# calibre-import

Best-effort metadata enrichment for a live Calibre library that runs in a Docker container (`calibre-1`, linuxserver/calibre) on a Synology NAS.

The script runs on the Mac and drives the container through `ssh` + `docker exec`. Every library write goes through the content server (`calibredb --with-library http://localhost:8081/#Calibre_Library`, executed inside the container). It never writes `metadata.db` directly and never runs `calibredb` against the library path, because the Calibre GUI has the library open. Stdlib only.

## Setup

The repo-root `.env` (gitignored) must define `NAS_USER`, `NAS_IP` and `CALIBRE_PASSWORD`. `ssh $NAS_USER@$NAS_IP` must work with key auth. The password is sent on ssh stdin and read by calibredb as `--password "<f:/dev/stdin>"`, so it is never in argv on either machine. It is also scrubbed from captured output. Nothing here stores the NAS address or the password.

## Usage order

Pipeline order: **cleanup -> agent proposals -> lookup**. Apply them in that order too. Lookup searches with the title/author as they stand after cleanup and the agent proposals (`--after`), so it never works from a mechanical guess the agent already improved.

All commands accept `--ids 1,2,3` (or `--ids @file`) and `--limit N`. Run from this directory.

```sh
python calibre_import.py backup                       # snapshot of metadata.db -> /volume2/docker/calibre/backups/metadata-<ts>.db
python calibre_import.py export                       # work/export.json (+ work/baseline.json on first run), prints gap counts
python calibre_import.py cleanup --out work/proposals/cleanup.jsonl
python calibre_import.py excerpt                      # work/batches/batch_001.jsonl ... (20 books each)
#   chat agents read the batches and write proposal files (format below), e.g. work/proposals/agent.jsonl
python calibre_import.py lookup  --out work/proposals/lookup.jsonl --after work/proposals/agent.jsonl   # online, ~5-10 s per book
python calibre_import.py apply work/proposals/cleanup.jsonl              # dry run: prints what would change
python calibre_import.py apply work/proposals/cleanup.jsonl --apply      # writes through the content server
python calibre_import.py correct work/proposals/corrections_*.jsonl            # dry run: replace WRONG values (see Corrections)
python calibre_import.py correct work/proposals/corrections_*.jsonl --apply
python calibre_import.py report [--refresh]           # gaps before/after, journal totals, flagged books
```

