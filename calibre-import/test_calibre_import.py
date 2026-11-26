"""Self-check of the pure logic: python test_calibre_import.py"""
from calibre_import import *

assert isbn_valid("0133592480") and isbn_valid("076869678X") and isbn_valid("978-0-7352-1129-2")
assert not isbn_valid("0133592481") and not isbn_valid("1234567890123")

assert filename_like("0133592480.pdf") and filename_like("Foo_Bar") and filename_like("Snow Crash B002RI9KAE")
assert filename_like("1108847-WFRoEI v01") and filename_like("Cult of the Dead Cow B07J5MW") and filename_like("cs1.indd")
assert filename_like("Microsoft Word - Errata04282005")
assert not filename_like("Man's Search for Meaning") and not filename_like("Pirate Borg")
assert not filename_like("Godbound Character Sheet PROOF 2016-0526")

assert clean_title("Atomic Habits An Easy & Proven Way B07D23CFGR") == ("Atomic Habits An Easy & Proven Way", "B07D23CFGR", None)
assert clean_title("0133592480.pdf") == ("", None, "0133592480")
assert clean_title("Cult of the Dead Cow B07J5MW")[0] == "Cult of the Dead Cow"
assert clean_title("1108847-WFRoEI v01")[0] == "WFRoEI v01"
assert clean_title("a_b+c.epub")[0] == "a b c" and not filename_like("Aram-C++") and filename_like("Questions+and+Answers")

b = {"id": 1, "title": "Snow Crash B002RI9KAE", "authors": "Unknown", "tags": [], "identifiers": {}, "formats": ["KFX-ZIP"]}
p = cleanup_proposal(b)
assert p["fields"]["identifiers"] == {"amazon": "B002RI9KAE"} and p["fields"]["title"] == "Snow Crash"
assert cleanup_proposal({**b, "title": "Real Title", "authors": "X", "identifiers": {"amazon": "B002RI9KAE"}}) is None
assert cleanup_proposal({**b, "title": "Real", "formats": ["CBZ"]})["fields"]["tags"] == ["Comics"]

# fill-empty-only
book = {"title": "Real Title", "authors": "Jane Doe", "tags": ["A"], "comments": "old", "publisher": "",
        "identifiers": {"isbn": "9780735211292"}, "series": "", "pubdate": "0101-01-01T00:00:00+00:00", "languages": []}
ch = plan(book, {"title": "Other", "authors": "Someone Else", "comments": "new", "publisher": "P", "tags": ["a", "B"],
                 "identifiers": {"isbn": "9780306406157", "amazon": "B002RI9KAE"}, "pubdate": "2018-10-16",
                 "languages": ["eng"], "series": "S", "series_index": 2})
assert "title" not in ch and "authors" not in ch and "comments" not in ch        # never overwrite
assert ch["publisher"]["new"] == "P" and ch["tags"]["new"] == ["A", "B"]         # tags merged, case-insensitive
assert ch["identifiers"]["new"] == {"isbn": "9780735211292", "amazon": "B002RI9KAE"}
assert ch["pubdate"]["new"] == "2018-10-16T00:00:00+00:00" and ch["series_index"]["new"] == 2.0
# exceptions: Unknown author, filename-like title
ch = plan({"title": "x_y.pdf", "authors": "Unknown", "tags": []}, {"title": "X Y", "authors": ["A B", "C D"]})
assert ch["title"]["new"] == "X Y" and ch["authors"]["arg"] == "A B & C D"
assert plan({"title": "x_y.pdf", "authors": "Unknown", "tags": []}, {"title": "z_w"}) == {}  # new title not clean
assert plan(book, {"tags": ["A"]}) == {}                                          # idempotent

# confidence gate
hi, lo = gate([{"confidence": 0.8}, {"confidence": 0.79}, {"confidence": 0.95}])
assert len(hi) == 2 and len(lo) == 1
assert validate_proposal({"id": 1, "fields": {"tags": ["x"]}, "confidence": 0.9, "source": "agent"}) is None
assert validate_proposal({"id": 1, "fields": {"bogus": 1}, "confidence": 0.9, "source": "a"})

