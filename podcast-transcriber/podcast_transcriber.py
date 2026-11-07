#!/usr/bin/env python3
"""Transcribe a podcast RSS feed with ElevenLabs Scribe (Hebrew, diarized) into one Markdown note per episode.

Usage: podcast_transcriber.py FEED_URL OUT_DIR [--dry-run] [--only TEXT] [--limit N] [--shortest]
                              [--speakers N] [--keyterms FILE] [--season N] [--guests REGEX] [--context FILE] [--polish] [--rerender] [--log-file PATH]
Layout: OUT_DIR/<YYYY-MM-DD - Title>.md, OUT_DIR/raw/<same>.json (raw API response), OUT_DIR/speakers.json.
speakers.json maps labels to names: {"*": {"speaker_0": "Host"}, "<note stem>": {"speaker_1": "Guest"}}.
Done = raw JSON exists (skipped). --rerender rewrites notes from raw JSON, no API calls.
--polish: `claude -p` (subscription, no API key) fixes names/terms/numbers and names the speakers; stored as
OUT_DIR/polished/<stem>.json (substring edits only) + speakers.json; raw JSON is never touched. Idempotent.
Key: ELEVENLABS_API_KEY from the environment or the repo-root .env. Never logged.
Last stdout line: "SUMMARY total=N todo=N done=N failed=N". Exit 1 if any episode failed.
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
API = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v2"
TIMEOUT = 4 * 3600  # per-socket-read; the sync request is silent until the transcript is ready
CHUNK_CHARS = 60000  # polish prompt size per call (~15-20k tokens of Hebrew)
POLISH_MODEL = "sonnet"
STAMP_EVERY = 120  # seconds between inline timestamps inside a long turn
log = logging.getLogger("transcriber")


def sanitize(title, limit=150):
    t = re.sub(r'[\x00-\x1f/\\:*?"<>|]', " ", title)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:limit].strip(" .") or "Untitled"


def direct_url(url):
    """Drop the podtrac redirect so ElevenLabs fetches media.transistor.fm directly."""
    m = re.match(r"https?://dts\.podtrac\.com/redirect\.mp3/(.+)", url)
    return "https://" + m.group(1) if m else url


def parse_feed(xml_bytes):
    """-> [dict(stem, title, date, url, link, secs)] oldest first."""
    eps = []
    for it in ET.fromstring(xml_bytes).find("channel").findall("item"):
        enc, pub = it.find("enclosure"), it.findtext("pubDate")
        if enc is None or not enc.get("url") or not pub:
            continue
        dt, title = parsedate_to_datetime(pub), it.findtext("title") or ""
        dur = (it.findtext(ITUNES + "duration") or "").strip()
        secs = sum(int(p) * 60 ** i for i, p in enumerate(reversed(dur.split(":")))) if re.fullmatch(r"[\d:]+", dur) else 0
        season = (it.findtext(ITUNES + "season") or "").strip()
        eps.append(dict(stem=f"{dt:%Y-%m-%d} - {sanitize(title)}", title=title, date=f"{dt:%Y-%m-%d}", season=season,
                        url=direct_url(enc.get("url")), link=it.findtext("link") or "", secs=secs,
                        desc=re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))))
    eps.sort(key=lambda e: (e["date"], e["url"]))
    seen = {}
    for e in eps:  # same-day same-title: " (2)", ...
        seen[e["stem"]] = seen.get(e["stem"], 0) + 1
        if seen[e["stem"]] > 1:
            e["stem"] += f" ({seen[e['stem']]})"
    return eps


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def turns_of(raw):
    """-> [(speaker, start, body)] with inline [m:ss] stamps at turn start and every STAMP_EVERY s."""
    words = raw.get("words") or []
    turns = []  # [speaker, start, [(text, start)]]
    for w in words:
        sp = w.get("speaker_id") or "speaker_0"
        if not turns or turns[-1][0] != sp:
            if w.get("type") == "spacing":
                if turns:
                    turns[-1][2].append((w["text"], w.get("start")))
                continue
            turns.append([sp, w.get("start") or 0, []])
        turns[-1][2].append((w["text"], w.get("start")))
    out = []
    for sp, start, toks in turns:
        parts, last = [], start
        for text, t in toks:
            if t is not None and t - last >= STAMP_EVERY:
                parts.append(f" [{stamp(t)}] ")
                last = t
            parts.append(text)
        body = re.sub(r"\s+", " ", "".join(parts)).strip()
        if body:
            out.append((sp, start, body))
    return out


def render(ep, raw, names, edits=()):
    """Markdown note: frontmatter + speaker turns. edits: [{turn, old, new}] substring fixes by turn index."""
    by_turn = {}
    for e in edits:
        by_turn.setdefault(e["turn"], []).append(e)
    out = ["---", f"title: {json.dumps(ep['title'], ensure_ascii=False)}", f"date: {ep['date']}",
           f"url: {ep['link'] or ep['url']}", "tags: [podcast, transcript]", "---", "",
           f"# {ep['title']}", ""]
    for i, (sp, start, body) in enumerate(turns_of(raw)):
        for e in by_turn.get(i, ()):
            body = body.replace(e["old"], e["new"])
        out += [f"**{names.get(sp, sp)}** [{stamp(start)}]: {body}", ""]
    return "\n".join(out)


def chunk_turns(turns, limit=CHUNK_CHARS):
    """Group (index, speaker, body) lines into chunks of <= limit chars (a single oversize turn gets its own)."""
    chunks, cur, size = [], [], 0
    for i, (sp, _, body) in enumerate(turns):
        line = f"[{i}] {sp}: {body}"
        if cur and size + len(line) > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    return chunks + [cur] if cur else chunks


def apply_edits(turns, edits):
    """Keep only well-formed edits whose `old` occurs in that turn and differs from `new` (a bad LLM edit is dropped)."""
    ok = []
    for e in edits:
        try:
            if e["old"] and e["old"] != e["new"] and e["old"] in turns[e["turn"]][2]:
                ok.append(dict(turn=e["turn"], old=e["old"], new=str(e["new"])))
        except (KeyError, IndexError, TypeError):
            pass
    return ok


PROMPT = """You are proofreading part of a diarized Hebrew podcast transcript (ASR output). English terms appear inside Hebrew speech.
Episode: {title} ({date}). Description: {desc}
{context}
Reference list of correct names/terms (one per line):
{terms}

