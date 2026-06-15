# Sync Conflict Resolver

Interactive command-line tool for cleaning up **Syncthing conflict files**.

When two devices edit the same file between syncs, Syncthing keeps the
newest-mtime version under the real name and renames the loser to:

```
<name>.sync-conflict-<YYYYMMDD>-<HHMMSS>-<DEVICEID>.<ext>
```

Resolving these by hand (`find` → `diff` → `mv`/`rm`) is tedious, and the blunt
"original always wins" approach (delete every conflict copy) can throw away real
edits. This tool keeps a human in the loop: it scans a tree, shows you the
difference, and lets you decide per conflict.

## Features

- **Recursive scan** for `*.sync-conflict-*` files (handles nested dirs and
  extension-less files).
- **Smart presentation** per conflict:
  - small text files → colored unified diff,
  - identical copies → flagged as redundant,
  - binary / large files → size + mtime + age comparison,
  - orphaned copies (original missing) → highlighted.
- **You decide**: keep original, keep conflict, skip, skip-all, open both in
  your editor, or quit. **Bare Enter = skip** — nothing destructive happens by
  accident.
- **Favorites**: save frequently-scanned paths in a JSON config and pick from a
  menu.
- **Bulk mode** (`--auto`) for when you really do want "original always wins" (or
  conflict, or newest) without prompts.
- **`--dry-run`** to preview every action.
- Stdlib only — no `pip install`, runs on macOS, Linux and the Synology NAS.

## Usage

```sh
# Scan a directory interactively
python sync_conflict_resolver.py /path/to/folder

# Preview without changing anything
python sync_conflict_resolver.py /path/to/folder --dry-run

# Pick from saved favorites (no path argument)
python sync_conflict_resolver.py

# List configured favorites
python sync_conflict_resolver.py --list-favorites

# Bulk: delete all conflict copies (original always wins)
python sync_conflict_resolver.py /path/to/folder --auto original

# Bulk: keep whichever copy is newest by mtime
python sync_conflict_resolver.py /path/to/folder --auto newer
```

### Per-conflict keys

| Key | Action                                            |
|-----|---------------------------------------------------|
| `o` | keep **o**riginal (delete the conflict copy)      |
| `c` | keep **c**onflict (move it over the original)     |
| `s` | skip this one                                     |
| `S` | skip all remaining                                |
| `e` | open both files in `$EDITOR`, then re-prompt      |
| `q` | quit, leaving the rest untouched                  |
| ⏎   | (Enter) skip — the safe default                   |

## Favorites config

Default location: `~/.config/sync-conflict-resolver/favorites.json`
(override with `--config`). See `favorites.example.json`:

```json
{
  "favorites": [
    { "name": "Obsidian Vault", "path": "/volume1/homes/amit/Obsidian" },
    { "name": "KOReader Library", "path": "/volume1/Assets/Books" }
  ]
}
```

## Options

| Flag                  | Description                                                        |
|-----------------------|-------------------------------------------------------------------|
| `--config FILE`       | Path to favorites JSON.                                            |
| `--list-favorites`    | Print favorites and exit.                                          |
| `--dry-run`           | Show actions without changing files.                              |
| `--no-color`          | Disable ANSI colors (also honors `NO_COLOR`; auto-off when piped). |
| `--max-diff-bytes N`  | Max file size for inline text diffs (default 262144 = 256 KB).     |
| `--auto {original,conflict,newer}` | Non-interactive bulk resolution.                     |

## ⚠️ Important

Run this on **one device only** and let the result sync out before touching the
same files elsewhere. Resolving conflicts on two devices at once just generates
fresh conflicts.

For data that is inherently one-directional (e.g. a KOReader library where one
machine is the source of truth), consider setting that folder to **Send Only** /
**Receive Only** in Syncthing to stop conflicts at the source.

## Stopping conflicts at the source (Syncthing settings)

This tool cleans up conflicts after the fact. To stop creating them, tune the
Syncthing folder itself:

- **Send Only / Receive Only** — for one-directional data (a library, a backup,
  an export). Set the source device's folder to **Send Only** and every consumer
  to **Receive Only**. The receivers never write back, so they can never lose an
  edit race. Kills most conflicts dead.
- **Conflict Resolution** (folder → *Advanced* → *Conflict Resolution*):
  - default keeps up to 10 conflict files,
  - set it to a small number to cap clutter, or
  - set it to **0** so the newest-mtime file silently wins with no copy kept —
    only do this where losing an edit is acceptable.
- **Ignore the sidecars that actually clash.** The usual culprits are app
  metadata written on two devices between syncs — e.g. KOReader's `.sdr`
  folders / reading-position files. Add patterns to the folder's `.stignore`
  if you don't need them synced:

  ```
  // KOReader sidecar metadata
  *.sdr
  *.sdr/**
  ```

- **Behavioral fix:** close the file / let one device finish syncing before
  opening or editing the same file on another device. Most conflicts come from
  two devices touching one file inside the same sync window.

### Typical workflow

1. Pick one device as the cleanup machine and make sure it is fully synced.
2. Run this resolver there and settle each conflict.
3. Let the result sync out to the other devices before touching those files
   again.
4. If a folder keeps generating conflicts, revisit the Send/Receive Only and
   `.stignore` settings above so you stop fighting the same fire.