# junk authors: replaceable, never trusted
assert all(unknown_author(x) for x in ("Unknown", "", "Administrator", "admin", "User", "Owner", "michael", "jeff", "brian2", ["pc"]))
assert not any(unknown_author(x) for x in ("Michael Moorcock", "J. R. R. Tolkien", "Cunningham, Elaine", "Don Bassingthwaite", "McWhorter"))
ch = plan({"title": "T", "authors": "Administrator", "tags": []}, {"authors": ["Jane Doe"]})
assert ch["authors"]["arg"] == "Jane Doe"
assert plan({"title": "T", "authors": "Jane Doe", "tags": []}, {"authors": ["X Y"]}) == {}

# lookup: no ISBN + untrustworthy author is never >= 0.8; trustworthy author still can be
found = {"title": "StarCraft", "authors": ["Michael Smith"]}
assert lookup_confidence({"title": "starcraft", "authors": "michael"}, found, "title")[0] < THRESHOLD
assert lookup_confidence({"title": "starcraft", "authors": "michael"}, found, "title+author")[0] < THRESHOLD   # junk author
assert lookup_confidence({"title": "starcraft", "authors": "Michael Smith"}, found, "title+author")[0] >= THRESHOLD
assert lookup_confidence({"title": "Starcraft", "authors": "X"}, found, "isbn")[0] >= THRESHOLD

# title precedence: cleanup's guess stays replaceable by a better-informed (agent) title, once
b = {"id": 1, "title": "Microsoft Word - Eberron_Errata04282005.doc", "authors": "K K", "tags": [], "identifiers": {}, "formats": ["PDF"]}
cl = cleanup_proposal(b)
ag = {"id": 1, "fields": {"title": "Eberron Campaign Setting Errata"}, "confidence": 0.85, "source": "agent:x"}
e = effective(b, [cl, ag])
assert cl["fields"]["title"] == "Eberron Errata04282005" and e["title"] == "Eberron Campaign Setting Errata"
assert plan(e, {"title": "Another"}) == {} and plan(e, cl["fields"]) == {}          # agent's title now final
assert effective(b, [ag, cl])["title"] == "Eberron Campaign Setting Errata"          # either order
assert effective({**b, "title": "Real"}, [ag])["title"] == "Real"                    # real titles untouched
lo = {**ag, "confidence": 0.7}
assert effective(b, [lo])["title"] == b["title"]                                     # low confidence never pre-applied

# excerpts: watermark/CSS scrub, ids, same-author names
txt = "Cover @page {padding: 0pt; margin:0pt} body { text-align: center; } <style>p{x:y}</style>\nJohn Smith (Order #12345678)\nPurchased by Jane Roe\nReal text here\n"
assert scrub(txt).split() == ["Real", "text", "here"], scrub(txt)
assert found_ids({"title": "Making Movies B004089HZC", "files": ["a/b (1)/0133592480.pdf"], "identifiers": {"isbn": "9780735211292"}}) == \
       {"asin": ["B004089HZC"], "isbn": ["0133592480", "9780735211292"]}
lib = [{"id": 1, "authors": "A B", "title": "One", "series": "S"}, {"id": 2, "authors": "A B", "title": "Two", "series": "S"},
       {"id": 3, "authors": "Unknown", "title": "Three"}]
assert same_author(lib[0], lib) == {"titles": ["Two"], "series": ["S"]} and same_author(lib[2], lib) == {}
# tidy a real-but-ugly title: conf >= 0.9 and clearly the same work
assert same_work("simak vol2", "Simak Vol. 2: Deadly Games") and not same_work("Dune", "Dune Messiah")
assert same_work("Nine Nasty Words English in the Gutter Then, Now, and Forever", "Nine Nasty Words: English in the Gutter")
assert not same_work("Pirate Borg", "Atomic Habits")
b = {"title": "simak vol2", "authors": "C Simak", "tags": []}
assert plan(b, {"title": "Simak Vol. 2: Deadly Games"}, 0.9)["title"]["new"] == "Simak Vol. 2: Deadly Games"
assert plan(b, {"title": "Simak Vol. 2: Deadly Games"}, 0.84) == {} and plan(b, {"title": "Something Else Entirely"}, 0.95) == {}
# dates: bare day written with explicit UTC, and a lookup without ISBN never writes edition fields
assert plan({"pubdate": "0101-01-01T00:00:00+00:00"}, {"pubdate": "2004-10-01"})["pubdate"]["arg"] == "2004-10-01T00:00:00+00:00"
assert edition_safe({"title": "T", "publisher": "P", "pubdate": "1996-01-01", "comments": "c",
                     "identifiers": {"isbn": "9780747527671", "google": "g"}}) == {"title": "T", "comments": "c", "identifiers": {"google": "g"}}
