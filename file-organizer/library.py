"""Archive index, move/run history and trash for the organizer dashboard. Stdlib only."""
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif", ".dng",
             ".tif", ".tiff", ".cr2", ".cr3", ".nef", ".arw", ".raf", ".orf", ".rw2"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".mts", ".m2ts", ".webm", ".wmv"}
# Formats a browser can show without a server-side converter.
BROWSER_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
BROWSER_VIDEO = {".mp4", ".mov", ".m4v", ".webm"}
# Synology Photos / File Station thumbnails, smallest first.
SYNO_THUMBS = ["SYNOFILE_THUMB_SM.jpg", "SYNOFILE_THUMB_M.jpg", "SYNOFILE_THUMB_B.jpg",
               "SYNOFILE_THUMB_XL.jpg"]


def kind_of(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return "other"


def skip_dir(name: str) -> bool:
    # @eaDir/@SynoResource (Synology metadata), #recycle, .hidden folders
    return name.startswith(("@", "#", "."))


class PathError(ValueError):
    pass


def safe_join(root: Path, rel: str) -> Path:
    """Resolve a client-supplied relative path, refusing anything that escapes root."""
    if not rel or "\x00" in rel:
        raise PathError("empty path")
    p = PurePosixPath(rel.replace("\\", "/"))
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise PathError("invalid path")
    full = (root / Path(*p.parts)).resolve()
    root_r = root.resolve()
    if full != root_r and root_r not in full.parents:
        raise PathError("outside root")
    return full


# --------------------------------------------------------------------------- store

class Store:
    """SQLite file under the config volume: where/when files arrived, runs, trash."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS arrivals (
                    rel TEXT PRIMARY KEY, arrived REAL NOT NULL, size INTEGER, source TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, started REAL, finished REAL,
                    moved INTEGER, bytes INTEGER, skipped INTEGER, errors INTEGER,
                    trigger TEXT, error_text TEXT);
                CREATE TABLE IF NOT EXISTS trash (
                    id TEXT PRIMARY KEY, rel TEXT NOT NULL, trash_rel TEXT NOT NULL,
                    size INTEGER, mtime REAL, arrived REAL, trashed REAL NOT NULL);
            """)

    def _exec(self, sql, args=()):
        with self._lock, self._db:
            return self._db.execute(sql, args)

    def _all(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # arrivals
    def record_arrival(self, rel: str, arrived: float, size: int, source: str = "sorter"):
        self._exec("INSERT OR REPLACE INTO arrivals(rel, arrived, size, source) VALUES (?,?,?,?)",
                   (rel, arrived, size, source))

    def forget_arrival(self, rel: str):
        self._exec("DELETE FROM arrivals WHERE rel = ?", (rel,))

    def arrivals(self) -> Dict[str, float]:
        return {r["rel"]: r["arrived"] for r in self._all("SELECT rel, arrived FROM arrivals")}

    # runs
    def record_run(self, started, finished, moved, nbytes, skipped, errors, trigger, error_text=""):
        self._exec("INSERT INTO runs(started, finished, moved, bytes, skipped, errors, trigger, error_text)"
                   " VALUES (?,?,?,?,?,?,?,?)",
                   (started, finished, moved, nbytes, skipped, errors, trigger, error_text))
        # keep the table small: last 5000 runs is ~3.5 days at a 60 s interval
        self._exec("DELETE FROM runs WHERE id <= (SELECT MAX(id) FROM runs) - 5000")

    def runs(self, limit=50, only_with_activity=False):
        where = "WHERE moved > 0 OR errors > 0" if only_with_activity else ""
        return self._all(f"SELECT * FROM runs {where} ORDER BY id DESC LIMIT ?", (limit,))

    # trash
    def add_trash(self, row: dict):
        self._exec("INSERT INTO trash(id, rel, trash_rel, size, mtime, arrived, trashed)"
                   " VALUES (:id,:rel,:trash_rel,:size,:mtime,:arrived,:trashed)", row)

    def trash_items(self):
        return self._all("SELECT * FROM trash ORDER BY trashed DESC")

    def trash_item(self, item_id: str) -> Optional[dict]:
        rows = self._all("SELECT * FROM trash WHERE id = ?", (item_id,))
        return rows[0] if rows else None

    def remove_trash(self, item_id: str):
        self._exec("DELETE FROM trash WHERE id = ?", (item_id,))


# --------------------------------------------------------------------------- library

@dataclass
class Entry:
    rel: str          # posix path relative to the archive root, e.g. "2026/11/IMG_1318.MP4"
    size: int
    mtime: float      # what the sorter dated it by (usually capture time)
    arrived: float    # when it landed in the archive
    kind: str

    def to_json(self):
        d = asdict(self)
        d["name"] = self.rel.rsplit("/", 1)[-1]
        ext = os.path.splitext(self.rel)[1].lower()
        d["previewable"] = ext in BROWSER_IMAGE or ext in BROWSER_VIDEO
        return d


class Library:
    """Cached walk of the archive. 29k files walks in a second or two on the NAS itself."""

    def __init__(self, root: Path, store: Store, ttl: float = 120):
        self.root = root
        self.store = store
        self.ttl = ttl
        self._lock = threading.Lock()
        self._entries: List[Entry] = []
        self._scanned_at = 0.0
        self._scan_seconds = 0.0

    def invalidate(self):
        self._scanned_at = 0.0

    def entries(self) -> List[Entry]:
        with self._lock:
            if time.time() - self._scanned_at > self.ttl:
                self._scan()
            return self._entries

    def _scan(self):
        t0 = time.time()
        known = self.store.arrivals()
        out: List[Entry] = []
        # scandir, not walk+stat: the directory listing already carries type (and on SMB the
        # full stat), so this avoids a round trip per file.
        stack = [("", str(self.root))]
        while stack:
            prefix, path = stack.pop()
            try:
                it = os.scandir(path)
            except OSError:
                continue
            with it:
                for de in it:
                    try:
                        if de.is_dir(follow_symlinks=False):
                            if not skip_dir(de.name):
                                stack.append((prefix + de.name + "/", de.path))
                            continue
                        if not de.is_file(follow_symlinks=False):
                            continue
                        st = de.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    rel = prefix + de.name
                    # Files the dashboard saw arrive have an exact time; older ones fall back to
                    # ctime, which on the NAS is when the file was copied in (copy, not rename,
                    # because input and output are separate mounts).
                    arrived = known.get(rel, st.st_ctime)
                    out.append(Entry(rel, st.st_size, st.st_mtime, arrived, kind_of(de.name)))
        self._entries = out
        self._scanned_at = time.time()
        self._scan_seconds = self._scanned_at - t0

    def stats(self):
        es = self.entries()
        return {"files": len(es), "bytes": sum(e.size for e in es),
                "scanned_at": self._scanned_at, "scan_seconds": round(self._scan_seconds, 2)}

    def query(self, sort: str = "size", since: Optional[float] = None, kind: str = "all",
              limit: int = 100, offset: int = 0):
        es = self.entries()
        if since:
            es = [e for e in es if e.arrived >= since]
        if kind in ("image", "video", "other"):
            es = [e for e in es if e.kind == kind]
        key = {"size": lambda e: e.size, "arrived": lambda e: e.arrived,
               "mtime": lambda e: e.mtime}.get(sort, lambda e: e.size)
        es = sorted(es, key=key, reverse=True)
        return {"total": len(es), "total_bytes": sum(e.size for e in es),
                "items": [e.to_json() for e in es[offset:offset + limit]]}

    def daily_arrivals(self, days: int, tz_offset_minutes: int):
        """Bytes/files per local day for the last `days` days. tz offset as JS getTimezoneOffset()."""
        shift = -tz_offset_minutes * 60
        now_local = time.time() + shift
        today = int(now_local // 86400)
        buckets = {today - i: [0, 0] for i in range(days)}
        for e in self.entries():
            d = int((e.arrived + shift) // 86400)
            if d in buckets:
                buckets[d][0] += 1
                buckets[d][1] += e.size
        return [{"day_start": d * 86400 - shift, "files": v[0], "bytes": v[1]}
                for d, v in sorted(buckets.items())]

    def thumbnail(self, rel: str, large: bool = False) -> Optional[Path]:
        full = safe_join(self.root, rel)
        ea = full.parent / "@eaDir" / full.name
        order = list(reversed(SYNO_THUMBS)) if large else SYNO_THUMBS[1:] + SYNO_THUMBS[:1]
        for t in order:
            p = ea / t
            if p.is_file():
                return p
        return None

    def drop(self, rel: str):
        with self._lock:
            self._entries = [e for e in self._entries if e.rel != rel]


# --------------------------------------------------------------------------- trash

class Trash:
    """Deleted files go to a folder outside the archive so they can be restored, and so a
    delete is not seen by the Backblaze sync as a move (which would upload the file again)."""

    def __init__(self, root: Path, archive_root: Path, store: Store, library: Library):
        self.root = root
        self.archive_root = archive_root
        self.store = store
        self.library = library

    def delete(self, rel: str) -> dict:
        src = safe_join(self.archive_root, rel)
        if not src.is_file():
            raise FileNotFoundError(rel)
        st = src.stat()
        arrived = self.store.arrivals().get(rel, st.st_ctime)
        item_id = uuid.uuid4().hex[:12]
        dest = self.root / item_id / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        # Synology keeps thumbnails in @eaDir/<name>/; drop them with the file.
        ea = src.parent / "@eaDir" / src.name
        if ea.is_dir():
            shutil.rmtree(ea, ignore_errors=True)
        row = {"id": item_id, "rel": rel, "trash_rel": f"{item_id}/{src.name}", "size": st.st_size,
               "mtime": st.st_mtime, "arrived": arrived, "trashed": time.time()}
        self.store.add_trash(row)
        self.store.forget_arrival(rel)
        self.library.drop(rel)
        return row

    def restore(self, item_id: str) -> str:
        from filesOrganizer import unique_dest
        row = self.store.trash_item(item_id)
        if not row:
            raise FileNotFoundError(item_id)
        src = safe_join(self.root, row["trash_rel"])
        dest = unique_dest(safe_join(self.archive_root, row["rel"]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        shutil.rmtree(src.parent, ignore_errors=True)
        new_rel = dest.relative_to(self.archive_root).as_posix()
        self.store.record_arrival(new_rel, row["arrived"], row["size"], source="restored")
        self.store.remove_trash(item_id)
        self.library.invalidate()
        return new_rel

    def purge(self, item_id: str):
        row = self.store.trash_item(item_id)
        if not row:
            raise FileNotFoundError(item_id)
        shutil.rmtree(safe_join(self.root, item_id), ignore_errors=True)
        self.store.remove_trash(item_id)

    def empty(self, older_than_days: Optional[float] = None) -> int:
        cutoff = time.time() - older_than_days * 86400 if older_than_days else None
        n = 0
        for row in self.store.trash_items():
            if cutoff is None or row["trashed"] < cutoff:
                self.purge(row["id"])
                n += 1
        return n

    def items(self):
        rows = self.store.trash_items()
        for r in rows:
            r["name"] = r["rel"].rsplit("/", 1)[-1]
            r["kind"] = kind_of(r["name"])
        return rows

    def file(self, item_id: str) -> Path:
        row = self.store.trash_item(item_id)
        if not row:
            raise FileNotFoundError(item_id)
        return safe_join(self.root, row["trash_rel"])
