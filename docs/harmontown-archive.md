# Archiving Harmontown to the NAS

I archived all of Harmontown, Dan Harmon's podcast, to my Synology NAS: 236 videos from a YouTube playlist (142 GB) and 364 audio episodes from the RSS feed. The video side took about three days of slow, unattended downloading (18 to 21 October 2026), and the audio side finished with zero failures. This post covers what broke along the way and the downloader framework that came out of it.

Sources: the [YouTube playlist](https://www.youtube.com/playlist?list=PLhnyTCcNcaceutNO3CeRSWGuMyqqsN1mO) and the show's public RSS feed.

## Estimating the space

Before downloading anything I estimated the video library at 125 to 140 GB. The final size was 142 GB for 236 `.mkv` files in `/Volumes/Assets/Podcasts/Harmontown/Video`, slightly over the top of the range. The 364 mp3s sit next to it in `/Volumes/Assets/Podcasts/Harmontown`.

## A bug in audio selection

The downloader (`youtube-downloader/Program.cs`) keeps one audio track per language and muxes them into a single mkv. yt-dlp lists formats from worst to best, and my selection took the first format per language, so every track was the lowest quality available. The fix in commit `54d3744` keeps the last format per language instead.

## Bot blocks and pacing

YouTube answered with "Sign in to confirm you're not a bot" after about 35 to 40 consecutive videos. Two options address it:

- `--delay <seconds>` sets the pause between playlist videos. The default is 60, with +/-25% random jitter.
- `--max-consecutive-failures <n>` stops the run and exits with code 2 after n consecutive bot blocks. Age-gate errors and one-off failures do not count.

## Cookies for age-restricted episodes

Some episodes are age-restricted and need a logged-in session. Three problems followed.

1. `--cookies-from-browser chrome:<profile>` failed with Arc: the decryption key did not match, so no cookies were read.
2. I switched to an exported Netscape `cookies.txt` passed with `--cookies ~/youtube-cookies.txt`. I exported it from a private window so YouTube would not rotate the session afterwards. The first export lacked the login cookies, and I had to redo it.
3. With valid cookies, requests returned only image formats. yt-dlp needs a JavaScript challenge solver for logged-in YouTube requests, so I installed deno and the `yt-dlp-ejs` package:

```sh
pip install -U "yt-dlp[default]"
```

The cookies file is a login secret. It lives outside the repo and is gitignored.

## The prolonged runner

Pacing alone would still need me to babysit a terminal for days, so I wrapped the downloader in a launchd LaunchAgent (`youtube-downloader/prolonged/prolonged.sh`). The agent runs every four hours, downloads at most 20 missing items per batch with a 100 second delay (+/-25%), and survives closing the terminal and rebooting. A job is a shell-sourced config file:

```sh
URL="https://www.youtube.com/playlist?list=PLhnyTCcNcaceutNO3CeRSWGuMyqqsN1mO"
OUTPUT="/Volumes/Assets/Podcasts/Harmontown/Video"
COOKIES="$HOME/youtube-cookies.txt"
BATCH=20
DELAY=100
INTERVAL_HOURS=4
MAX_BOT_FAILURES=3
```

The subcommands are `install`, `uninstall`, `status`, `missing`, `run`, `check` and `probe`. Each run writes a JSON status file with a `result` of `ok`, `blocked`, `error`, `waiting-cookies`, `not-mounted`, `no-access` or `complete`.

The runner keeps no list of what it has downloaded. Each run counts the `NNN. title [id].mkv` files in the output folder, downloads up to `BATCH` of the rest, and exits. A stalled or failed item stays missing and the next batch picks it up. Several downloads stalled at about 0%, which looks like silent throttling. I wrote no special handling for them, because the next batch retried them anyway.

## macOS and the network volume

The first scheduled run reported all 236 items as missing, and I killed it before it downloaded anything. macOS blocks launchd processes from reading network volumes unless the responsible binary has Full Disk Access, and an `ls` on a denied mount hangs rather than failing. The output folder looked empty, so everything looked missing.

Two changes fixed it:

- A fail-closed guard. Directory checks have 30 second timeouts, the runner writes a probe file to confirm the volume is writable, and it refuses to run if the missing count jumps by more than 5 compared with the last status. In those cases it sets `no-access` and downloads nothing.
- A small C launcher (`launcher.c`), built by `install` into `~/.local/share/nasutils/ytdl/bin/ytdl-launcher`. launchd runs the launcher, which `exec`s the job script, so bash, yt-dlp, ffmpeg and the .NET downloader share one identity. I granted Full Disk Access to that binary only, not to `/bin/bash`. `install` runs `check` under launchd and refuses to load the agent if it fails.

## Subtitles

I first requested about 12 popular subtitle languages. The extra requests caused HTTP 429 responses, and the 429s were followed by throttled video downloads. I changed the downloader to request English only (`en`, manual or auto-generated), and the 429s stopped.

## Results

The batch reports, as moved/failed counts:

| Batch | Moved | Failed |
| --- | --- | --- |
| 1 | 10 | 11 |
| 2 | 16 | 5 |
| 3 | 16 | 5 |
| 4 | 13 | 8 |
| 5 | 17 | 4 |
| 6 | 18 | 3 |
| 7 | 14 | 4 |
| 8 | 3 | 1 |

A final run on 2026-10-21 at 01:22 reported "complete: all 236 items present". There were no bot blocks once pacing and cookies were in place. These eight rows add up to 107 files. The other 129 came from interactive runs before the scheduled runner existed: the first 50, then retries and further batches of 50.

## The audio feed

The 364 mp3s come from `podcast-downloader/podcast_downloader.py`, run as a second job with `TYPE=podcast` under the same launcher and the same access guard. Files are named `YYYY-MM-DD - Title.mp3`. Downloads go to `*.part` and are renamed when complete, existing files are skipped, and failures retry with backoff. It finished with zero failures. The job runs daily and never unloads itself, so new episodes would be picked up.

## Reuse and future work

Any playlist works the same way: copy `harmontown.example.conf` to `prolonged/jobs/<name>.conf`, edit it and run `prolonged.sh install <name>`. A progress dashboard on top of the status JSON files is the next thing I would add. It does not exist yet.
