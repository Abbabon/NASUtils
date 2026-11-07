"""python3 test_podcast_transcriber.py"""
from pathlib import Path
from podcast_transcriber import apply_edits, read_terms, chunk_turns, direct_url, render, stamp, turns_of

assert direct_url("https://dts.podtrac.com/redirect.mp3/media.transistor.fm/a/b.mp3") == "https://media.transistor.fm/a/b.mp3"
assert stamp(65) == "1:05" and stamp(3725) == "1:02:05"
w = lambda t, s, sp="speaker_0", ty="word": dict(text=t, start=s, end=s + 1, speaker_id=sp, type=ty)
raw = {"words": [w("שלום", 0), w(" ", 1, ty="spacing"), w("Unity", 2), w(" ", 3, ty="spacing"),
                 w("היי", 4, "speaker_1"), w(" ", 5, "speaker_1", "spacing"), w("עוד", 130, "speaker_1")]}
ep = dict(title="T", date="2026-01-01", link="http://x", url="u")
md = render(ep, raw, {"speaker_0": "Host"})
assert "**Host** [0:00]: שלום Unity" in md, md
assert "**speaker_1** [0:04]: היי [2:10] עוד" in md, md
assert md.startswith("---\ntitle:") and "tags: [podcast, transcript]" in md
md = render(ep, raw, {}, [dict(turn=0, old="Unity", new="Unreal"), dict(turn=1, old="עוד", new="x")])
assert "שלום Unreal" in md and "עוד" not in md.split("speaker_1")[0] and "[2:10] x" in md, md
turns = turns_of(raw)
assert [t[0] for t in turns] == ["speaker_0", "speaker_1"]
good = apply_edits(turns, [dict(turn=0, old="Unity", new="U"), dict(turn=0, old="nope", new="x"), dict(turn=9, old="a", new="b"), dict(turn=0, old="Unity", new="Unity"), {}])
assert good == [dict(turn=0, old="Unity", new="U")], good
assert [len(c) for c in chunk_turns(turns, 20)] == [1, 1] and len(chunk_turns(turns)) == 1 and chunk_turns([]) == []
import tempfile
f = Path(tempfile.mkdtemp()) / "k.md"
f.write_text("# Terms\n\n- Unity\n* קורוטינות\nplain\n", "utf-8")
assert read_terms(f) == ["Unity", "קורוטינות", "plain"]
print("ok")
