#!/usr/bin/env python3
"""
Interactive resolver for Syncthing conflict files.

Syncthing renames the losing version of an edit-clash to
    <name>.sync-conflict-<YYYYMMDD>-<HHMMSS>-<DEVICEID>.<ext>
and keeps the winning version under the real name. This tool scans a directory
tree for those conflict copies, shows a diff (for small text files) or a
metadata comparison (for binaries / large files), and lets you decide per
conflict what to keep. Nothing destructive happens unless you explicitly ask
for it -- the default action is always "skip".

Stdlib only. Works on macOS, Linux and the Synology NAS without installing
anything.

IMPORTANT: run this on ONE device only and let the result sync out, otherwise
you may generate fresh conflicts mid-cleanup.
"""

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Matches the Syncthing conflict marker inside a filename, e.g.
#   notes.sync-conflict-20260612-103000-ABC123.md
# The marker sits between the original stem and the original extension.
CONFLICT_RE = re.compile(r"\.sync-conflict-\d{8}-\d{6}-[A-Z0-9]+")

# Files at or below this size are eligible for a text diff.
DEFAULT_MAX_DIFF_BYTES = 256 * 1024  # 256 KB

# How many diff lines to print before truncating.
MAX_DIFF_LINES = 200

# Filenames that are pure OS/app noise — almost never worth syncing, and a
# frequent source of conflicts. Used to suggest .stignore patterns.
NOISE_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ".Spotlight-V100",
    ".Trashes",
    ".localized",
}


# --------------------------------------------------------------------------- #
# Colors
# --------------------------------------------------------------------------- #

class Color:
    """ANSI color codes; all empty strings when color is disabled."""

    def __init__(self, enabled):
        self.RESET = "\033[0m" if enabled else ""
        self.BOLD = "\033[1m" if enabled else ""
        self.DIM = "\033[2m" if enabled else ""
        self.RED = "\033[31m" if enabled else ""
        self.GREEN = "\033[32m" if enabled else ""
        self.YELLOW = "\033[33m" if enabled else ""
        self.BLUE = "\033[34m" if enabled else ""
        self.CYAN = "\033[36m" if enabled else ""


def color_enabled(no_color_flag):
    """Decide whether to emit ANSI colors."""
    if no_color_flag:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


# --------------------------------------------------------------------------- #
# Conflict discovery
# --------------------------------------------------------------------------- #

class Conflict:
    """One conflict copy paired with the original it shadows."""

    def __init__(self, conflict_path, original_path):
        self.conflict = conflict_path
        self.original = original_path

    @property
    def original_exists(self):
        return self.original.exists()


def original_for(conflict_path):
    """
    Derive the original file path from a conflict copy's path by removing the
    `.sync-conflict-...-DEVICEID` marker from the filename. Preserves any real
    extension and works for extension-less files.
    """
    name = conflict_path.name
    original_name = CONFLICT_RE.sub("", name, count=1)
    return conflict_path.with_name(original_name)


def scan(root):
    """
    Recursively find conflict files under `root`. Returns a list of Conflict
    records sorted so that copies of the same original are grouped together,
    newest copy first.
    """
    root = Path(root)
    conflicts = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if CONFLICT_RE.search(path.name):
            conflicts.append(Conflict(path, original_for(path)))

    # Group by original, then within a group put the newest conflict copy first.
    conflicts.sort(
        key=lambda c: (str(c.original), -mtime(c.conflict))
    )
    return conflicts


# --------------------------------------------------------------------------- #
# File classification helpers
# --------------------------------------------------------------------------- #

