---
name: podcast-digest
description: Turn a podcast episode link into a transcript, a structured digest in the user's Obsidian vault and a short chat summary, and, only when asked, a generated audio explainer. Use when the user gives a podcast episode page URL (any host) and wants it summarized, digested or explained, or asks for an audio summary of an episode. Orchestrates podcast-transcriber/ (ElevenLabs Scribe) and podcast-maker/ (ElevenLabs Text to Dialogue); adds no new transcription or TTS code.
---

# Podcast Digest

Episode page URL in, summary out. Audio is a separate, explicit request. Both tools are billed
(ElevenLabs credits); every billed call is preceded by a dry-run and a stated estimate. All commands run
from the repo root.

## Setup

- **Vault**: read `VAULT_DIR` from the gitignored root `.env`
  (`grep '^VAULT_DIR=' .env | cut -d= -f2-`; the environment wins if set). If it is unset or not a
  directory, stop and ask the user for the vault path, tell them to add `VAULT_DIR=...` to `.env`
  (the placeholder is in `.env.example`), and do not guess a location.
- **Key**: `ELEVENLABS_API_KEY` in the environment or `.env`. Never print it.
- Layout inside the vault (`<Show>` = the show's existing folder, else its Latin name):
  - `<Show>/Transcripts/` is the transcriber `OUT_DIR` (notes, `raw/`, `polished/`, `speakers.json`),
    plus `context.md` and `keyterms.md` (the show glossary) and a `run-<episode>.log`.
  - `<Show>/<episode no. or date> - <guest or topic> - digest.md`
  - `<Show>/podcast/` for scripts, MP3s and `cache/`; `<Show>/podcast-test/` for A/B clips.
  - `Podcasts/Pronunciation dictionary.md`: ONE global file for all shows (see Audio).
- Anything show-specific stays in the vault. Never write it into this repo.

## 1. Resolve the feed and exactly one episode

1. Fetch the page; the feed is `<link rel="alternate" type="application/rss+xml" href=...>` (a podbean
   page has it; otherwise search for the show's RSS, or ask).
2. Pick the episode by the page URL, using the transcriber's own parser, so the stem is exactly what the
   tool will use:

   ```sh
   python3 - FEED_URL PAGE_URL <<'PY'
   import sys, urllib.request, urllib.parse
   sys.path.insert(0, "podcast-transcriber")
   import podcast_transcriber as p
   feed, page = sys.argv[1:3]
   eps = p.parse_feed(urllib.request.urlopen(urllib.request.Request(feed, headers={"User-Agent": "x"})).read())
   q = lambda u: urllib.parse.unquote(u).rstrip("/")
   for e in eps:
       if q(e["link"]) == q(page):
           print(e["stem"], e["secs"] // 60, "min"); print(e["desc"])
   PY
   ```

   No match (host with different link shape): match on the title and date from the page instead.
3. Dry-run, with the same `--only` you will use for the real run (the stem from step 2):

   ```sh
   python3 podcast-transcriber/podcast_transcriber.py FEED_URL "$VAULT_DIR/<Show>/Transcripts" --only "<stem>" --dry-run
   ```

   The final line must be `SUMMARY total=1 todo=1`. Anything else: **stop**, do not make a billed call.
   `total>1` means the filter is ambiguous. `todo=0` means it was already transcribed: reuse
   `raw/` and go to step 3 (no cost).

## 2. Per-show inputs (in `<Show>/Transcripts/`)

- `keyterms.md`: the show's accumulated glossary, a Markdown bullet list (one term per line, at most 5
  words; the tool ignores headings and `- `). Add names and technical terms from the episode description
  (step 1). Create it if the show is new.
- `context.md`: free text for the polish prompt: show name and accepted spellings, hosts and guest
  copied verbatim from the feed (`itunes:author`, description), "write speaker names in Latin script, keep
  English tech terms in Latin letters, do not reconcile facts".
- Speaker count: hosts plus guests. Scribe's default cap (2) merges a guest into a host. Pass
  `--guests . --guest-speakers N` (`.` matches the one selected title; N = hosts expected + guests, or
  leave 0 for auto if unsure). Language: Hebrew is the default; `--language eng` for English, `--language auto`
  if unknown.

## 3. Transcribe, polish, verify names

```sh
python3 podcast-transcriber/podcast_transcriber.py FEED_URL "$VAULT_DIR/<Show>/Transcripts" \
  --only "<stem>" --guests . --guest-speakers N --keyterms .../keyterms.md --context .../context.md \
  --polish --log-file ".../run-<episode>.log"
```

Estimate cost before running, from the dry-run minutes: about $0.22 per audio hour, +$0.05/h with
keyterms (see the transcriber README); state it. Failed requests are not retried automatically because a
retry bills again, so check the log before re-running.

Then:

1. Check one turn per speaker label in the note; fix wrong names in `speakers.json` or with
   `speaker_fixes` in `polished/<stem>.json`, then re-run the same command with `--rerender` (no API
   call).
2. Name-verification pass over the `needs review` warnings in the log: for each item, check the feed
   description and `context.md` first, then the web. Sort into Apply (exact substring in that turn, new
   spelling, evidence), Keep, or Unresolved. Apply by editing `polished/<stem>.json` `edits` (never the
   `.md`) and `--rerender`. The README's "Name review pass" has the details. Unresolved items are
   marked uncertain in the digest, never silently guessed.
3. Add the confirmed names and terms (and the spellings you settled on) to `keyterms.md`, so the next
   episode of the same show transcribes better.

## 4. Digest note

`<Show>/<episode> - <guest or topic> - digest.md`, frontmatter `title`, `date`, `tags: [podcast, digest]`,
`source: "[[Transcripts/<stem>]]"`. Written in the episode's language (Hebrew episode, Hebrew digest);
English terms stay as spoken. Every claim names its speaker and carries an `[m:ss]` stamp from the
transcript. Ignore sponsor reads (mention that they were skipped). Fixed sections, in this order:

1. Themes (3-6 bullets)
2. Terms and concepts
3. Strategies and practices
4. Opinions, predictions, recommendations
5. Worth following up (short numbered list of things the user could act on)
6. Uncertain transcription (resolved from context/web, and unresolved)

## 5. What to say in chat

5-6 lines of main themes; the "worth following up" list; the file paths (digest, transcript);
anything unresolved; what it cost (Scribe estimate from step 3). Then stop. Offer audio in one line;
do not make it.

## 6. Audio (only when the user asked)

**Format.** One dense narrator by default (one `@voice` line). Two-host dialogue only when the user is
learning a topic that is new to them.

**Voices** (Hebrew-verified library voices already on the account; model `eleven_v4`, language `he`
is fixed in the tool): narrator Nimrod `ZiofZHcEBTn5sRySe5h8`; dialogue Nimrod + Dalit
`MEuFCMd6dNJqQaLoEa8r`. Never the premade English voices for Hebrew (they sound like Americans speaking
Hebrew). Do not plan around the ElevenLabs Studio/GenFM API: the account is not whitelisted
(403 `invalid_subscription`).

**Script.** Write it from the TRANSCRIPT, not from the digest (the digest has lost the thread). About
780 characters per minute (measured), so 6-8 minutes is 4,700-6,200 characters. Written for the ear: short
sentences, one idea each, explicit signposting ("first", "the second point"), each term explained once,
open with why it matters, end with three things to try. Attribute claims to who said them. Nothing from
the digest's "uncertain" section. Format: see `podcast-maker/README.md`
(`@voice N = <id>` then `N: text` lines). Save as `<Show>/podcast/<episode>-narrator-script.txt` (or
`-dialogue-script.txt`).

**Pronunciation.** Apply `<vault>/Podcasts/Pronunciation dictionary.md`: use each "Write as", never a
"Never write", no niqqud. Before rendering run the mechanical check, passing the host/guest names exactly as
the feed spells them:

```sh
python3 .claude/skills/podcast-digest/check_script.py "$VAULT_DIR/Podcasts/Pronunciation dictionary.md" SCRIPT "<Host name>" "<Guest name>"
```

It must print `OK`. It flags every "never write" word and any near-miss of a feed name; fix the script
and re-run. Names that do not appear in the dictionary: spell them as the feed does.

**Unknown terms.** Any term the script needs that is not in the dictionary and whose spelling (Latin vs
Hebrew letters, number or acronym reading) is a guess: say so. Offer a short numbered A/B clip instead of
guessing silently: one sentence per variant, spoken as "version N" before each, rendered with the same
tool, plus a table like `podcast-test/pronunciation-test.md` (number, what it tests, text as written).
Ask the user which they prefer, then add a row to the dictionary. No general Latin-vs-Hebrew rule exists, so
do not infer from other rows.

**Render.**

```sh
python3 podcast-maker/podcast_maker.py SCRIPT OUT.mp3 --cache-dir <Show>/podcast/cache --dry-run
```

State the credits (about 0.37 per character measured; the tool's own estimate is 0.41), then render the same
command without `--dry-run`. Editing one chunk re-bills only that chunk. If the user wants to approve the
spend, ask before the real run.

**Round trip.** Transcribe the MP3 with Scribe and diff it against the script. Treat every oddity as a real
finding, not a spelling difference (it caught "AA" for "איי איי" and "scanned brain" for "second brain" that
were wrongly dismissed before). The round trip cannot detect wrong vowels or stress, so say plainly in
chat that the audio was not listened to and the user should listen to it.

Gap: `podcast_transcriber.py` only takes a feed URL (it sends `source_url`), so it cannot transcribe a
local MP3. Until a file option exists, make a one-off `POST https://api.elevenlabs.io/v1/speech-to-text`
with the same form fields as `transcribe()` in that script but the MP3 as a `file` upload (key from the
environment, never printed). If you skip the round trip, say so.
