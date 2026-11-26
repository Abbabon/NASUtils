#!/usr/bin/env python3
"""Best-effort metadata enrichment for a live Calibre library running in a Docker container on a NAS.

Runs on the Mac, drives the container over ssh + `docker exec`. Writes only through the Calibre
content server (calibredb --with-library http://...), never to metadata.db. Stdlib only.
Settings come from the repo-root .env (NAS_USER, NAS_IP, CALIBRE_PASSWORD) - see README.md.
"""
import argparse, difflib, json, os, re, shlex, subprocess, sys, time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
CONTAINER = os.environ.get("CALIBRE_CONTAINER", "calibre-1")
DOCKER = "/usr/local/bin/docker"
LIB_URL = "http://localhost:8081/#Calibre_Library"   # as seen from inside the container
LIB_DIR = "/config/Calibre Library"                   # container path
HOST_DB = "/volume2/docker/calibre/Calibre Library/metadata.db"
BACKUP_DIR = "/volume2/docker/calibre/backups"
CONTAINER_COVERS = "/tmp/calibre-import/covers"       # ephemeral, inside the container
THRESHOLD = 0.8
TIDY_CONF = 0.85              # min confidence to replace a real title by a same-work one
CORRECT_CONF = 0.85           # min confidence for `correct`
FIELDS = {"title", "authors", "series", "series_index", "tags", "publisher", "pubdate",
          "languages", "identifiers", "comments", "cover"}
REVIEW_TAG = "needs-review"   # the content server cannot create custom columns (calibredb add_custom_column is refused), so a tag it is
REVIEW_COL = "needs_review"    # journal field name

# ---------------------------------------------------------------- pure logic

def isbn_valid(s):
    s = re.sub(r"[-\s]", "", s or "")
    if re.fullmatch(r"\d{9}[\dXx]", s):
        return sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(s)) % 11 == 0
    if re.fullmatch(r"97[89]\d{10}", s):
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(s)) % 10 == 0
    return False

ASIN = re.compile(r"\bB0[0-9A-Z]{8}\b")
ASIN_PARTIAL_TAIL = re.compile(r"\s+B0[0-9A-Z]{2,7}$")      # title was truncated mid-ASIN
ISBN_TOKEN = re.compile(r"(?<![\d-])(97[89][\d-]{10,14}|\d{9}[\dXx])(?![\d])")
EXT = re.compile(r"\.(pdf|epub|mobi|azw3?|kfx|cbz|cbr|zip|rar|txt|docx?|indd|indb)$", re.I)
MSOFFICE = re.compile(r"^Microsoft (Word|PowerPoint|Excel) - ", re.I)
LEAD_ID = re.compile(r"^\d{5,8}-(?=\S)")                     # DriveThruRPG-style product id prefix

def find_isbn(text):
    for m in ISBN_TOKEN.finditer(text or ""):
        if isbn_valid(m.group(1)):
            return re.sub(r"-", "", m.group(1)).upper()
    return None

def filename_like(title):
    """Conservative: only clear filename artefacts, not merely ugly titles."""
    t = (title or "").strip()
    if not t:
        return True
    return bool(MSOFFICE.match(t) or ASIN.search(t) or ASIN_PARTIAL_TAIL.search(t) or EXT.search(t) or re.search(r"_|(?<=\w)\+(?=\w)", t)   # "C++" is a title, "a+b" a filename
                or LEAD_ID.match(t) or re.fullmatch(r"[\d\-Xx]{1,}", t)
                or re.fullmatch(r"[A-Za-z0-9]+(-[A-Za-z0-9.]+){2,}", t))

