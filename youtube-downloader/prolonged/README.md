# Prolonged playlist download

Downloads a big YouTube playlist in small batches over hours or days, headless, via a macOS LaunchAgent. Built for YouTube's "Sign in to confirm you're not a bot" block, which hits after ~35-40 consecutive videos.

## Usage

```sh
cp prolonged/harmontown.example.conf prolonged/jobs/<job>.conf   # edit; jobs/ is gitignored
prolonged/prolonged.sh install <job>     # builds Release + the launcher into ~/.local/share/nasutils/ytdl/bin, runs `check`, loads the agent only if it passes
prolonged/prolonged.sh status <job>      # launchd state, status JSON, newest log
prolonged/prolonged.sh check <job>       # read-only access check, run under launchd via the launcher (see below)
prolonged/prolonged.sh missing <job>     # playlist length + missing indices (read-only)
prolonged/prolonged.sh run <job> --force # one batch now, ignoring the min-gap check
prolonged/prolonged.sh uninstall <job>
```

Re-run `install` after changing the config or `Program.cs`. Label: `com.abbabon.nasutils.ytdl.<job>`.

## One-time: Full Disk Access (NAS volume)

macOS blocks background (launchd) processes from network volumes such as `/Volumes/Assets` unless the responsible binary has Full Disk Access. `install` builds a tiny launcher that launchd runs and that `exec`s the job script, so bash, yt-dlp, ffmpeg and the .NET downloader all run under that one identity. Grant it to the launcher only, not `/bin/bash`:

System Settings -> Privacy & Security -> Full Disk Access -> `+` -> press Cmd+Shift+G and enter `~/.local/share/nasutils/ytdl/bin/ytdl-launcher` (full path: `/Users/<you>/.local/share/nasutils/ytdl/bin/ytdl-launcher`), then enable it.

Then verify under launchd, without downloading anything:

```sh
prolonged/prolonged.sh check <job>   # prints "access ok ... RESULT ok", or "no-access ... RESULT failed"
prolonged/prolonged.sh install <job> # refuses to schedule if the check fails
```

Re-running `install` only replaces the launcher if it changed, so the grant survives. If access is missing, the output dir looks unlistable or unwritable (a denied SMB access can hang, so it times out after 30s). The run fails closed: status `no-access`, nothing downloads. The same guard aborts if the missing count jumps by more than 5 versus the last status (delete the status file if that is legitimate).

## How it works

- Each run downloads up to `BATCH` missing items, then exits. A `mkdir` lock prevents overlap.
- Progress is read from the output folder: files named `NNN. title [id].mkv` in `OUTPUT/` or `OUTPUT/<playlistId>/`. New files are flattened into `OUTPUT/` after each run (name clashes are left in place).
- `--max-consecutive-failures` (Program.cs) stops the run after `MAX_BOT_FAILURES` consecutive "not a bot" errors (exit code 2, result `blocked`). Age-gate and one-off failures are logged but do not count.
- No cookies file: logs "waiting for cookies" and exits. NAS not mounted: logs and exits. Nothing missing: logs "complete" and unloads the agent.
- Logs: `~/.local/share/nasutils/ytdl/logs/<job>/run-*.log` (last 60) plus `launchd.log`. Status: `~/.local/share/nasutils/ytdl/status/<job>.json` (`result` is one of `ok`, `blocked`, `error`, `waiting-cookies`, `not-mounted`, `no-access`, `complete`).
- Config keys: `URL OUTPUT COOKIES BATCH DELAY INTERVAL_HOURS MAX_BOT_FAILURES` (defaults 20, 100s, 4h, 3).

## Sleep and reboots

`StartInterval` timers do not fire while the Mac sleeps; launchd runs one catch-up run on wake (missed intervals are not stacked). `RunAtLoad` also runs at login, so a run is skipped if the last one was under `INTERVAL_HOURS` ago (minus 10 minutes). While the lid is closed nothing downloads; an unattended overnight run needs the Mac awake (power adapter, display sleep only).

## Secrets

The cookies file (`cookies.txt`) is a login secret. Keep it outside the repo, never commit it, and re-export it if a run reports `blocked`.