- `backup` uses `sqlite3 -readonly ... .backup` on the NAS and checks `pragma integrity_check` plus the book count. Any `apply --apply` refuses to run without a backup younger than 24 hours.
- `cleanup` is free and deterministic: ASIN in title -> `amazon` identifier and cleaned title; valid ISBN in title -> `isbn` identifier; "kind" tag (CBZ/CBR -> `Comics`, "character sheet"/RPG words -> `RPG`) when the book has no tags.
- `lookup` calls calibre's `fetch-ebook-metadata` (Google Books + Amazon). By ISBN when present; else title+author when the author is trustworthy (not "Unknown"/junk); else title-only for Kindle-style books (title had an ASIN). A lookup not keyed on the book's own ISBN never proposes edition-specific fields (`isbn` identifier, `pubdate`, `publisher`), since it may have found another edition; description, cover, language and other identifiers are still fine. Title-only results are always below 0.8 (flagged with the `needs-review` tag, never written), and a title+author match only reaches 0.85 when the author agrees. Lookup proposals carry no tags (Google categories are noise; tags come from cleanup's kind tag and agents). Calibre's Amazon source cannot resolve a bare ASIN, so ASINs are not queried. It sees the book as cleanup would leave it. It is sequential with `--delay` (default 2 s) between calls. Results are cached in `work/lookup_cache/` (`--refresh` to redo). Covers are saved inside the container at `/tmp/calibre-import/covers/<id>.jpg` (ephemeral) and proposed as the `cover` field only when the book has none and a cover was found.
- `excerpt` writes JSONL batches. By default it covers books with a title, author, description or tag gap. Each record has the current metadata, `files`, `gaps`, `found_ids` (`asin`/`isbn` lists found in title, file names and identifiers), `same_author` (other library titles and series by the same known author, for consistent series naming), an `excerpt` (up to 6000 chars; purchaser-watermark lines such as order numbers and "Purchased by", plus CSS, are stripped) and, for CBZ/ZIP/KFX-ZIP, `archive_listing` (`[file count, first 30 names]`). Text comes from `pdftotext` (first 8 pages), the EPUB spine, or `ebook-convert` for MOBI/AZW3. Scanned PDFs and archives yield no text.

## Proposal format

One JSON object per line (JSONL). A JSON array file also works. Same format for cleanup, lookup and agents.

```json
{"id": 1256, "fields": {"title": "Atomic Habits", "authors": ["James Clear"], "tags": ["Self-help"], "publisher": "Penguin", "pubdate": "2018-10-16", "languages": ["eng"], "identifiers": {"isbn": "9780735211292"}, "comments": "<p>One-paragraph description.</p>", "series": "Series Name", "series_index": 2}, "confidence": 0.9, "source": "agent:batch_001", "reason": "title page names the author; ISBN printed on copyright page"}
```

| key | rules |
| --- | --- |
| `id` | integer Calibre book id (required) |
| `fields` | non-empty object, only these keys: `title`, `authors` (list or `"A & B"`), `series`, `series_index` (number, used only together with `series`), `tags` (list), `publisher`, `pubdate` (`YYYY-MM-DD`), `languages` (list of ISO 639 codes, e.g. `eng`), `identifiers` (object, e.g. `isbn`, `amazon`, `google`), `comments` (description; plain text is wrapped in `<p>`), `cover` (path inside the container, produced by `lookup`) |
| `confidence` | number 0 to 1. Be honest: 0.9+ only when the evidence is explicit in the text or an identifier match |
| `source` | `cleanup`, `lookup`, or `agent:<name>` |
| `reason` | short evidence, one line |

Only include fields you actually know. For junk authors (Unknown, Administrator, bare usernames like `michael`) propose the real author whenever the text identifies one. To tidy a real but ugly title (`simak vol2`, a Kindle run-on subtitle) just put the better `title` in `fields` with confidence >= 0.85: it replaces the current title only when the two clearly name the same work (the shorter title's words, case/punctuation-insensitive, are at least 80% contained in the other, at least two words, or a run-together filename title of 10+ characters such as `theincal vol6` that sits inside the other title once spaces and punctuation are removed, without extending a trailing number); anything else stays untouched. Do not invent ISBNs: they are checksum-validated and invalid ones are dropped. Invalid proposals are rejected with a message and skipped.

## Apply rules

- Fill empty fields only. Existing non-empty values are never overwritten.
- Exceptions: `authors` is replaced when it is "Unknown", empty, or file-creator junk ("Administrator", "Admin", "User", "Owner", or a single all-lowercase token like "michael"); only proposals with confidence >= 0.8 get this far. `title` is replaced only when (confidence >= 0.85 and the new title is clearly the same work, see above), or when the current title is filename-like, or when the original (baseline) title was filename-like and the only change since was cleanup's mechanical title (so a better-informed agent title wins once; the journal tells). Filename-like means (contains an ASIN or partial ASIN, a file extension, `_` or `+`, a leading product-id prefix such as `123456-`, only digits, `Microsoft Word - ...`, or looks like `a-b-c-d`) and the new title is not.
- `tags` and `identifiers` are merged (new tags / new identifier keys only). `pubdate` counts as empty when unset (year 0101); it is written as `YYYY-MM-DDT00:00:00+00:00` because a bare date is parsed in the server's local zone and the 1st of a month reads back a day late.
- Confidence below 0.8: nothing is written except the `needs-review` tag (custom columns cannot be created through the content server, so the review flag is a tag; journal field `needs_review`).
- Every change is appended to `work/journal.jsonl` (`time, book, field, old, new, source, confidence`). It is the undo record: to revert, set the field back to `old`.
- Re-running is safe: current values are read live from the library before each proposal, so filled fields are skipped, and books already flagged are not flagged again.

## Corrections

`correct <files...>` replaces a WRONG existing value (apply only fills empty ones). Dry run by default; `--apply` needs the 24h backup and journals every change (old/new, source `correction`) like `apply`. One JSON object per line:

```json
{"id": 123, "field": "authors", "current": "Faiths of Eberron", "proposed": ["Jennifer Clarke Wilkes", "Ari Marmell"], "confidence": 0.9, "evidence": "credits page"}
```

- `field`: `title`, `authors`, `publisher`, `tags`, `identifiers`, `series`, `pubdate`, `languages`. `proposed: null` clears (authors become "Unknown"; `tags`/`identifiers` remove only the tags / keys named in `current`; `pubdate` is set to calibre's undefined date; a title cannot be cleared).
- Applied only at confidence >= 0.85 and only while the live value still matches `current` (case, whitespace, punctuation, string vs list, ` & ` joins are forgiven; authors may be a subset). Otherwise it is reported `stale`. `tags` replace the named tag by the proposed ones and keep the rest; proposed ISBNs are checksum-validated; pubdate is written as explicit UTC.
- Re-running is safe: a value already equal to `proposed` counts as `noop`.
- Summary: `applied / stale / below-threshold / invalid / noop / missing`; dry run prints `id field: old -> new`.
- `lookup` proposals also carry `lookup_authors` (what the online source returned) for cross-checking against agent proposals; `apply` ignores it.

## Import new books (Menu Services module)

`calibre-import.menu-module.toml` runs `import_worker.py` under [Menu Services](https://github.com/Abbabon/menu-services). Install it once with `menu-services install calibre-import/calibre-import.menu-module.toml`.

- **Import Books…** opens a file dialog (any format Calibre reads, several files at once). `python import_worker.py add FILE...` queues without the dialog.
- Each file is copied into `~/.local/state/menu-services/calibre-import/queue/`, so the original can move and the NAS can be away. While ssh, the container or the content server does not answer, jobs wait and the menu shows `NAS unreachable · N queued`; the worker checks again every 60 s.
- Per book: upload into the container's `/tmp`, `calibredb add`, then the same pipeline as above on that one book: cleanup, excerpt, a headless `claude -p` proposal (web search and fetch only, no file tools, model `CALIBRE_AGENT_MODEL`, default `sonnet`), lookup. All writes use `apply`, so the rules, the 24h backup (taken when missing) and the journal are the same.
- A finished step is not repeated on retry. A failure while the NAS is reachable counts as an attempt; after 3 the job moves to `failed/` and a notification shows the error. **Retry Now** puts failed jobs back. A book Calibre refuses as a duplicate fails at once. Delete a job's folder to drop it.
- The menu lists the last six results. Low-confidence proposals get the `needs-review` tag, as in `apply`.

## Check

`python test_import_worker.py` runs the queue with the NAS faked (retry, attempts, duplicate, status file).


`python test_calibre_import.py` asserts the pure logic (ISBN validation, title cleaning, fill-empty-only merge, junk authors, title precedence, lookup confidence, excerpt scrubbing, confidence gate).
