"""Self-check of the import queue with the NAS faked: python test_import_worker.py"""
import json, tempfile
from pathlib import Path
import import_worker as w

tmp = Path(tempfile.mkdtemp())
w.STATE = tmp / "state"
(tmp / "a.pdf").write_bytes(b"%PDF")
(tmp / "b.pdf").write_bytes(b"%PDF")

assert w.added_id("Added book ids: 1316\n") == 1316 and w.added_id("The following books were not added") is None

p = w.proposal('Sure:\n{"fields": {"title": "T", "authors": ["A"], "cover": "/etc/passwd"}, "confidence": 0.9, "reason": "r"}', 7)
assert p["id"] == 7 and p["source"] == "agent:import" and "cover" not in p["fields"]
assert w.proposal('{"skip": "personal document"}', 7) is None
for bad in ('{"fields": {"evil": 1}, "confidence": 0.9}', '{"fields": {"title": "T"}, "confidence": 5}'):
    try: w.proposal(bad, 7); raise AssertionError("accepted " + bad)
    except ValueError: pass

assert w.enqueue([tmp / "a.pdf", tmp / "b.pdf", tmp / "missing.pdf"]) == 2
a, b = w.jobs("queue")
assert (a / "a.pdf").read_bytes() == b"%PDF" and w.load(a)["done"] == []

# a step that fails while the NAS is away costs no attempt and keeps the job queued, resuming after the finished steps
calls = []
def flaky(job, d):
    calls.append("flaky")
    if calls.count("flaky") < 3: raise w.ci.Err("ssh exit 255")
def first(job, d): calls.append("first"); job["book"] = 5
w.STEPS = [("first", first), ("flaky", flaky)]
w.nas_down = lambda: "ssh exit 255"
assert w.run_job(a) == "retry" and w.load(a)["attempts"] == 0 and w.load(a)["done"] == ["first"]
# with the NAS up the failure counts, and the next attempt finishes
w.nas_down = lambda: None
assert w.run_job(a) == "retry" and w.load(a)["attempts"] == 1
assert w.run_job(a) == "done" and calls.count("first") == 1
assert not a.exists() and w.load(w.jobs("done")[0])["book"] == 5

# a duplicate fails at once; other errors fail after MAX_ATTEMPTS; Retry puts them back
def dup(job, d): raise w.Fatal("already in the library")
w.STEPS = [("dup", dup)]
assert w.run_job(b) == "failed" and w.jobs("queue") == []
w.retry_failed()
(b,) = w.jobs("queue")
def boom(job, d): raise SystemExit("refusing to apply: no backup")
w.STEPS = [("boom", boom)]
assert [w.run_job(b) for _ in range(w.MAX_ATTEMPTS)] == ["retry", "retry", "failed"]

w.show("ok", w.counts())
s = json.loads((w.STATE / "status.json").read_text())
assert s["headline"] == "1 imported · 1 failed" and s["lines"][0].startswith("✗ b.pdf: refusing") and len(s["notify"]) == 2
print("ok")