Lines look like `[turn] speaker_id: text` ([m:ss] stamps inside the text are timestamps).
Return ONLY a JSON object, no prose, no code fence:
{{"speakers": {{"speaker_0": "First Last", ...}}, "edits": [{{"turn": 12, "old": "exact substring of that turn", "new": "replacement"}}], "review": ["short note for a human"]}}
Rules for edits: fix clear mis-transcriptions of names/terms from the reference list (e.g. a garbled name or an English term misspelled in Latin), convert numbers or dates spelled out in words to digits, and convert technical terms spelled phonetically in Hebrew letters to the standard English term in Latin letters (e.g. "קורוטינות" to "coroutines", "פרומיס" to "Promise") whenever you are confident which term is meant. Where the reference list gives alternate correct spellings of a name (e.g. a long and a short show name), accept all of them and do not "fix" one into another. Transcribe what was said: never correct or reconcile facts, figures or claims, even if they look inconsistent with the description. Do not paraphrase, summarize, fix grammar or style, remove words, or touch anything uncertain. Keep each `old` short (a few words) and unique enough in its turn; use a separate edit per occurrence.
Rules for speakers: write names in Latin script. Map speaker ids to real names ONLY when context makes it clear (people introducing themselves or each other, being addressed by name, introducing a guest). Omit ids you are unsure about and never guess. Put every unresolved speaker id, and every name or term you suspect is wrong but cannot confidently spell (quote it with its turn number), into "review" as short notes; list only real open questions, not confirmations or things you fixed. {spk_hint}