def clean_title(title):
    """-> (cleaned title, asin or None, isbn or None). Cleaned may be '' if nothing is left."""
    t = (title or "").strip()
    m = ASIN.search(t)
    asin = m.group(0) if m else None
    isbn = find_isbn(t)
    t = EXT.sub("", t)
    t = ASIN.sub("", t)
    t = ASIN_PARTIAL_TAIL.sub("", t)
    t = LEAD_ID.sub("", MSOFFICE.sub("", t))
    if isbn:
        t = ISBN_TOKEN.sub("", t)
    t = re.sub(r"_|(?<=\w)\+(?=\w)", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -")
    if re.fullmatch(r"[\d\-Xx ]*", t):   # only digits left: not a title
        t = ""
    return t, asin, isbn

JUNK_AUTHORS = ("unknown", "unbekannt", "anonymous", "administrator", "admin", "user", "owner")
BARE_USERNAME = re.compile(r"[a-z][a-z0-9_]+")   # one all-lowercase token, e.g. "michael", "jeff", "brian2"

def unknown_author(a):
    """Empty/'Unknown' or file-creator junk (Administrator, a bare lowercase username): replaceable, never trusted."""
    a = (a if isinstance(a, str) else " & ".join(a or [])).strip()
    return not a or a.lower() in JUNK_AUTHORS or bool(BARE_USERNAME.fullmatch(a))

def pubdate_empty(p):
    return not p or p[:4] <= "0101"

def gaps(b):
    g = []
    if filename_like(b.get("title")): g.append("title")
    if unknown_author(b.get("authors")): g.append("authors")
    if not b.get("comments"): g.append("description")
    if not (b.get("identifiers") or {}).get("isbn") and not b.get("isbn"): g.append("isbn")
    if not b.get("tags"): g.append("tags")
    if not b.get("publisher"): g.append("publisher")
    if not b.get("languages"): g.append("language")
    if not b.get("cover"): g.append("cover")
    return g

KIND_PATTERNS = [(re.compile(r"character sheet|sheet\b", re.I), "RPG"),
                 (re.compile(r"\b(rpg|d&d|dungeons|pathfinder|5e|osr)\b", re.I), "RPG")]

def kind_tags(b):
    tags = []
    fm = {f.upper() for f in b.get("formats", [])}
    if fm and fm <= {"CBZ", "CBR", "CB7"}:
        tags.append("Comics")
    for rx, tag in KIND_PATTERNS:
        if rx.search(b.get("title") or "") and tag not in tags:
            tags.append(tag)
    return tags

def cleanup_proposal(b):
    """Free, deterministic proposal for one book, or None."""
    f, why = {}, []
    t, asin, isbn = clean_title(b["title"])
    ids = b.get("identifiers") or {}
    new_ids = {}
    if asin and "amazon" not in ids: new_ids["amazon"] = asin; why.append("ASIN in title")
    if isbn and "isbn" not in ids: new_ids["isbn"] = isbn; why.append("valid ISBN in title")
    if new_ids: f["identifiers"] = new_ids
    if filename_like(b["title"]) and t and t != b["title"]:
        f["title"] = t; why.append("title cleaned")
    kt = kind_tags(b)
    if kt and not b.get("tags"): f["tags"] = kt; why.append("kind from format/title")
    if not f:
        return None
    return {"id": b["id"], "fields": f, "confidence": 0.85, "source": "cleanup", "reason": "; ".join(why)}

def effective(b, props):
    """Book as it would look after applying the proposals (used so lookup sees cleanup's identifiers/title)."""
    b = json.loads(json.dumps(b))
    for p in props:
        if p["confidence"] < THRESHOLD: continue
        ch = plan(b, p["fields"], p["confidence"])
        for fld, c in ch.items():
            b[fld] = c["value"]
        if "title" in ch: b["title_open"] = p["source"] == "cleanup"
    return b

def norm_list(v, sep=","):
    if v is None: return []
    if isinstance(v, str): v = re.split(r"\s*&\s*" if sep == "&" else r"\s*,\s*", v)
    return [x.strip() for x in v if x and x.strip()]

def title_tokens(t):
    t = re.sub(r"[^a-z0-9]+", " ", re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", (t or "").lower()))
    return set(t.split())

def same_work(old, new):
    """Conservative: the shorter title's tokens (>= 2, case/punctuation-insensitive, letter/digit split) are >= 80% inside the other."""
    a, b = sorted((title_tokens(old), title_tokens(new)), key=len)
    if len(a) >= 2 and len(a & b) / len(a) >= 0.8: return True
    # run-together filename words ("theincal vol6"): the squashed shorter title inside the squashed longer one, digits not extended
    so, sn = sorted((re.sub(r"[^a-z0-9]", "", (old or "").lower()), re.sub(r"[^a-z0-9]", "", (new or "").lower())), key=len)
    return len(so) >= 10 and bool(re.search((r"(?<!\d)" if so[0].isdigit() else "") + re.escape(so) + (r"(?!\d)" if so[-1].isdigit() else ""), sn))

def plan(book, fields, conf=0):
    """Fill-empty-only merge (authors: also junk ones; title: see title_open; callers gate by confidence). -> {field: {old, new, value, arg}}; `arg` is the calibredb --field value,
    `value` the resulting field value on the book dict."""
    out = {}
    def put(k, old, value, arg):
        out[k] = {"old": old, "new": value, "value": value, "arg": arg}
    for k, v in fields.items():
        if v in (None, "", [], {}): continue
        if k == "title":
            # replaceable while filename-like, or while only cleanup's mechanical guess replaced a filename-like title
            if filename_like(v) or v == book.get("title"): continue
            if filename_like(book.get("title")) or book.get("title_open") or (conf >= TIDY_CONF and same_work(book.get("title"), v)):
                put(k, book.get("title"), v, v)
        elif k == "authors":
            a = norm_list(v, "&")
            if unknown_author(book.get("authors")) and a and not unknown_author(a):
                put(k, book.get("authors"), " & ".join(a), " & ".join(a))
        elif k == "series":
            if not book.get("series"):
                put(k, "", v, v)
                if fields.get("series_index") is not None:
                    out["series_index"] = {"old": book.get("series_index"), "new": float(fields["series_index"]),
                                           "value": float(fields["series_index"]), "arg": str(fields["series_index"])}
        elif k == "series_index":
            pass  # only with series
        elif k == "tags":
            have = list(book.get("tags") or [])
            low = {t.lower() for t in have}
            add = [t.replace(",", " ") for t in norm_list(v) if t.lower() not in low]
            if add:
                put(k, have, have + add, ",".join(have + add))
        elif k == "identifiers":
            have = dict(book.get("identifiers") or {})
            add = {a: str(b) for a, b in v.items() if a not in have and b and not re.search(r"[,:]", str(b))
                   and (a != "isbn" or isbn_valid(str(b)))}
            if add:
                merged = {**have, **add}
                put(k, have, merged, ",".join(f"{a}:{b}" for a, b in merged.items()))
        elif k in ("publisher", "comments", "languages"):
            if not book.get(k):
                val = norm_list(v) if k == "languages" else v
                if k == "comments" and "<" not in val: val = "<p>" + val.replace("\n\n", "</p><p>") + "</p>"
                put(k, book.get(k), val, ",".join(val) if k == "languages" else val)
        elif k == "pubdate":
            if pubdate_empty(book.get("pubdate")):
                # a bare YYYY-MM-DD is parsed in the server's local zone and the 1st of a month reads back a day late
                v = f"{v}T00:00:00+00:00" if re.fullmatch(r"\d{4}-\d\d-\d\d", v) else v
                put(k, book.get("pubdate"), v, v)
        elif k == "cover":
            if not book.get("cover"): put(k, 0, 1, v)
    return out

def gate(props, threshold=THRESHOLD):
    """-> (apply, review) split by confidence."""
    return ([p for p in props if p["confidence"] >= threshold], [p for p in props if p["confidence"] < threshold])

def validate_proposal(p):
    if not isinstance(p, dict) or not isinstance(p.get("id"), int): return "id must be an integer"
    if not isinstance(p.get("fields"), dict) or not p["fields"]: return "fields must be a non-empty object"
    bad = set(p["fields"]) - FIELDS
    if bad: return f"unknown fields {sorted(bad)}"
    c = p.get("confidence")
    if not isinstance(c, (int, float)) or not 0 <= c <= 1: return "confidence must be 0..1"
    if not p.get("source"): return "source missing"
    return None

def parse_opf(text):
    """fetch-ebook-metadata --opf output -> dict of proposal fields (no filtering)."""
    text = text[text.index("<?xml"):] if "<?xml" in text else text[text.index("<package"):]
    ns = {"dc": "http://purl.org/dc/elements/1.1/", "o": "http://www.idpf.org/2007/opf"}
    r = ET.fromstring(text)
    g = lambda tag: [e.text.strip() for e in r.iterfind(f".//dc:{tag}", ns) if e.text and e.text.strip()]
    ids = {}
    for e in r.iterfind(".//dc:identifier", ns):
        s = (e.get("{http://www.idpf.org/2007/opf}scheme") or "").lower()
        if s and s not in ("calibre", "uuid") and e.text: ids[s] = e.text.strip()
    f = {"title": (g("title") or [""])[0], "authors": g("creator"), "comments": (g("description") or [""])[0],
         "publisher": (g("publisher") or [""])[0], "languages": g("language"), "tags": g("subject")[:6],
         "identifiers": ids}
    d = (g("date") or [""])[0][:10]
    if d and d[:4] > "1000": f["pubdate"] = d
    for m in r.iterfind(".//o:meta", ns):
        if m.get("name") == "calibre:series": f["series"] = m.get("content")
        if m.get("name") == "calibre:series_index": f["series_index"] = float(m.get("content"))
    return f

def sim(a, b):
    n = lambda s: re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
    a, b = n(a).strip(), n(b).strip()
    r = difflib.SequenceMatcher(None, a, b).ratio()
    short, long_ = sorted((a, b), key=len)
    return max(r, 0.95) if len(short) >= 6 and short in long_ else r   # subtitle/series suffixes

def edition_safe(f):
    """A lookup not keyed on the book's own ISBN may have found another edition: drop edition-specific fields."""
    f = {k: v for k, v in f.items() if k not in ("pubdate", "publisher")}
    if "identifiers" in f: f["identifiers"] = {k: v for k, v in f["identifiers"].items() if k != "isbn"}
    return f

def lookup_confidence(book, found, mode):
    """Trust identifier hits, but downgrade when a real current title disagrees with the result.
    Without an ISBN, only a title+author match with a trustworthy (non-junk) author reaches 0.85."""
    ts = sim(clean_title(book["title"])[0] or book["title"], found["title"])
    last = lambda a: a.split()[-1].lower() if a.split() else ""
    auth_ok = not unknown_author(book.get("authors")) and any(last(x) in found["authors"][i].lower()
              for x in norm_list(book["authors"], "&") for i in range(len(found["authors"])))
    real_title = not filename_like(book["title"])
    if mode == "isbn":
        return (0.9 if ts >= 0.5 or not real_title else 0.6), f"ISBN match, title similarity {ts:.2f}"
    if mode == "title":   # no ISBN and no trustworthy author: never trusted, only flagged for review
        return 0.5, f"title-only search, title similarity {ts:.2f}"
    return (0.85 if ts >= 0.85 and auth_ok else 0.5), f"title+author search, title similarity {ts:.2f}, author match {auth_ok}"

# ---------------------------------------------------------------- remote plumbing

def load_env():
    env = {}
    p = HERE.parent / ".env"
    for line in p.read_text().splitlines() if p.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    for k in ("NAS_USER", "NAS_IP", "CALIBRE_PASSWORD"):
        env[k] = os.environ.get(k, env.get(k, ""))
        if not env[k]: sys.exit(f"missing {k} (set in repo-root .env)")
    return env

class Err(RuntimeError): pass
NOISE = re.compile(r"qrhi|vulkan|sandbox|gpu vendor|createplatform|qt\.|getpass|echo|enter the password", re.I)

def remote(cmd, stdin=None, timeout=300):
    """Run argv on the NAS over ssh. The password only ever travels on stdin and is scrubbed from output."""
    env = load_env()
    argv = ["ssh", "-o", "BatchMode=yes", f"{env['NAS_USER']}@{env['NAS_IP']}", shlex.join(cmd)]
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Err("timeout")
    scrub = lambda s: s.replace(env["CALIBRE_PASSWORD"], "***").replace(env["NAS_IP"], "<nas>")
    out, err = scrub(p.stdout), scrub(p.stderr)
    if p.returncode:
        err = "\n".join(l for l in err.splitlines() if not NOISE.search(l))
        raise Err(f"{cmd[0]} exit {p.returncode}: {err.strip() or out.strip()}"[:600])
    return out

def dexec(*cmd, stdin=None, timeout=300):
    return remote([DOCKER, "exec", "-i", CONTAINER, *cmd], stdin=stdin, timeout=timeout)

def cdb(*args, timeout=300):
    """calibredb through the content server; password via <f:/dev/stdin> so it is never in argv."""
    return dexec("calibredb", *args, "--with-library", LIB_URL, "--username", "amit",
                 "--password", "<f:/dev/stdin>", stdin=load_env()["CALIBRE_PASSWORD"], timeout=timeout)

def list_books(search=None):
    a = ["list", "--for-machine", "--fields", "all"] + (["--search", search] if search else [])
    out = cdb(*a, timeout=600)
    return json.loads(out[out.index("["):] if "[" in out else "[]")

def list_by_ids(ids):
    got = {}
    for i in range(0, len(ids), 40):
        for b in list_books(" or ".join(f"id:{x}" for x in ids[i:i + 40])):
            got[b["id"]] = b
    return got

# ---------------------------------------------------------------- work files

def jread(path):
    p = Path(path)
    if not p.exists(): return []
    txt = p.read_text().strip()
    if txt.startswith("["): return json.loads(txt)
    return [json.loads(l) for l in txt.splitlines() if l.strip()]

def jwrite(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

def load_export():
    p = WORK / "export.json"
    if not p.exists(): sys.exit("run `export` first")
    return json.loads(p.read_text())

def pick(books, a):
    if a.ids:
        raw = Path(a.ids[1:]).read_text() if a.ids.startswith("@") else a.ids
        want = {int(x) for x in re.split(r"[,\s]+", raw.strip()) if x}
        books = [b for b in books if b["id"] in want]
    return books[:a.limit] if a.limit else books

# ---------------------------------------------------------------- subcommands

def cmd_backup(a):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = f"{BACKUP_DIR}/metadata-{ts}.db"
    remote(["mkdir", "-p", BACKUP_DIR])
    remote(["/usr/bin/sqlite3", "-readonly", HOST_DB, f".backup '{dst}'"])
    res = remote(["/usr/bin/sqlite3", dst, "pragma integrity_check; select count(*) from books;"]).split()
    print(f"{dst}\nintegrity_check={res[0]} books={res[-1]}")
    if res[0] != "ok": sys.exit("integrity check FAILED")

def backup_fresh():
    return remote(["find", BACKUP_DIR, "-name", "metadata-*.db", "-mmin", "-1440"]).strip() != ""

def cmd_export(a):
    books = list_books()
    files = {}
    for rel in dexec("find", LIB_DIR, "-mindepth", "3", "-maxdepth", "3", "-type", "f", "-printf", "%P\\n").splitlines():
        m = re.search(r"/[^/]*\((\d+)\)/([^/]+)$", "/" + rel)
        if m and m.group(2) not in ("cover.jpg", "metadata.opf"):
            files.setdefault(int(m.group(1)), []).append(rel)
    for b in books:
        b["files"] = files.get(b["id"], [])
        b["gaps"] = gaps(b)
    WORK.mkdir(exist_ok=True)
    (WORK / "export.json").write_text(json.dumps(books, ensure_ascii=False))
    if not (WORK / "baseline.json").exists():
        (WORK / "baseline.json").write_text(json.dumps(books, ensure_ascii=False))
    print(f"exported {len(books)} books -> work/export.json")
    print_gaps(books)

def print_gaps(books, label=""):
    c = {}
    for b in books:
        for g in gaps(b): c[g] = c.get(g, 0) + 1
    print(label + ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda x: -x[1])), f"(of {len(books)})")

def cmd_cleanup(a):
    props = [p for b in pick(load_export(), a) if (p := cleanup_proposal(b))]
    jwrite(a.out, props)
    print(f"{len(props)} cleanup proposals -> {a.out}")

def cmd_lookup(a):
    books = pick(load_export(), a)
    cache = WORK / "lookup_cache"; cache.mkdir(parents=True, exist_ok=True)
    props, nothing, skipped, times = [], 0, 0, []
    earlier = {}   # agent (etc.) proposals applied after cleanup, before lookup
    for f in a.after or []:
        for p in jread(f): earlier.setdefault(p["id"], []).append(p)
    for b in books:
        eff = effective(b, [p for p in [cleanup_proposal(b)] if p] + earlier.get(b["id"], []))
        ids = eff.get("identifiers") or {}
        isbn = ids.get("isbn")
        had_asin = bool(clean_title(b["title"])[1] or ids.get("amazon"))
        author_known = not unknown_author(eff["authors"])
        mode = "isbn" if isbn else "title+author" if author_known else "title" if had_asin else None
        if mode is None or (mode != "isbn" and filename_like(eff["title"])):
            skipped += 1; continue
        # ponytail: calibre's Amazon source cannot resolve an ASIN alone (verified: always "no results"), so no ASIN query
        cf = cache / f"{b['id']}.opf"
        if cf.exists() and not a.refresh:
            raw = cf.read_text()
        else:
            base = ["sh", "-c", f'mkdir -p {CONTAINER_COVERS} && exec fetch-ebook-metadata "$@"', "sh", "--opf", "--timeout", "30"]
            if not b.get("cover"): base += ["--cover", f"{CONTAINER_COVERS}/{b['id']}.jpg"]
            if isbn: queries = [["--isbn", isbn]]
            else:   # long subtitles/series suffixes defeat the search: retry with a shorter title
                t1 = re.sub(r"\s*[(\[].*", "", eff["title"]).strip() or eff["title"]
                queries = [["--title", t] for t in dict.fromkeys([t1, " ".join(t1.split()[:6])])]
                if author_known: queries = [q + ["--authors", eff["authors"]] for q in queries]
            t0, raw = time.time(), ""
            for q in queries:
                try: raw = dexec(*base, *q, timeout=120)
                except Err as e:
                    if "identify query" not in str(e):   # a real failure (ssh, timeout): don't cache, move on
                        print(f"  id {b['id']}: {str(e)[:100]}", file=sys.stderr); raw = None; break
                    raw = ""
                if "<package" in (raw or ""): break
                time.sleep(a.delay)
            if raw is None: continue
            times.append(time.time() - t0)
            raw = raw if "<package" in raw else "NONE"
            cf.write_text(raw)
            time.sleep(a.delay)
        if raw == "NONE":
            nothing += 1; print(f"  id {b['id']}: no result"); continue
        found = parse_opf(raw)
        conf, why = lookup_confidence(eff, found, mode)
        f = {k: v for k, v in found.items() if v and k != "tags"}   # google categories are noise
        if mode != "isbn": f = edition_safe(f)
        if not filename_like(eff["title"]): f.pop("title", None)   # lookup titles are noisy; they only fill a filename-like one
        if not b.get("cover"):
            f["cover"] = f"{CONTAINER_COVERS}/{b['id']}.jpg"
        ch = plan(eff, f)
        if not b.get("cover") and "cover" in ch and not has_cover_file(b["id"]): del ch["cover"]
        if ch:
            fields = {k: f[k] for k in ch if k in f}
            if "identifiers" in fields:
                fields["identifiers"] = {x: y for x, y in f["identifiers"].items() if x not in ids}
            props.append({"id": b["id"], "fields": fields, "confidence": conf, "source": "lookup", "reason": why,
                          **({"lookup_authors": found["authors"]} if found["authors"] else {})})
        else:
            nothing += 1
    jwrite(a.out, props)
    avg = sum(times) / len(times) if times else 0
    print(f"{len(props)} proposals, {nothing} nothing found/nothing to add, {skipped} skipped (no trustworthy key), "
          f"avg {avg:.1f}s per live fetch over {len(times)} -> {a.out}")

def has_cover_file(i):
    try: return dexec("test", "-s", f"{CONTAINER_COVERS}/{i}.jpg") is not None
    except Err: return False

# Runs inside the container (prefixed to EXTRACT) and here (tests): drops purchaser watermarks and CSS from excerpts.
SCRUB = r'''
import re
WATERMARK = re.compile(r"(\b(order|invoice|transaction)\s*(#|no\.?|number|id)?\s*:?\s*\d{5,}"
                       r"|\b(purchased by|licensed to|downloaded by|generated for|prepared for|personali[sz]ed for|registered to)\b"
                       r"|\bwatermark|drivethrurpg\.com/.*(order|download)|\S+@\S+\.\w+.*\d{5,})", re.I)
CSS = re.compile(r"<(style|script)\b.*?</\1>|@(page|font-face|media|import)\b[^{;]*(\{[^{}]*\}|;)|[^{}<>]{0,80}\{[^{}]*:[^{}]*\}", re.I | re.S)
def scrub(t):
    t = CSS.sub(" ", t)
    return "\n".join(l for l in t.splitlines() if not WATERMARK.search(l))
'''
exec(SCRUB)

EXTRACT = SCRUB + r'''
import json,sys,subprocess,zipfile,html,posixpath,os
CAP=int(sys.argv[1])
def clean(t): return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",scrub(t)))).strip()
def epub(p):
    z=zipfile.ZipFile(p); names=z.namelist()
    try:
        opf=re.search(r'full-path="([^"]+)"',z.read("META-INF/container.xml").decode("utf8","ignore")).group(1)
        o=z.read(opf).decode("utf8","ignore"); base=posixpath.dirname(opf)
        man=dict(re.findall(r'<item[^>]*?id="([^"]+)"[^>]*?href="([^"]+)"',o))
        man.update({a:b for b,a in re.findall(r'<item[^>]*?href="([^"]+)"[^>]*?id="([^"]+)"',o)})
        order=[posixpath.normpath(posixpath.join(base,man[i])) for i in re.findall(r'<itemref[^>]*?idref="([^"]+)"',o) if i in man]
    except Exception: order=sorted(n for n in names if n.endswith(("html","htm")))
    out=""
    for n in order:
        if n in names:
            out+=" "+clean(z.read(n).decode("utf8","ignore"))
            if len(out)>CAP: break
    return out.strip()
res={}
for j in json.load(sys.stdin):
    i,p,f=j["id"],j["path"],j["fmt"]; text,listing="",[]
    try:
        if f=="PDF":
            text=scrub(subprocess.run(["pdftotext","-l","8","-nopgbrk",p,"-"],capture_output=True,text=True,timeout=60).stdout)
        elif f=="EPUB": text=epub(p)
        elif f in("CBZ","ZIP","KFX-ZIP"):
            n=zipfile.ZipFile(p).namelist(); listing=[len(n)]+n[:30]
        elif f in("MOBI","AZW3","AZW","TXT","DOCX","RTF","LIT","FB2"):
            if f=="TXT": text=scrub(open(p,errors="ignore").read(CAP*2))
            else:
                x="/tmp/ci_x.txt"
                if os.path.exists(x): os.remove(x)   # a failed conversion must never inherit the previous book's output
                subprocess.run(["ebook-convert",p,x],capture_output=True,timeout=120)
                text=scrub(open(x,errors="ignore").read(CAP*4)) if os.path.exists(x) else ""
    except Exception as e: text="";listing=["extract error: "+str(e)[:100]]
    res[i]={"text":re.sub(r"\s+"," ",text).strip()[:CAP],"listing":listing}
print(json.dumps(res))
'''
FMT_ORDER = ["EPUB", "PDF", "AZW3", "MOBI", "AZW", "DOCX", "TXT", "KFX-ZIP", "CBZ", "ZIP"]

def found_ids(b):
    """ASINs and valid ISBNs found in title, file names and identifier values."""
    text = " ".join([b.get("title") or "", *map(str, b.get("files") or []), *map(str, (b.get("identifiers") or {}).values())])
    isbns = [re.sub("-", "", m.group(1)).upper() for m in ISBN_TOKEN.finditer(text) if isbn_valid(m.group(1))]
    return {"asin": sorted(set(ASIN.findall(text))), "isbn": sorted(set(isbns))}

def same_author(b, allbooks, cap=8):
    """Other library books by the same (known) author: titles and series names, to keep series naming consistent."""
    if unknown_author(b.get("authors")): return {}
    o = [x for x in allbooks if x["id"] != b["id"] and x["authors"] == b["authors"]]
    return {"titles": [x["title"] for x in o][:cap], "series": sorted({x["series"] for x in o if x.get("series")})}

def cmd_excerpt(a):
    allbooks = load_export()
    books = pick(allbooks, a)
    if not a.ids:
        books = [b for b in books if set(b["gaps"]) & {"title", "authors", "description", "tags"}]
    if a.limit: books = books[:a.limit]
    jobs = []
    for b in books:
        rank = lambda f: FMT_ORDER.index(f.split(".")[-1].upper()) if f.split(".")[-1].upper() in FMT_ORDER else 99
        fs = sorted(b["files"], key=rank)
        if fs:
            jobs.append({"id": b["id"], "path": f"{LIB_DIR}/{fs[0]}", "fmt": fs[0].split(".")[-1].upper()})
    # resumable: per-book results are cached in work/excerpt_cache/; a failing chunk is retried book by book, failures are recorded
    cache = WORK / "excerpt_cache"; cache.mkdir(parents=True, exist_ok=True)
    ex = {}
    for j in jobs:
        f = cache / f"{j['id']}.json"
        if f.exists() and not a.refresh and json.loads(f.read_text()).get("cap") == a.cap: ex[str(j["id"])] = json.loads(f.read_text())
    todo = [j for j in jobs if str(j["id"]) not in ex]
    def run(chunk):
        return json.loads(dexec("python3", "-c", EXTRACT, str(a.cap), stdin=json.dumps(chunk), timeout=900))
    def save(i, r):
        r["cap"] = a.cap; ex[str(i)] = r; (cache / f"{i}.json").write_text(json.dumps(r, ensure_ascii=False))
    print(f"{len(jobs)} books with files, {len(jobs) - len(todo)} cached, {len(todo)} to extract", flush=True)
    for n in range(0, len(todo), 10):
        chunk = todo[n:n + 10]
        try: res = run(chunk)
        except (Err, ValueError):
            res = {}
            for j in chunk:
                try: res.update(run([j]))
                except (Err, ValueError) as e: res[str(j["id"])] = {"text": "", "listing": [], "failed": str(e)[:150]}
        for j in chunk: save(j["id"], res.get(str(j["id"]), {"text": "", "listing": [], "failed": "no result"}))
        print(f"  {min(n + 10, len(todo))}/{len(todo)}", flush=True)
    recs = []
    for b in books:
        e = ex.get(str(b["id"]), {"text": "", "listing": []})
        recs.append({"id": b["id"], "title": b["title"], "authors": b["authors"], "tags": b["tags"],
                     "identifiers": b["identifiers"], "series": b.get("series"), "publisher": b.get("publisher"),
                     "languages": b["languages"], "has_description": bool(b.get("comments")),
                     "formats": b["formats"], "files": [Path(f).name for f in b["files"]], "gaps": b["gaps"],
                     "found_ids": found_ids(b), "same_author": same_author(b, allbooks),
                     "excerpt": e["text"], "archive_listing": e["listing"], **({"extract_failed": e["failed"]} if e.get("failed") else {})})
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    n = 0
    for i in range(0, len(recs), a.size):
        n += 1; jwrite(out / f"batch_{n:03d}.jsonl", recs[i:i + a.size])
    print(f"{len(recs)} books, {n} batch file(s) in {out}; {sum(1 for r in recs if r['excerpt'])} have text")

def set_review(b):
    tags = list(b.get("tags") or [])
    if REVIEW_TAG not in tags:
        cdb("set_metadata", str(b["id"]), "--field", "tags:" + ",".join(tags + [REVIEW_TAG]))
        b["tags"] = tags + [REVIEW_TAG]

def cmd_apply(a):
    props, bad = [], 0
    for p in jread(a.proposals):
        e = validate_proposal(p)
        if e: bad += 1; print(f"reject {p.get('id') if isinstance(p, dict) else p}: {e}", file=sys.stderr)
        else: props.append(p)
    props = [p for p in props if (not a.ids) or p["id"] in {int(x) for x in a.ids.split(",")}]
    if a.limit: props = props[:a.limit]
    if a.apply:
        if not backup_fresh(): sys.exit("refusing to apply: no backup younger than 24h (run `backup`)")
    live = list_by_ids(sorted({p["id"] for p in props}))
    jp = WORK / "journal.jsonl"
    stats = {"applied": 0, "review": 0, "noop": 0, "missing": 0}
    jr = jread(jp)
    flagged = {r["book"] for r in jr if r["field"] == REVIEW_COL}
    bp = WORK / "baseline.json"
    base_title = {b["id"]: b["title"] for b in json.loads(bp.read_text())} if bp.exists() else {}
    for i, b in live.items():   # title still replaceable if only cleanup changed a filename-like baseline title
        h = [r for r in jr if r["book"] == i and r["field"] == "title"]
        b["title_open"] = bool(h) and filename_like(base_title.get(i)) and all(r["source"] == "cleanup" for r in h) and h[-1]["new"] == b["title"]
    for p in props:
        b = live.get(p["id"])
        if not b: stats["missing"] += 1; continue
        if p["confidence"] < THRESHOLD:
            if p["id"] in flagged or REVIEW_TAG in (b.get("tags") or []): stats["noop"] += 1; continue
            print(f"id {p['id']}: conf {p['confidence']} < {THRESHOLD} -> tag {REVIEW_TAG} ({p['source']}: {p.get('reason','')})")
            if a.apply:
                set_review(b); flagged.add(p["id"])
                jappend(jp, p, REVIEW_COL, None, True)
            stats["review"] += 1; continue
        ch = plan(b, p["fields"], p["confidence"])
        if not ch: stats["noop"] += 1; continue
        print(f"id {p['id']} [{p['source']} {p['confidence']}]: " + "; ".join(f"{k}: {c['old']!r} -> {c['new']!r}"[:140] for k, c in ch.items()))
        if a.apply:
            args = ["set_metadata", str(p["id"])]
            for k, c in ch.items(): args += ["--field", f"{k}:{c['arg']}"]
            cdb(*args)
            for k, c in ch.items():
                jappend(jp, p, k, c["old"], c["new"]); b[k] = c["value"]
            if "title" in ch: b["title_open"] = p["source"] == "cleanup"
        stats["applied"] += 1
    print(("APPLIED " if a.apply else "DRY-RUN (use --apply) ") + json.dumps(stats) + (f", {bad} rejected" if bad else ""))

CFIELDS = {"title", "authors", "publisher", "tags", "identifiers", "series", "pubdate", "languages"}

def nrm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", str(s or "").lower())).strip()

def names(v):
    """authors as a list of names: string with & ; 'and' joins, or list"""
    v = " & ".join(v) if isinstance(v, (list, tuple)) else (v or "")
    return [x.strip() for x in re.split(r"\s*(?:&|;|\band\b)\s*", v) if x.strip()]

def close(a, b):
    a, b = nrm(a), nrm(b)
    return bool(a) and (a == b or a.replace(" ", "") == b.replace(" ", "") or difflib.SequenceMatcher(None, a, b).ratio() >= 0.9)

def id_pairs(v):
    """identifiers as {key: value or None}: dict, 'k:v,k2', or list of those"""
    if isinstance(v, dict): return {str(k): (str(x) if x else None) for k, x in v.items()}
    out = {}
    for it in ([v] if isinstance(v, str) else v or []):
        for part in it.split(","):
            k, _, x = part.strip().partition(":")
            if k: out[k.strip()] = x.strip() or None
    return out

def correction_plan(b, c):
    """Replace a WRONG value. -> ("apply", old, new, arg) | ("stale",) | ("noop",) | ("invalid", why).
    `current` must still match the live value (forgiving); a value that is something else entirely is stale."""
    f, cur, prop = c["field"], c.get("current"), c.get("proposed")
    have = b.get(f)
    if f in ("title", "publisher", "series"):
        if f == "title" and not prop: return ("invalid", "title cannot be cleared")
        if not isinstance(prop, (str, type(None))): return ("invalid", f"{f} must be a string or null")
        if (prop is None and not have) or (prop and nrm(prop) == nrm(have)): return ("noop",)
        if not close(have, cur): return ("stale",)
        return ("apply", have or "", prop or "", prop or "")
    if f == "authors":
        bk, cu = names(have), names(cur)
        pn = ["Unknown"] if prop is None else names(prop)
        if not pn: return ("invalid", "authors empty")
        if {nrm(x) for x in pn} == {nrm(x) for x in bk}: return ("noop",)
        if not cu or not ({nrm(x) for x in cu} <= {nrm(x) for x in bk} or close(" ".join(cu), " ".join(bk))): return ("stale",)
        return ("apply", have, " & ".join(pn), " & ".join(pn))
    if f == "tags":
        hv = list(have or []); low = {t.lower() for t in hv}
        cu = {t.lower() for t in norm_list(cur)}
        pr = [t.replace(",", " ") for t in norm_list(prop)]
        present = cu & low
        if not present:
            return ("noop",) if cu and all(p.lower() in low for p in pr) else ("stale",)
        new = [t for t in hv if t.lower() not in present]
        new += [p for p in pr if p.lower() not in {t.lower() for t in new}]
        return ("apply", hv, new, ",".join(new))
    if f == "identifiers":
        hv = dict(have or {}); cu = id_pairs(cur); pr = id_pairs(prop)
        if not cu: return ("invalid", "identifiers current missing")
        if any(not v or re.search(r"[,:]", v) or (k == "isbn" and not isbn_valid(v)) for k, v in pr.items()): return ("invalid", f"bad proposed identifier {pr}")
        eq = lambda x, y: re.sub(r"[-\s]", "", x or "").lower() == re.sub(r"[-\s]", "", y or "").lower()
        present = [k for k, v in cu.items() if k in hv and (v is None or eq(v, hv[k]))]
        if not present:
            if any(k in hv for k in cu): return ("stale",)           # key there, value is another one
            return ("noop",) if all(k in hv and eq(v, hv[k]) for k, v in pr.items()) else ("stale",)
        new = {k: v for k, v in hv.items() if k not in present}; new.update(pr)
        return ("apply", hv, new, ",".join(f"{k}:{v}" for k, v in new.items()))
    if f == "pubdate":
        if prop is not None and not re.fullmatch(r"\d{4}(-\d\d-\d\d)?", str(prop)): return ("invalid", "pubdate must be YYYY or YYYY-MM-DD")
        new = None if prop is None else (prop if len(prop) == 10 else f"{prop}-01-01")
        if (new is None and pubdate_empty(have)) or (new and not pubdate_empty(have) and have[:10] == new): return ("noop",)
        if pubdate_empty(have) or str(cur or "")[:4] != have[:4]: return ("stale",)
        v = f"{new}T00:00:00+00:00" if new else "0101-01-01T00:00:00+00:00"   # ponytail: calibre's "undefined" date as the clear value
        return ("apply", have, v, v)
    if f == "languages":
        hv = [x.lower() for x in have or []]; cu = {x.lower() for x in norm_list(cur)}; pr = [x.lower() for x in norm_list(prop)]
        if sorted(pr) == sorted(hv): return ("noop",)
        if not cu or cu != set(hv): return ("stale",)
        return ("apply", have, pr, ",".join(pr))

def validate_correction(c):
    if not isinstance(c, dict) or not isinstance(c.get("id"), int): return "id must be an integer"
    if c.get("field") not in CFIELDS: return f"field must be one of {sorted(CFIELDS)}"
    if "current" not in c or "proposed" not in c: return "current and proposed are required"
    if not isinstance(c.get("confidence"), (int, float)) or not 0 <= c["confidence"] <= 1: return "confidence must be 0..1"
    return None

def cmd_correct(a):
    rows, st = [], {"applied": 0, "stale": 0, "below-threshold": 0, "invalid": 0, "noop": 0, "missing": 0}
    for fn in a.files:
        for c in jread(fn):
            e = validate_correction(c)
            if e: st["invalid"] += 1; print(f"reject {c.get('id') if isinstance(c, dict) else c}: {e}", file=sys.stderr)
            elif not a.ids or c["id"] in {int(x) for x in a.ids.split(",")}: rows.append(c)
    if a.limit: rows = rows[:a.limit]
    if a.apply and not backup_fresh(): sys.exit("refusing to apply: no backup younger than 24h (run `backup`)")
    live = list_by_ids(sorted({c["id"] for c in rows if c["confidence"] >= CORRECT_CONF}))
    jp = WORK / "journal.jsonl"
    for c in rows:
        if c["confidence"] < CORRECT_CONF: st["below-threshold"] += 1; continue
        b = live.get(c["id"])
        if not b: st["missing"] += 1; continue
        r = correction_plan(b, c)
        if r[0] == "invalid": st["invalid"] += 1; print(f"reject {c['id']} {c['field']}: {r[1]}", file=sys.stderr); continue
        if r[0] != "apply": st[r[0]] += 1; continue
        _, old, new, arg = r
        print(f"{c['id']} {c['field']}: {old!r} -> {new!r}"[:200])
        if a.apply:
            cdb("set_metadata", str(c["id"]), "--field", f"{c['field']}:{arg}")
            jappend(jp, {"id": c["id"], "source": "correction", "confidence": c["confidence"]}, c["field"], old, new)
        b[c["field"]] = new
        st["applied"] += 1
    print(("APPLIED " if a.apply else "DRY-RUN (use --apply) ") + json.dumps(st))

def jappend(path, p, field, old, new):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "book": p["id"],
                            "field": field, "old": old, "new": new, "source": p["source"],
                            "confidence": p["confidence"]}, ensure_ascii=False) + "\n")