# tidy threshold 0.85 and run-together filename titles
assert same_work("unfabulousfive vol2", "Unfabulous Five, Vol. 2: Lucha Beach Party") and same_work("theincal vol6", "The Incal, Vol. 6")
assert not same_work("unfabulousfive vol2", "Unfabulous Five, Vol. 20: X") and not same_work("dune", "Dune Messiah Extended") and not same_work("thehobbit", "The Hobbit")
assert plan({"title": "theincal vol6", "authors": "A B", "tags": []}, {"title": "The Incal, Vol. 6"}, 0.85)["title"]["new"] == "The Incal, Vol. 6"
assert plan({"title": "theincal vol6", "authors": "A B", "tags": []}, {"title": "The Incal, Vol. 6"}, 0.84) == {}

# corrections
def cp(b, f, cur, prop): return correction_plan(b, {"field": f, "current": cur, "proposed": prop})
bk = {"title": "Old Title", "authors": "Faiths of Eberron", "tags": ["RPG", "Junk", "x"], "identifiers": {"isbn": "9780735211292", "amazon": "B002RI9KAE"},
      "series": "Wrong", "pubdate": "2004-10-01T00:00:00+00:00", "languages": ["eng"], "publisher": "P"}
r = cp(bk, "authors", "Faiths of Eberron", ["Jennifer Clarke Wilkes", "Ari Marmell"])
assert r == ("apply", "Faiths of Eberron", "Jennifer Clarke Wilkes & Ari Marmell", "Jennifer Clarke Wilkes & Ari Marmell")
assert cp(bk, "authors", ["faiths  of eberron"], None)[2] == "Unknown" and cp(bk, "authors", "Someone Else", ["X Y"]) == ("stale",)
assert cp({**bk, "authors": "A B & C D"}, "authors", "A B & C D", ["E F"])[0] == "apply" and cp({**bk, "authors": "E F"}, "authors", "A B", ["E F"]) == ("noop",)
assert cp(bk, "title", "old title", "New Title")[2] == "New Title" and cp(bk, "title", "Totally Different", "N") == ("stale",) and cp(bk, "title", "x", None)[0] == "invalid"
assert cp(bk, "tags", "junk", None)[2] == ["RPG", "x"] and cp(bk, "tags", ["Junk"], ["Games"])[2] == ["RPG", "x", "Games"]
assert cp(bk, "tags", "Nope", ["Zed"]) == ("stale",) and cp(bk, "tags", "Nope", None) == ("noop",) and cp({**bk, "tags": ["RPG"]}, "tags", "Junk", ["RPG"]) == ("noop",)
assert cp(bk, "identifiers", ["isbn"], None)[2] == {"amazon": "B002RI9KAE"} and cp(bk, "identifiers", {"isbn": "9999999999999"}, None) == ("stale",)
assert cp(bk, "identifiers", "isbn", {"isbn": "9780306406157"})[2]["isbn"] == "9780306406157" and cp(bk, "identifiers", "isbn", {"isbn": "123"})[0] == "invalid"
assert cp({**bk, "identifiers": {}}, "identifiers", "isbn", None) == ("noop",)
assert cp(bk, "series", "Wrong", None)[2:] == ("", "") and cp({**bk, "series": ""}, "series", "Wrong", None) == ("noop",)
assert cp(bk, "pubdate", "2004-10-01", "2005-03-02")[3] == "2005-03-02T00:00:00+00:00" and cp(bk, "pubdate", "1999", "2005") == ("stale",)
assert cp(bk, "pubdate", "2004", "2004-10-01") == ("noop",) and cp(bk, "pubdate", "2004", "bad")[0] == "invalid"
assert cp(bk, "languages", ["eng"], ["fra"])[3] == "fra" and cp(bk, "languages", "deu", ["fra"]) == ("stale",)
assert validate_correction({"id": 1, "field": "title", "current": "a", "proposed": "b", "confidence": 0.9}) is None
assert validate_correction({"id": 1, "field": "cover", "current": "a", "proposed": "b", "confidence": 0.9})
print("ok")