Transcript:
{text}
"""


def ask_claude(prompt):
    """Headless Claude Code on the user's subscription, no tools. Returns the parsed JSON object."""
    r = subprocess.run(["claude", "-p", "--model", POLISH_MODEL, "--tools", "", "--no-session-persistence"],
                       input=prompt, capture_output=True, text=True, timeout=1800, cwd="/tmp")
    if r.returncode:
        raise RuntimeError(f"claude exit {r.returncode}: {r.stderr[:300]}")
    out = r.stdout
    return json.loads(out[out.index("{"):out.rindex("}") + 1])  # tolerate a stray preamble line


def polish(ep, raw, keyterms, context=""):
    """-> {"speakers": {...}, "edits": [...]}. Speakers come from the first chunk (intros live there)."""
    turns = turns_of(raw)
    speakers, edits, review = {}, [], []
    for n, lines in enumerate(chunk_turns(turns)):
        prompt = PROMPT.format(title=ep["title"], date=ep["date"], desc=ep.get("desc", "")[:1500], terms="\n".join(keyterms), context=context,
                               text="\n".join(lines), spk_hint="" if n == 0 else 'Return "speakers": {} for this part.')
        for attempt in (1, 2):
            try:
                res = ask_claude(prompt)
                break
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as ex:
                if attempt == 2:
                    raise RuntimeError(f"polish chunk {n + 1} failed: {ex}") from None
        if n == 0:
            speakers = {k: v for k, v in (res.get("speakers") or {}).items() if isinstance(v, str) and v.strip()}
        edits += apply_edits(turns, res.get("edits") or [])
        review += [str(r) for r in res.get("review") or []]
    return {"speakers": speakers, "edits": edits, "review": review}


def read_terms(path):
    """One term per line; blank lines, `#` headings and leading `- ` bullets are ignored (so a vault .md list works)."""
    terms = (re.sub(r"^[-*]\s+", "", l.strip()) for l in path.read_text("utf-8").splitlines())
    return [t for t in terms if t and not t.startswith("#")]


def load_names(path, stem):
    try:
        d = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    return {**d.get("*", {}), **d.get(stem, {})}


def api_key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    env = Path(__file__).resolve().parent.parent / ".env"
    if not k and env.is_file():
        for line in env.read_text("utf-8").splitlines():
            m = re.match(r"\s*(?:export\s+)?ELEVENLABS_API_KEY\s*=\s*(.*)", line)
            if m:
                k = m.group(1).strip().strip("'\"")
    return k


