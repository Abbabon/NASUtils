# Podcast Transcriber

Transcribes a podcast RSS feed with ElevenLabs Scribe (`scribe_v2`, Hebrew, diarized) into one
Markdown note per episode. Python stdlib only.

```sh
export ELEVENLABS_API_KEY=...        # or put it in the repo-root .env (gitignored)
python podcast_transcriber.py FEED_URL OUT_DIR --dry-run            # list what would be sent
python podcast_transcriber.py FEED_URL OUT_DIR --shortest --limit 1 # try one cheap episode
python podcast_transcriber.py FEED_URL OUT_DIR                      # everything not yet done
python test_podcast_transcriber.py                                  # self-check of the rendering
```

Options: `--only TEXT`, `--season N` (itunes:season), `--limit N`, `--shortest`, `--speakers N` (default 2,
0 = auto), `--guests REGEX` (titles matching it have guests and always use auto speakers; default `Conference`. The speaker cap is wrong for episodes with a third voice, so match your guest-episode titles), `--keyterms FILE`, `--language CODE` (default `heb`; use `auto` for a feed or episodes in another language, so Scribe detects it instead of forcing Hebrew),
`--guest-speakers N` (speaker cap for `--guests` titles; default 0 = auto, use 3 when auto merges voices), `--context FILE`, `--polish`, `--rerender`, `--log-file`.

Resuming later is just re-running the same command with another `--season` (or none): episodes whose raw
JSON exists are skipped, so only new ones are billed.

- `--keyterms FILE`: one term per line (<=5 words each; blank lines, `#` headings and `- ` bullets are
  ignored, so a Markdown list works). Boosts show/host/guest names and English or game-dev terms; about
  +20% cost. Keep the list with your own notes, not in this repo, since it is specific to a show:

  ```
  # Keyterms
  - Unity
  - Some Guest Name
  ```
- `--context FILE`: free text spliced into the polish prompt (show name and its accepted spellings,
  hosts, preferred Latin spellings of guests, what to leave alone).

## Output

- `OUT_DIR/<date> - <title>.md` - frontmatter + speaker turns, `[m:ss]` at each turn and every 2 min.
- `OUT_DIR/raw/<same>.json` - raw API response; an episode is "done" when this exists (idempotent).
- `OUT_DIR/speakers.json` - label to name, then `python podcast_transcriber.py FEED OUT_DIR --rerender`
  (no API calls):

```json
{"*": {"speaker_0": "Host One", "speaker_1": "Host Two"},
 "2025-05-04 - Some episode": {"speaker_2": "Guest Name"}}
```

Labels can swap between episodes, so check one turn per episode and use the per-episode entry if needed.

## Polish (`--polish`)

Optional LLM pass after rendering, via headless `claude -p --model sonnet` (your Claude subscription, no
API key; ~15 s per 40-min episode). Per episode it returns substring fixes (known names/terms from the
keyterms list, spelled-out numbers to digits, tech terms written in Hebrew letters converted to the English term) and a speaker-id to name mapping. Facts are never reconciled. Nothing is paraphrased or
dropped: only exact `old` to `new` edits are applied. Long episodes are split into ~60k-char chunks.

- `OUT_DIR/polished/<stem>.json` - edits, speakers and `review` notes; the raw JSON is never touched, and
  `--rerender` re-applies the edits (delete the polished file to redo it).
- Speakers are written to `speakers.json` per episode (existing entries win); unclear ids are left unmapped.
- Unresolved speakers and uncertain spellings are logged as `needs review` and stored under `review`; fill
  `speakers.json` by hand and `--rerender`.
- To get the unpolished note back, move `polished/` away and `--rerender`.

## Name review pass

Polish guesses at uncertain names and terms, and some guesses are wrong (for example a company name
"corrected" to a different company). After `--polish`, review the `needs review [<episode>]: ...`
warnings. The same items are in the `review` list of each `polished/<stem>.json`.

Give an agent with web access (for example Claude Code with web search) the review list, the
`--context` and `--keyterms` files and the episode notes. The feed's episode descriptions are the first
source for names; web search covers the rest. The agent only proposes and edits nothing. It sorts each item into:

- **Apply**: the exact current substring, its replacement and the evidence, checked to occur in the note.
- **Keep as is**: the transcript is right.
- **Unresolved**: a best guess, for the host to answer.

It also lists polish edits that look wrong. Apply the fixes after any running transcription finishes.

Example prompt:

```
Review these name/term warnings from the transcript polish step: <paste warnings>.
Read CONTEXT.md, KEYTERMS.md and the notes in OUT_DIR. Check names against the episode descriptions first,
then the web. Edit nothing. For each item answer Apply (exact current substring in the note -> replacement,
evidence, confirmed to occur in the note), Keep as is, or Unresolved (best guess, for the host). Also list
existing edits in polished/*.json whose `new` is wrong.
```

### Applying the fixes

Edit `polished/<stem>.json`, not the `.md` note, then run the same command with `--rerender`. Notes are
rebuilt from the raw JSON plus these edits, so a fix made in the `.md` is lost on the next re-render. Each
entry of the `edits` list has three fields:

```json
{"turn": 12, "old": "exact substring of that turn", "new": "replacement"}
```

- `turn` is the zero-based index of the speaker turn, counting the `**Name** [m:ss]: ...` lines in the note
  from the first. It is not printed in the note.
- Every occurrence of `old` in that turn is replaced. A name spoken in several turns needs one entry per turn.
- To undo a wrong polish edit, delete its entry or change its `new`.
- `--rerender` does not validate edits. An `old` that is not in the turn does nothing, and a missing field
  raises `KeyError`. Check each `old` against the note before rendering.
- `--polish` skips episodes whose polished file exists, so manual edits are kept.

## Behaviour

- Audio is passed as `source_url` (the podtrac redirect is stripped to `media.transistor.fm`); nothing is downloaded.
- One synchronous request per episode with a 4 h read timeout; failures are logged, the run continues,
  exit code 1. Failed requests are not auto-retried because a retry may bill again.
- Safe from launchd: no prompts, idempotent. Last stdout line is `SUMMARY ...`.
- Silence is billed. Scribe v2 API list price per third-party sources is about $0.22 per audio hour
  (+$0.05/h with keyterms), so about $16 for the ~73 h. Check against your plan's credit rate.