def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def size_of(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def is_text(path):
    """
    Heuristic: a file is treated as text if its first 8 KB contains no NUL byte
    and decodes as UTF-8 or latin-1.
    """
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    for encoding in ("utf-8", "latin-1"):
        try:
            chunk.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def read_lines(path):
    """Read a text file's lines, tolerating common encodings."""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.readlines()
        except UnicodeDecodeError:
            continue
    # Last resort: decode with replacement so we can still show something.
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def human_size(num_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024


def human_age(timestamp):
    if not timestamp:
        return "unknown"
    delta = datetime.now() - datetime.fromtimestamp(timestamp)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def fmt_time(timestamp):
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_metadata(conflict, c):
    """Print a side-by-side-ish metadata comparison (used for binary/large)."""
    orig, conf = conflict.original, conflict.conflict
    rows = [
        ("", "original", "conflict"),
        ("size", human_size(size_of(orig)) if conflict.original_exists else "—",
         human_size(size_of(conf))),
        ("modified",
         fmt_time(mtime(orig)) if conflict.original_exists else "—",
         fmt_time(mtime(conf))),
        ("age",
         human_age(mtime(orig)) if conflict.original_exists else "—",
         human_age(mtime(conf))),
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for i, row in enumerate(rows):
        cells = [row[j].ljust(widths[j]) for j in range(3)]
        line = f"  {cells[0]}   {cells[1]}   {cells[2]}"
        if i == 0:
            print(f"{c.DIM}{line}{c.RESET}")
        else:
            print(line)


def render_diff(conflict, c, max_lines=MAX_DIFF_LINES):
    """Print a colored unified diff of original vs conflict."""
    import difflib

    orig_lines = read_lines(conflict.original) if conflict.original_exists else []
    conf_lines = read_lines(conflict.conflict)

    diff = difflib.unified_diff(
        orig_lines,
        conf_lines,
        fromfile="original",
        tofile="conflict",
        lineterm="",
    )

    printed = 0
    any_output = False
    for line in diff:
        any_output = True
        if printed >= max_lines:
            print(f"{c.DIM}  …diff truncated at {max_lines} lines — "
                  f"use [e] to open both in your editor.{c.RESET}")
            break
        if line.startswith("+") and not line.startswith("+++"):
            print(f"{c.GREEN}{line.rstrip()}{c.RESET}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"{c.RED}{line.rstrip()}{c.RESET}")
        elif line.startswith("@@"):
            print(f"{c.CYAN}{line.rstrip()}{c.RESET}")
        else:
            print(line.rstrip())
        printed += 1

    if not any_output:
        print(f"{c.DIM}  (no textual differences){c.RESET}")


def show_conflict(conflict, index, total, c, max_diff_bytes):
    """Print the header + body (diff or metadata) for one conflict."""
    print()
    print(f"{c.BOLD}{c.BLUE}[{index}/{total}] {conflict.original}{c.RESET}")
    print(f"  {c.DIM}conflict:{c.RESET} {conflict.conflict.name}")

    if not conflict.original_exists:
        print(f"  {c.YELLOW}! original is missing — the conflict copy is "
              f"orphaned.{c.RESET}")
        render_metadata(conflict, c)
        return

    identical = filecmp.cmp(conflict.original, conflict.conflict, shallow=False)
    if identical:
        print(f"  {c.GREEN}= identical content — the conflict copy is "
              f"redundant.{c.RESET}")
        return

    both_text = is_text(conflict.original) and is_text(conflict.conflict)
    small = (size_of(conflict.original) <= max_diff_bytes
             and size_of(conflict.conflict) <= max_diff_bytes)

    if both_text and small:
        render_diff(conflict, c)
    else:
        reason = "binary" if not both_text else "too large for inline diff"
        print(f"  {c.DIM}({reason} — showing metadata only){c.RESET}")
        render_metadata(conflict, c)


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #

def keep_original(conflict, dry_run, c):
    """Delete the conflict copy, keeping the existing original."""
    if dry_run:
        print(f"  {c.DIM}[dry-run] would delete {conflict.conflict}{c.RESET}")
        return True
    try:
        conflict.conflict.unlink()
        print(f"  {c.GREEN}deleted conflict copy{c.RESET}")
        return True
    except OSError as e:
        print(f"  {c.RED}error deleting conflict copy: {e}{c.RESET}")
        return False


def keep_conflict(conflict, dry_run, c):
    """Move the conflict copy over the original."""
    if dry_run:
        print(f"  {c.DIM}[dry-run] would move {conflict.conflict} -> "
              f"{conflict.original}{c.RESET}")
        return True
    try:
        shutil.move(str(conflict.conflict), str(conflict.original))
        print(f"  {c.GREEN}promoted conflict copy over original{c.RESET}")
        return True
    except OSError as e:
        print(f"  {c.RED}error promoting conflict copy: {e}{c.RESET}")
        return False


def open_in_editor(conflict, c):
    """Open both files for manual inspection, then return to re-prompt."""
    editor = os.environ.get("EDITOR")
    targets = [str(conflict.original), str(conflict.conflict)]
    try:
        if editor:
            subprocess.call([editor, *targets])
        elif sys.platform == "darwin":
            subprocess.call(["open", *targets])
        else:
            for t in targets:
                subprocess.call(["xdg-open", t])
    except OSError as e:
        print(f"  {c.RED}could not open editor: {e}{c.RESET}")


# --------------------------------------------------------------------------- #
# Syncthing .stignore
# --------------------------------------------------------------------------- #

def noise_pattern_for(name):
    """
    Return a recommended .stignore pattern for a noise filename, or None.
    Bare names like '.DS_Store' match that file anywhere in the folder; the
    AppleDouble '._*' family gets a glob.
    """
    if name in NOISE_FILES:
        return name
    if name.startswith("._"):
        return "._*"
    return None


def find_stignore_root(file_path, scan_root):
    """
    Find the directory whose .stignore governs `file_path`: the nearest existing
    .stignore walking up from the file toward `scan_root`. If none exists, fall
    back to `scan_root` (the conventional Syncthing folder root).
    """
    scan_root = Path(scan_root).resolve()
    d = Path(file_path).resolve().parent
    while True:
        if (d / ".stignore").exists():
            return d
        if d == scan_root or d == d.parent:
            return scan_root
        d = d.parent


def _pattern_covers(line, target):
    """
    Approximate whether a Syncthing .stignore `line` already matches `target`
    (a filename or pattern). Understands the common bits: comments, the `!`
    negation, `(?i)`/`(?d)` flags, and `**` globs. Not a full doublestar
    implementation — just enough to avoid suggesting redundant entries.
    """
    import fnmatch

    line = line.strip()
    if not line or line.startswith("//") or line.startswith("#"):
        return False
    if line.startswith("!"):
        return False
    while line.startswith("(?"):
        end = line.find(")")
        if end == -1:
            break
        line = line[end + 1:].strip()
    if not line:
        return False
    pat = line.replace("**", "*")          # collapse doublestar for fnmatch
    base = pat.rsplit("/", 1)[-1]          # last path segment
    return fnmatch.fnmatch(target, pat) or fnmatch.fnmatch(target, base)


def stignore_covers(root, target):
    """True if any line in <root>/.stignore already matches `target`."""
    stignore = Path(root) / ".stignore"
    if not stignore.exists():
        return False
    try:
        lines = stignore.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    return any(_pattern_covers(line, target) for line in lines)


def add_to_stignore(root, pattern, dry_run, c):
    """Append `pattern` to `<root>/.stignore` unless already covered."""
    stignore = Path(root) / ".stignore"
    if stignore_covers(root, pattern):
        print(f"  {c.DIM}already ignored (a pattern in {stignore} "
              f"covers '{pattern}'){c.RESET}")
        return True
    if dry_run:
        print(f"  {c.DIM}[dry-run] would add '{pattern}' to {stignore}{c.RESET}")
        return True
    try:
        text = stignore.read_text(encoding="utf-8") if stignore.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        text += pattern + "\n"
        stignore.write_text(text, encoding="utf-8")
        print(f"  {c.GREEN}added '{pattern}' to {stignore}{c.RESET}")
        return True
    except OSError as e:
        print(f"  {c.RED}error writing .stignore: {e}{c.RESET}")
        return False


def ignore_action(conflict, scan_root, dry_run, c):
    """Prompt for an .stignore pattern (defaulting to a smart guess) and add it."""
    suggested = (noise_pattern_for(conflict.original.name)
                 or conflict.original.name)
    root = find_stignore_root(conflict.original, scan_root)
    try:
        entered = input(
            f"  pattern to add to {root}/.stignore [{suggested}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        entered = ""
    pattern = entered or suggested
    add_to_stignore(root, pattern, dry_run, c)
    print(f"  {c.DIM}note: this stops future syncing/conflicts; the existing "
          f"conflict copy still needs resolving below.{c.RESET}")


def suggest_ignores(conflicts, scan_root, c):
    """Print a one-time tip listing noise patterns not yet ignored."""
    suggestions = {}  # pattern -> count
    for conflict in conflicts:
        pattern = noise_pattern_for(conflict.original.name)
        root = find_stignore_root(conflict.original, scan_root)
        if pattern and not stignore_covers(root, conflict.original.name):
            suggestions[pattern] = suggestions.get(pattern, 0) + 1
    if not suggestions:
        return
    print(f"{c.YELLOW}Tip:{c.RESET} some conflicts are OS/app noise not yet "
          f"ignored by Syncthing:")
    for pattern, count in sorted(suggestions.items()):
        print(f"  {c.DIM}•{c.RESET} {pattern}  ({count} conflict(s)) — "
              f"press [i] on one to add it to .stignore")


# --------------------------------------------------------------------------- #
# Interactive loop
# --------------------------------------------------------------------------- #

PROMPT = (
    "  [o] keep original (delete conflict)   "
    "[c] keep conflict (overwrite original)\n"
    "  [s] skip   [S] skip all   [i] ignore in Syncthing (.stignore)\n"
    "  [e] open both in editor   [q] quit\n"
    "  choice (Enter = skip): "
)


def resolve_interactive(conflicts, scan_root, c, dry_run, max_diff_bytes):
    stats = {"original": 0, "conflict": 0, "skipped": 0, "errors": 0}
    total = len(conflicts)
    skip_all = False

    for i, conflict in enumerate(conflicts, start=1):
        show_conflict(conflict, i, total, c, max_diff_bytes)

        if skip_all:
            stats["skipped"] += 1
            continue

        while True:
            try:
                choice = input(PROMPT).strip()
            except EOFError:
                choice = "S"  # non-interactive stdin: skip the rest safely
            except KeyboardInterrupt:
                print("\nAborted.")
                return stats

            if choice in ("", "s"):
                stats["skipped"] += 1
                break
            if choice == "S":
                stats["skipped"] += 1
                skip_all = True
                break
            if choice == "o":
                stats["original" if keep_original(conflict, dry_run, c)
                      else "errors"] += 1
                break
            if choice == "c":
                if not conflict.original_exists:
                    # No original to overwrite — just rename into place.
                    pass
                stats["conflict" if keep_conflict(conflict, dry_run, c)
                      else "errors"] += 1
                break
            if choice == "i":
                ignore_action(conflict, scan_root, dry_run, c)
                continue
            if choice == "e":
                open_in_editor(conflict, c)
                show_conflict(conflict, i, total, c, max_diff_bytes)
                continue
            if choice == "q":
                print("Quit — remaining conflicts left untouched.")
                return stats
            print(f"  {c.YELLOW}unrecognized choice "
                  f"'{choice}'{c.RESET}")

    return stats


def resolve_auto(conflicts, mode, c, dry_run):
    """Non-interactive bulk resolution."""
    stats = {"original": 0, "conflict": 0, "skipped": 0, "errors": 0}
    total = len(conflicts)

    for i, conflict in enumerate(conflicts, start=1):
        print(f"{c.DIM}[{i}/{total}] {conflict.original}{c.RESET}")
        if mode == "original":
            action = "original"
        elif mode == "conflict":
            action = "conflict"
        else:  # newer
            if not conflict.original_exists:
                action = "conflict"
            elif mtime(conflict.conflict) > mtime(conflict.original):
                action = "conflict"
            else:
                action = "original"

        if action == "original":
            stats["original" if keep_original(conflict, dry_run, c)
                  else "errors"] += 1
        else:
            stats["conflict" if keep_conflict(conflict, dry_run, c)
                  else "errors"] += 1

    return stats


# --------------------------------------------------------------------------- #
# Favorites
# --------------------------------------------------------------------------- #

def default_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "sync-conflict-resolver" / "favorites.json"


def load_favorites(config_path):
    """Return a list of {name, path} dicts; empty if the file is absent."""
    path = Path(config_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: could not read favorites at {path}: {e}",
              file=sys.stderr)
        return []
    favorites = data.get("favorites", [])
    return [f for f in favorites if f.get("path")]


def pick_favorite(favorites, c):
    """Show a numbered menu and return the chosen path, or None."""
    print(f"{c.BOLD}Favorite locations:{c.RESET}")
    for i, fav in enumerate(favorites, start=1):
        name = fav.get("name", fav["path"])
        print(f"  {c.CYAN}{i}{c.RESET}) {name}  {c.DIM}{fav['path']}{c.RESET}")
    try:
        choice = input("Pick a number (Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not choice:
        return None
    try:
        idx = int(choice)
        if 1 <= idx <= len(favorites):
            return favorites[idx - 1]["path"]
    except ValueError:
        pass
    print("Invalid selection.")
    return None


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        description="Interactively resolve Syncthing conflict files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Run this on ONE device only and let the result sync out, to avoid "
            "generating fresh conflicts mid-cleanup."
        ),
    )
    p.add_argument("path", nargs="?",
                   help="Directory to scan recursively. If omitted, pick from "
                        "favorites.")
    p.add_argument("--config", default=None,
                   help="Path to favorites JSON "
                        "(default: ~/.config/sync-conflict-resolver/favorites.json).")
    p.add_argument("--list-favorites", action="store_true",
                   help="List configured favorites and exit.")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would happen without changing anything.")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI colors.")
    p.add_argument("--max-diff-bytes", type=int, default=DEFAULT_MAX_DIFF_BYTES,
                   help=f"Max file size for inline text diffs "
                        f"(default: {DEFAULT_MAX_DIFF_BYTES}).")
    p.add_argument("--auto", choices=["original", "conflict", "newer"],
                   help="Non-interactive bulk resolution: keep original "
                        "(delete all conflict copies), keep conflict (promote "
                        "all), or keep newer (by mtime).")
    return p


def print_summary(stats, dry_run, c):
    print()
    print(f"{c.BOLD}Summary{c.RESET}{' (dry-run)' if dry_run else ''}:")
    print(f"  kept original  : {stats['original']}")
    print(f"  kept conflict  : {stats['conflict']}")
    print(f"  skipped        : {stats['skipped']}")
    if stats["errors"]:
        print(f"  {c.RED}errors         : {stats['errors']}{c.RESET}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    c = Color(color_enabled(args.no_color))
    config_path = args.config or default_config_path()

    if args.list_favorites:
        favorites = load_favorites(config_path)
        if not favorites:
            print(f"No favorites configured. Create {config_path} with:")
            print('  {"favorites": [{"name": "Notes", "path": "/path/to/dir"}]}')
            return 0
        for fav in favorites:
            print(f"{fav.get('name', fav['path'])}: {fav['path']}")
        return 0

    target = args.path
    if not target:
        favorites = load_favorites(config_path)
        if not favorites:
            print("No path given and no favorites configured.\n")
            print(f"Either pass a directory, or create {config_path}:")
            print('  {"favorites": [{"name": "Notes", "path": "/path/to/dir"}]}')
            return 1
        target = pick_favorite(favorites, c)
        if not target:
            print("Nothing selected.")
            return 1

    root = Path(target).expanduser()
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        return 1

    print(f"Scanning {c.BOLD}{root}{c.RESET} for Syncthing conflict files…")
    conflicts = scan(root)
    if not conflicts:
        print(f"{c.GREEN}No conflict files found. Nothing to do.{c.RESET}")
        return 0

    print(f"Found {c.BOLD}{len(conflicts)}{c.RESET} conflict file(s).")
    if args.dry_run:
        print(f"{c.YELLOW}Dry-run: no files will be changed.{c.RESET}")

    suggest_ignores(conflicts, root, c)

    if args.auto:
        stats = resolve_auto(conflicts, args.auto, c, args.dry_run)
    else:
        stats = resolve_interactive(conflicts, root, c, args.dry_run,
                                    args.max_diff_bytes)

    print_summary(stats, args.dry_run, c)
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
