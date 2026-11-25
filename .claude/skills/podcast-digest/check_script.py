"""Mechanical pre-render check of an audio script (podcast-digest skill).

Usage: check_script.py DICTIONARY.md SCRIPT.txt [NAME ...]
  - every backticked item in the dictionary's "Never write" column (whole word,
    one Hebrew prefix letter allowed) is a finding, and so is any niqqud;
  - each NAME (spelled as in the feed) must occur, and any same-length script word that is
    close to one of its words but not equal is flagged as a likely misspelling.
Exit 1 on any finding. Stdlib only.
"""
import difflib, re, sys

H = r"֐-׿"


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def main(dic, script, names):
    text = open(script, encoding="utf-8").read()
    bad = 0
    for row in open(dic, encoding="utf-8"):
        if not row.startswith("|") or row.startswith("|---") or row.startswith("| Term"):
            continue
        cols = [c.strip() for c in row.strip().strip("|").split("|")]
        for w in re.findall(r"`([^`]+)`", cols[2]):
            pre = "[הובלכמש]?" if re.match(f"[{H}]", w) else ""
            for m in re.finditer(f"(?<![{H}\\w]){pre}{re.escape(w)}(?![{H}\\w])", text):
                bad += 1
                print(f"never-write {w!r} ({cols[0]}) line {line_of(text, m.start())}")
    for m in re.finditer(r"[ְ-ׇ]", text):
        bad += 1
        print(f"niqqud line {line_of(text, m.start())}")
    words = set(re.findall(f"[{H}A-Za-z0-9'\"]+", text))
    for name in names:
        if name not in text:
            bad += 1
            print(f"name {name!r} not found as spelled in the feed")
        for part in name.split():
            for w in words:
                core = w[1:] if w[0] in "הובלכמש" and w[1:] == part else w  # allow prefix
                if core != part and len(part) > 3 and len(core) == len(part) and difflib.SequenceMatcher(None, part, core).ratio() >= 0.75:
                    bad += 1
                    print(f"name variant {w!r} close to {part!r}")
    print("OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
