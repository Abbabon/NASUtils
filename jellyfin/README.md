# Jellyfin

Containerized [Jellyfin](https://jellyfin.org/) media server for the NAS, with a
memory cap and auto-restart to prevent and recover from out-of-memory crashes.

## Files

- **docker-compose.yml** — managed service definition (memory limit, auto-restart, log rotation)
- **.env.example** — copy to `.env` and set paths, timezone, and memory ceiling

## Quick start

```sh
cp .env.example .env   # edit TZ at minimum
docker compose up -d
docker compose logs -f
```

On the NAS, `docker` lives at `/usr/local/bin/docker` (see root `CLAUDE.md`).

## Crash post-mortem (2026-06-07)

The standalone GUI container `jellyfin-jellyfin-1-1-1` (Jellyfin 10.10.7) was
crashing and not coming back. Analysis of ~95k log lines spanning
2026-06-05 → 2026-06-07 showed:

### Symptoms

- Logs **stop dead mid-operation** at `17:56:42` (during a routine library
  scan), with **no shutdown message, no `SIGTERM`, and no fatal stack trace**.
- No `OutOfMemoryException` / `StackOverflow` logged by .NET itself.
- A **recurring pattern**: the prior instance went silent at `06/05 23:58`,
  stayed dark ~17 hours, then a fresh instance booted at `06/06 16:45`.

### Root cause: OOM kill

An abrupt stop with zero shutdown logging is the signature of the process being
**SIGKILL'd from outside** — i.e. the kernel **OOM-killer**, not an application
fault. It was driven by:

- **No memory limit** on the container (confirmed in Container Manager:
  *Memory Limit: No Limit*).
- A library scan spawning **parallel `ffprobe` processes with
  `-analyzeduration 200M -probesize 1G`** (up to ~1 GB probe buffer *each*),
  plus chapter/image extraction, on a **Synology DS423 with only 2 GB RAM**.
- **Auto-restart disabled** (*Enable auto-restart: No*), so once killed it
  stayed down.

### Not the cause (but noisy in the logs)

These errors are caught and non-fatal — Jellyfin kept running for 12+ minutes
after them:

- **OpenSubtitles plugin** `JsonException` on `null` `imdb_id`
  (`Cannot get the value of a token type 'Null' as a number`) — a known plugin
  bug where the API returns `imdb_id: null` but the model expects `Int32`.
- **Plugin repo unreachable**: DNS failure for `jellyfin-repo.jesseward.com`.
- **VGMDB plugin** HTTP connection failures.
- **ffprobe** `Could not find codec parameters ... pgssub: unspecified size` —
  benign warnings on PGS subtitle streams.

### Fixes applied (in `docker-compose.yml`)

1. **`restart: unless-stopped`** — recover automatically after a kill.
2. **`mem_limit` (default 1536m)** — `ffmpeg`/`ffprobe` fail gracefully at the
   ceiling instead of the kernel killing the whole NAS. Tune via `.env`.
3. **Log rotation** — prevent logs filling the volume.

### Recommended follow-ups (outside compose)

- **Confirm OOM** after a crash:
  ```sh
  docker inspect jellyfin --format '{{.State.OOMKilled}} {{.State.ExitCode}}'
  dmesg -T | grep -iE 'oom|killed process'   # true / 137 = confirmed OOM
  ```
- **Reduce scan memory pressure**: in Jellyfin → Dashboard → Libraries, disable
  **chapter image extraction** and **trickplay/thumbnail generation** if unused.
- **Add RAM** if possible — the real fix for a media server doing scan +
  transcode on 2 GB.
- **Update or disable the OpenSubtitles plugin** to silence the `imdb_id` errors.

## Migration notes

This replaces the GUI-created standalone container with a managed Compose
project. The container uses `network_mode: host`, so **stop and remove the old
container first** to free port 8096:

```sh
docker rm -f jellyfin-jellyfin-1-1-1
docker compose up -d
```

The `/config` and `/cache` volumes are unchanged, so no data is lost. The
compose file reuses the existing local image
(`jellyfin-jellyfin-1-1-1:20260220`); switch `JELLYFIN_IMAGE` in `.env` to
`jellyfin/jellyfin:10.10.7` to move to the official upstream image.
