# Handoff: verify memory-based authors

State on 2026-11-26. The library migration and enrichment are finished (1,174 books). One check is
left: 116 author values were written from filenames or model memory, with no excerpt credit or
web source behind them. Two memory-based authors were already found wrong in a fact-check of batches
032-034, so the rest deserve the same check.

## What was already checked

| Evidence behind the applied author | Books |
|---|---|
| Credits in the book's own excerpt | 291 |
| Web search during the batch | 126 |
| Web fact-check after the fact (batches 032-034) | 59 |
| Filename or memory only (this handoff) | 116 |

## Books to verify

Calibre book ids. Titles are left out on purpose because this repo is public.

```text
69, 70, 105, 106, 107, 111, 446, 448, 476, 480, 481, 482, 484, 488, 522, 523, 530, 593, 594, 596,
597, 599, 600, 601, 602, 603, 604, 605, 618, 619, 620, 621, 622, 623, 624, 625, 626, 627, 628, 629,
630, 631, 632, 633, 634, 660, 669, 679, 680, 681, 682, 683, 686, 687, 689, 690, 691, 692, 693, 695,
697, 698, 700, 703, 704, 710, 713, 714, 715, 722, 723, 725, 731, 734, 740, 742, 746, 750, 782, 807,
814, 928, 945, 947, 957, 960, 961, 967, 976, 983, 984, 1024, 1037, 1041, 1055, 1069, 1077, 1079,
1080, 1081, 1083, 1104, 1105, 1106, 1108, 1109, 1110, 1111, 1122, 1128, 1131, 1138, 1247, 1295,
1307, 1313
```

Most are RPG sheets, maps, magazines and comics where the "author" is a publisher or studio
(Wizards of the Coast, Paizo, White Wolf, Limithron). Those need a quick confirmation that the
attribution convention is right, not a deep search.

## Setup on the other machine

1. Be on the NAS network (LAN or Tailscale) with ssh key access.
2. Root `.env` needs `NAS_USER`, `NAS_IP`, `CALIBRE_PASSWORD`. It is gitignored, so copy it by hand.
3. The Calibre content server must be running in the container (Preferences, Sharing over the net).
4. `calibre-import/work/` is gitignored and stays on the first Mac. It is optional here. Copy it over
   if you want the journal history and the old proposals. Without it, `export` rebuilds what is needed.

## Steps

```sh
cd calibre-import
python3 test_calibre_import.py                      # prints ok
python3 calibre_import.py backup                    # apply and correct need a backup under 24h old
python3 calibre_import.py export --ids <ids above, comma separated>
```

Then, per book, web-search the title and current author from `work/export.json` and write one line
per wrong author to `work/proposals/corrections_verify.jsonl`:

```json
{"id": 123, "field": "authors", "current": "Wrong Name", "proposed": ["Right Name"], "confidence": 0.9, "evidence": "publisher page"}
```

`current` must match the live value exactly, or the line is skipped as stale. Lines under 0.85
confidence are not applied. Correct authors need no line.

```sh
python3 calibre_import.py correct work/proposals/corrections_verify.jsonl           # dry run
python3 calibre_import.py correct work/proposals/corrections_verify.jsonl --apply
python3 calibre_import.py report
```

Prompt for a Claude session on that machine: "Read `calibre-import/HANDOFF-author-verification.md`
and `calibre-import/README.md`, then verify the listed authors by web search and apply corrections."

## Rules that still hold

- Write only through the content server with this tool. Never touch `metadata.db`.
- Never recreate the `calibre-1` container. Stop and start only.
- The password stays in `.env`. It never goes in argv, chat or a tracked file.
- Book 449 is a personal financial statement. Do not quote it. Remove it from the library by hand.

## Other open items (not part of this check)

- 21 books carry the `needs-review` tag: the proposal was under 0.8 confidence and was not applied.
- 19 corrections at 0.8 confidence were skipped (threshold is 0.85). They are in
  `work/proposals/corrections_*.jsonl` on the first Mac.
- About 50 anonymous items (fan sheets, maps) have no author. `report` lists the count.
- Duplicate editions were noted but nothing was merged or deleted.
- Confirm the content server is set to start automatically.
- The old source library and `Calibre Library.bak-2026-11-24` on the NAS can be deleted once you
  are satisfied.