def cmd_report(a):
    if a.refresh: cmd_export(argparse.Namespace(ids=None, limit=None))
    base = json.loads((WORK / "baseline.json").read_text()) if (WORK / "baseline.json").exists() else []
    print_gaps(base, "before: ")
    print_gaps(load_export(), "now:    ")
    j = jread(WORK / "journal.jsonl")
    by = {}
    for r in j: by.setdefault((r["field"], r["source"]), set()).add(r["book"])
    print(f"journal: {len(j)} changes on {len({r['book'] for r in j})} books")
    for (f, s), ids in sorted(by.items()): print(f"  {f:14} {s:8} {len(ids)} books")
    fl = sorted({r["book"] for r in j if r["field"] == REVIEW_COL})
    print(f"flagged {REVIEW_COL}: {len(fl)} {fl[:30]}")

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    def sp(name, fn, **kw):
        s = sub.add_parser(name, **kw); s.set_defaults(fn=fn)
        s.add_argument("--ids", help="comma list of book ids, or @file"); s.add_argument("--limit", type=int)
        return s
    sp("backup", cmd_backup); sp("export", cmd_export)
    s = sp("cleanup", cmd_cleanup); s.add_argument("--out", default=str(WORK / "proposals/cleanup.jsonl"))
    s = sp("lookup", cmd_lookup); s.add_argument("--out", default=str(WORK / "proposals/lookup.jsonl"))
    s.add_argument("--delay", type=float, default=2.0); s.add_argument("--refresh", action="store_true")
    s.add_argument("--after", nargs="*", metavar="FILE", help="proposal files (cleanup, then agent) applied virtually before searching")
    s = sp("excerpt", cmd_excerpt); s.add_argument("--out-dir", default=str(WORK / "batches"))
    s.add_argument("--size", type=int, default=20); s.add_argument("--cap", type=int, default=6000); s.add_argument("--refresh", action="store_true")
    s = sp("apply", cmd_apply); s.add_argument("proposals"); s.add_argument("--apply", action="store_true")
    s = sp("correct", cmd_correct); s.add_argument("files", nargs="+"); s.add_argument("--apply", action="store_true")
    s = sp("report", cmd_report); s.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    try: a.fn(a)
    except Err as e: sys.exit(f"error: {e}")

if __name__ == "__main__":
    main()
