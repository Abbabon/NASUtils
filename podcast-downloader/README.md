# Podcast downloader

Downloads a podcast RSS feed's whole back catalogue, then only new episodes on later runs. Stdlib only.

```sh
python podcast-downloader/podcast_downloader.py FEED_URL DEST_DIR [--dry-run] [--pause 3] [--log-file run.log]
python podcast-downloader/test_podcast_downloader.py   # naming self-check
```

- Files are named `YYYY-MM-DD - Title.mp3` from `pubDate` and a sanitized title. Feeds often have no episode numbers, so none are invented. Same-day same-title clashes get ` (2)`, ` (3)`, ordered by enclosure URL.
- Idempotent: existing files are skipped. Downloads go to `*.part` and are renamed when complete; the size is checked against `Content-Length` when present. Failed downloads retry with backoff (5s, 30s, 2m, 5m).
- Sequential, with a pause between files. Publisher ID3 tags are kept as served. The feed's cover is saved once as `cover.jpg`.
- `--dry-run` lists the missing filenames and prints `SUMMARY total=N missing=N ...`.

## Headless (daily, via the prolonged framework)

Subscriptions are job configs in `youtube-downloader/prolonged/jobs/` (gitignored; copy `harmontown-audio.example.conf`). `TYPE=podcast` makes `prolonged.sh` run this script instead of yt-dlp, under the same Full Disk Access launcher and the same fail-closed mount/access guard.

```sh
youtube-downloader/prolonged/prolonged.sh install harmontown-audio   # checks access, loads the daily agent, runs once now
youtube-downloader/prolonged/prolonged.sh status harmontown-audio
youtube-downloader/prolonged/prolonged.sh missing harmontown-audio   # dry-run count
youtube-downloader/prolonged/prolonged.sh run harmontown-audio --force
```

Label `com.abbabon.nasutils.ytdl.<job>`; logs in `~/.local/share/nasutils/ytdl/logs/<job>/`, status in `~/.local/share/nasutils/ytdl/status/<job>.json`. Podcast jobs never rebuild an existing launcher, so the grant stays valid. The job never unloads itself.