def transcribe(key, url, speakers, keyterms):
    """One synchronous request; ElevenLabs fetches source_url itself. Returns the parsed JSON."""
    fields = [("model_id", MODEL), ("source_url", url), ("language_code", "heb"), ("diarize", "true"),
              ("timestamps_granularity", "word"), ("tag_audio_events", "false")]
    if speakers:
        fields.append(("num_speakers", str(speakers)))
    fields += [("keyterms", k) for k in keyterms]
    b = uuid.uuid4().hex
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode() for n, v in fields)
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request(API, body, {"xi-api-key": key, "Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:500].decode('utf-8', 'replace')}") from None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="substring of 'YYYY-MM-DD - Title'")
    ap.add_argument("--limit", type=int, help="transcribe at most N episodes (oldest first)")
    ap.add_argument("--shortest", action="store_true", help="pick shortest episodes first (by feed duration)")
    ap.add_argument("--speakers", type=int, default=2, help="max speakers (default 2; 0 = auto). Conference episodes always auto")
    ap.add_argument("--guests", default="Conference", help="regex on the title: matching episodes have guests, so speaker count is auto (default 'Conference')")
    ap.add_argument("--keyterms", type=Path, help="file with one term per line (<=5 words each); +20%% cost")
    ap.add_argument("--season", help="only episodes with this itunes:season (e.g. 1)")
    ap.add_argument("--context", type=Path, help="text file with show-specific facts for the polish prompt (show/host names, spellings)")
    ap.add_argument("--polish", action="store_true", help="LLM-clean transcripts via `claude -p` (names/terms/numbers + speaker names)")
    ap.add_argument("--rerender", action="store_true", help="rewrite notes from raw JSON, no API calls")
    ap.add_argument("--log-file")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler()] + ([logging.FileHandler(a.log_file)] if a.log_file else []))

    req = urllib.request.Request(a.feed, headers={"User-Agent": "podcast-transcriber"})
    eps = parse_feed(urllib.request.urlopen(req, timeout=60).read())
    if a.only:
        eps = [e for e in eps if a.only in e["stem"]]
    if a.season:
        eps = [e for e in eps if e["season"] == a.season]
    raw_dir, names_file = a.out / "raw", a.out / "speakers.json"
    todo = [e for e in eps if not (raw_dir / f"{e['stem']}.json").exists()]
    if a.shortest:
        todo.sort(key=lambda e: e["secs"] or 10 ** 9)
    todo = todo[:a.limit] if a.limit else todo
    log.info("feed has %d matching episodes, %d to transcribe", len(eps), len(todo))
    if a.dry_run:
        for e in todo:
            print(f"{e['stem']}  ({e['secs'] // 60} min)  {e['url']}")
        print(f"SUMMARY total={len(eps)} todo={len(todo)} done=0 failed=0")
        return 0

    raw_dir.mkdir(parents=True, exist_ok=True)
    keyterms = read_terms(a.keyterms) if a.keyterms else []
    context = a.context.read_text("utf-8").strip() if a.context else ""
    done = failed = 0
    if todo:
        key = api_key()
        if not key:
            log.error("ELEVENLABS_API_KEY not set (environment or repo-root .env)")
            return 1
        for i, e in enumerate(todo, 1):
            try:
                log.info("[%d/%d] transcribing %s", i, len(todo), e["stem"])
                cap = 0 if re.search(a.guests, e["title"]) else a.speakers
                raw = transcribe(key, e["url"], cap, keyterms)
                tmp = raw_dir / f"{e['stem']}.json.part"
                tmp.write_text(json.dumps(raw, ensure_ascii=False), "utf-8")
                tmp.rename(raw_dir / f"{e['stem']}.json")
                done += 1
            except Exception as ex:
                failed += 1
                log.error("[%d/%d] %s FAILED: %s", i, len(todo), e["stem"], str(ex).replace(key, "***"))
    pol_dir = a.out / "polished"
    for e in eps:  # (re)render notes: new ones always, existing only with --rerender or when just polished
        rp, note, pp = raw_dir / f"{e['stem']}.json", a.out / f"{e['stem']}.md", pol_dir / f"{e['stem']}.json"
        if not rp.exists():
            continue
        raw, fresh = json.loads(rp.read_text("utf-8")), False
        if a.polish and not pp.exists():
            try:
                log.info("polishing %s", e["stem"])
                res = polish(e, raw, keyterms, context)
                pol_dir.mkdir(exist_ok=True)
                pp.write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
                if res["speakers"]:  # never overwrite names the user already set for this episode
                    d = json.loads(names_file.read_text("utf-8")) if names_file.exists() else {}
                    d[e["stem"]] = {**res["speakers"], **d.get(e["stem"], {})}
                    names_file.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")
                fresh = True
                for r in res["review"]:
                    log.warning("needs review [%s]: %s", e["stem"], r)
            except Exception as ex:
                failed += 1
                log.error("polish %s FAILED: %s", e["stem"], ex)
        if a.rerender or fresh or not note.exists():
            edits = json.loads(pp.read_text("utf-8"))["edits"] if pp.exists() else []
            note.write_text(render(e, raw, load_names(names_file, e["stem"]), edits), "utf-8")
            log.info("wrote %s", note.name)
    print(f"SUMMARY total={len(eps)} todo={len(todo) - done} done={done} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
