# Podcast maker

Renders a script to one MP3 with ElevenLabs Text to Dialogue (`eleven_v4`, Hebrew, fixed seed). Stdlib plus `ffmpeg`.
It does not write the script; bring your own. Key: `ELEVENLABS_API_KEY` from the environment or the root `.env`.

## Script format

One turn per line. `#` comments and blank lines are ignored.

```
@voice A = <voice_id>
@voice B = <voice_id>
A: first turn
B: second turn
```

A one-speaker script works the same way: one `@voice` line and every turn under it.

## Usage

```sh
python podcast-maker/podcast_maker.py script.txt episode.mp3 --dry-run   # chunks, chars, estimated credits
python podcast-maker/podcast_maker.py script.txt episode.mp3 --cache-dir ./cache
python podcast-maker/test_podcast_maker.py                               # self-check
```

## Behaviour

- Turns are packed into chunks of at most `--max-chars` (default 1900; the API limit is 2000) at turn boundaries.
- Each chunk is cached as `<hash>.mp3` in the cache dir (default `<out>.cache`). The hash covers model, language,
  seed, voice ids and text, so editing one part and re-running re-renders (and re-bills) only the changed chunks.
- Failed chunks are reported and the run exits non-zero; re-run to retry only those.
- Chunks are joined with ffmpeg (re-encoded to 128 kbps MP3).
- The credit estimate uses about 0.41 credits per character, which is a guide only (observed runs came in lower).
- Chunks are rendered independently, with no `previous_request_ids`, so tone can shift slightly at chunk seams.
