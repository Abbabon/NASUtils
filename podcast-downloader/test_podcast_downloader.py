"""python3 test_podcast_downloader.py"""
from datetime import datetime, timezone
from podcast_downloader import plan, sanitize

d = datetime(2012, 7, 4, tzinfo=timezone.utc)
assert sanitize('A/B: "C"? ...') == "A B C"
p = plan([(d, "Same", "u2"), (d, "Same", "u1"), (d, "Other", "u3")])
assert [n for n, _ in p] == ["2012-07-04 - Same.mp3", "2012-07-04 - Same (2).mp3", "2012-07-04 - Other.mp3"]
assert p[0][1] == "u1"  # deterministic by url
print("ok")
