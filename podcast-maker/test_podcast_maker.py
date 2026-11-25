"""Self-check of the pure logic: python test_podcast_maker.py"""
from podcast_maker import cache_key, chunk_inputs, make_chunks, parse_script

voices, turns = parse_script("# c\n@voice A = a1\n@voice B = b1\n\nA: one\nB: two two\nA: three\n")
assert voices == {"A": "a1", "B": "b1"} and turns == [("A", "one"), ("B", "two two"), ("A", "three")]

chunks = make_chunks(turns, 10)  # 3 + 7 fits, +5 does not
assert [[t for _, t in c] for c in chunks] == [["one", "two two"], ["three"]]
assert sum(len(c) for c in chunks) == len(turns)  # nothing dropped, order kept

k = [cache_key(chunk_inputs(c, voices)) for c in chunks]
turns2 = turns[:2] + [("A", "three!")]
k2 = [cache_key(chunk_inputs(c, voices)) for c in make_chunks(turns2, 10)]
assert k[0] == k2[0] and k[1] != k2[1]  # editing the last chunk leaves the first cached
voices2 = dict(voices, A="other")
assert cache_key(chunk_inputs(chunks[0], voices2)) != k[0]  # voice change invalidates

for bad in ("A: x", "@voice A = a\nhello"):
    try:
        parse_script(bad)
        raise SystemExit("expected ValueError")
    except ValueError:
        pass
try:
    make_chunks([("A", "x" * 11)], 10)
    raise SystemExit("expected ValueError")
except ValueError:
    pass
print("ok")
