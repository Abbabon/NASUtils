"""File organizer service: the sort loop plus a web dashboard, in one process.

Environment (container defaults in brackets):
  INPUT_DIR            folder the phone syncs into            [/input_directory]
  OUTPUT_DIR           dated archive (YYYY/MM)                [/output_parent_directory]
  TRASH_DIR            deleted files, outside the archive     [/trash]
  CONFIG_DIR           settings.json + organizer.db           [/config]
  PORT                 dashboard port                         [8310]
  DASHBOARD_PASSWORD   if set, HTTP basic auth (any username) [unset = no auth]
"""
import base64
import hmac
import json
import logging
import mimetypes
import os
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from filesOrganizer import Rules, organize_files_by_date
from library import Library, PathError, Store, Trash, safe_join

INPUT_DIR = Path(os.environ.get("INPUT_DIR", "/input_directory"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output_parent_directory"))
TRASH_DIR = Path(os.environ.get("TRASH_DIR", "/trash"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
PORT = int(os.environ.get("PORT", "8310"))
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
STATIC_DIR = Path(__file__).resolve().parent / "static"

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("video/quicktime", ".mov")
mimetypes.add_type("video/mp4", ".m4v")

log = logging.getLogger("organizer")


# --------------------------------------------------------------------------- logging

class RingHandler(logging.Handler):
    def __init__(self, size=500):
        super().__init__()
        self.lines = deque(maxlen=size)

    def emit(self, record):
        self.lines.append({"t": record.created, "level": record.levelname, "msg": self.format(record)})


ring = RingHandler()
ring.setFormatter(logging.Formatter("%(message)s"))


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    out = logging.StreamHandler(sys.stdout)
    out.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(out)
    root.addHandler(ring)


# --------------------------------------------------------------------------- settings

DEFAULTS = {
    "paused": False,
    "interval_seconds": 60,
    "skip_at": True,
    "skip_hidden": True,
    "min_age_seconds": 120,
    "daily_cap_gb": None,          # your Backblaze daily budget; only drives the meter
    "trash_retention_days": 30,    # 0 = keep until emptied by hand
}
LIMITS = {"interval_seconds": (10, 86400), "min_age_seconds": (0, 86400),
          "trash_retention_days": (0, 3650)}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.values = dict(DEFAULTS)
        if path.exists():
            try:
                stored = json.loads(path.read_text("utf-8"))
                self.values.update({k: v for k, v in stored.items() if k in DEFAULTS})
            except (OSError, ValueError) as e:
                log.error("Ignoring unreadable %s: %s", path, e)

    def get(self, key):
        return self.values[key]

    def update(self, changes: dict) -> dict:
        clean = {}
        for k, v in changes.items():
            if k not in DEFAULTS:
                raise ValueError(f"unknown setting {k}")
            if k in ("paused", "skip_at", "skip_hidden"):
                if not isinstance(v, bool):
                    raise ValueError(f"{k} must be true/false")
            elif k == "daily_cap_gb":
                if v in (None, "", 0):
                    v = None
                else:
                    v = float(v)
                    if v <= 0:
                        raise ValueError("daily_cap_gb must be positive")
            else:
                v = int(v)
                lo, hi = LIMITS[k]
                if not lo <= v <= hi:
                    raise ValueError(f"{k} must be between {lo} and {hi}")
            clean[k] = v
        with self._lock:
            self.values.update(clean)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.values, indent=2), "utf-8")
            os.replace(tmp, self.path)
        return dict(self.values)

    def rules(self) -> Rules:
        return Rules(skip_at=self.get("skip_at"), skip_hidden=self.get("skip_hidden"),
                     min_age_seconds=self.get("min_age_seconds"))


# --------------------------------------------------------------------------- worker

class Worker(threading.Thread):
    def __init__(self, settings: Settings, store: Store, library: Library, trash: Trash):
        super().__init__(daemon=True, name="sorter")
        self.settings, self.store, self.library, self.trash = settings, store, library, trash
        self.wake = threading.Event()
        self.run_requested = False
        self.state = {"phase": "starting", "next_run": None, "last_run": None, "started_at": time.time()}
        self._last_purge = 0.0

    def request_run(self):
        self.run_requested = True
        self.wake.set()

    def poke(self):
        self.wake.set()

    def run(self):
        while True:
            manual = self.run_requested
            self.run_requested = False
            if manual or not self.settings.get("paused"):
                self.sort_once("manual" if manual else "timer")
            self.housekeeping()
            interval = self.settings.get("interval_seconds")
            self.state["phase"] = "paused" if self.settings.get("paused") else "idle"
            self.state["next_run"] = None if self.settings.get("paused") else time.time() + interval
            self.wake.wait(interval)
            self.wake.clear()

    def sort_once(self, trigger: str):
        self.state["phase"] = "sorting"
        started = time.time()

        def on_moved(m):
            rel = m.dest.relative_to(OUTPUT_DIR).as_posix()
            self.store.record_arrival(rel, time.time(), m.size)

        try:
            res = organize_files_by_date(INPUT_DIR, OUTPUT_DIR, self.settings.rules(), on_moved)
        except Exception as e:
            log.exception("Sort run crashed")
            res = None
            err = str(e)
        finished = time.time()
        if res is None:
            summary = {"moved": 0, "bytes": 0, "skipped": 0, "errors": 1, "error_text": err}
        else:
            summary = {"moved": len(res.moved), "bytes": res.bytes_moved, "skipped": res.skipped,
                       "errors": len(res.errors), "error_text": "\n".join(res.errors[:20])}
            if res.moved:
                log.info("Sorted %d file(s), %.1f MB", len(res.moved), res.bytes_moved / 1e6)
                self.library.invalidate()
        self.store.record_run(started, finished, summary["moved"], summary["bytes"], summary["skipped"],
                              summary["errors"], trigger, summary["error_text"])
        self.state["last_run"] = dict(summary, started=started, finished=finished, trigger=trigger)

    def housekeeping(self):
        days = self.settings.get("trash_retention_days")
        if days and time.time() - self._last_purge > 3600:
            self._last_purge = time.time()
            try:
                n = self.trash.empty(older_than_days=days)
                if n:
                    log.info("Purged %d trash item(s) older than %d days", n, days)
            except Exception:
                log.exception("Trash purge failed")


# --------------------------------------------------------------------------- http

class App:
    def __init__(self):
        self.store = Store(CONFIG_DIR / "organizer.db")
        self.settings = Settings(CONFIG_DIR / "settings.json")
        self.library = Library(OUTPUT_DIR, self.store)
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        self.trash = Trash(TRASH_DIR, OUTPUT_DIR, self.store, self.library)
        self.worker = Worker(self.settings, self.store, self.library, self.trash)


class Handler(BaseHTTPRequestHandler):
    app: App = None
    server_version = "file-organizer"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the access log out of the dashboard log
        pass

    # ---- helpers
    def send_json(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error_json(self, status, msg):
        self.send_json({"error": msg}, status)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def authorized(self) -> bool:
        if not PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                _, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
                if hmac.compare_digest(pw, PASSWORD):
                    return True
            except Exception:
                pass
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="file-organizer"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def send_file(self, path: Path, download_name=None, cache=True):
        try:
            st = path.stat()
        except OSError:
            return self.error_json(HTTPStatus.NOT_FOUND, "not found")
        size = st.st_size
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        partial = False
        if rng and rng.startswith("bytes=") and "," not in rng and size > 0:
            a, _, b = rng[6:].partition("-")
            try:
                if a:
                    start = int(a)
                    end = min(int(b), size - 1) if b else size - 1
                else:  # suffix range: last N bytes
                    start = max(0, size - int(b))
                if start > end or start >= size:
                    raise ValueError
                partial = True
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "private, max-age=3600" if cache else "no-store")
        if download_name:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{_quote(download_name)}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser stopped the video / scrubbed elsewhere

    # ---- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == "/healthz":  # for the Docker healthcheck; no auth, no data
            alive = self.app.worker.is_alive()
            return self.send_json({"ok": alive}, HTTPStatus.OK if alive else HTTPStatus.SERVICE_UNAVAILABLE)
        if not self.authorized():
            return
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        path = url.path
        app = self.app
        try:
            if path in ("/", "/index.html"):
                return self.send_file(STATIC_DIR / "index.html", cache=False)
            if path == "/api/status":
                return self.send_json(self.status(int(q.get("tz", 0))))
            if path == "/api/files":
                since = None
                if q.get("days"):
                    since = time.time() - float(q["days"]) * 86400
                return self.send_json(app.library.query(
                    sort=q.get("sort", "size"), since=since, kind=q.get("kind", "all"),
                    limit=min(int(q.get("limit", 60)), 500), offset=int(q.get("offset", 0))))
            if path == "/api/trash":
                return self.send_json({"items": app.trash.items()})
            if path == "/api/activity":
                return self.send_json({"runs": app.store.runs(int(q.get("limit", 50)), only_with_activity=True),
                                       "log": list(ring.lines)[-int(q.get("lines", 200)):]})
            if path.startswith("/media/"):
                rel = unquote(path[len("/media/"):])
                return self.send_file(safe_join(OUTPUT_DIR, rel),
                                      download_name=rel.rsplit("/", 1)[-1] if q.get("download") else None)
            if path.startswith("/thumb/"):
                rel = unquote(path[len("/thumb/"):])
                t = app.library.thumbnail(rel, large=q.get("size") == "xl")
                if not t:
                    return self.error_json(HTTPStatus.NOT_FOUND, "no thumbnail")
                return self.send_file(t)
            if path.startswith("/trash-media/"):
                return self.send_file(app.trash.file(unquote(path[len("/trash-media/"):])))
            return self.error_json(HTTPStatus.NOT_FOUND, "not found")
        except PathError as e:
            return self.error_json(HTTPStatus.BAD_REQUEST, str(e))
        except FileNotFoundError:
            return self.error_json(HTTPStatus.NOT_FOUND, "not found")
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            log.exception("GET %s failed", path)
            return self.error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def do_POST(self):
        if not self.authorized():
            return
        # Cross-site forms cannot set custom headers, so this blocks a malicious page on the
        # LAN from deleting files through your browser.
        if self.headers.get("X-Requested-With") != "organizer":
            return self.error_json(HTTPStatus.FORBIDDEN, "missing X-Requested-With")
        path = urlparse(self.path).path
        app = self.app
        try:
            body = self.read_json()
            if path == "/api/run":
                app.worker.request_run()
                return self.send_json({"ok": True})
            if path == "/api/settings":
                values = app.settings.update(body)
                app.worker.poke()  # apply pause/interval right away
                log.info("Settings changed: %s", ", ".join(f"{k}={v}" for k, v in body.items()))
                return self.send_json(values)
            if path == "/api/delete":
                row = app.trash.delete(body["rel"])
                log.info("Moved to trash: %s (%.1f MB)", row["rel"], row["size"] / 1e6)
                return self.send_json(row)
            if path == "/api/trash/restore":
                rel = app.trash.restore(body["id"])
                log.info("Restored from trash: %s", rel)
                return self.send_json({"rel": rel})
            if path == "/api/trash/purge":
                app.trash.purge(body["id"])
                return self.send_json({"ok": True})
            if path == "/api/trash/empty":
                n = app.trash.empty()
                log.info("Emptied trash: %d item(s)", n)
                return self.send_json({"purged": n})
            if path == "/api/rescan":
                app.library.invalidate()
                return self.send_json(app.library.stats())
            return self.error_json(HTTPStatus.NOT_FOUND, "not found")
        except (ValueError, KeyError, PathError) as e:
            return self.error_json(HTTPStatus.BAD_REQUEST, str(e))
        except FileNotFoundError:
            return self.error_json(HTTPStatus.NOT_FOUND, "file no longer exists")
        except Exception as e:
            log.exception("POST %s failed", path)
            return self.error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))

    def status(self, tz):
        app = self.app
        trash = app.trash.items()
        return {
            "worker": app.worker.state,
            "settings": app.settings.values,
            "library": app.library.stats(),
            "daily": app.library.daily_arrivals(14, tz),
            "trash": {"count": len(trash), "bytes": sum(r["size"] or 0 for r in trash)},
            "paths": {"input": str(INPUT_DIR), "output": str(OUTPUT_DIR), "trash": str(TRASH_DIR),
                      "input_ok": INPUT_DIR.is_dir(), "output_ok": OUTPUT_DIR.is_dir()},
            "now": time.time(),
        }


def _quote(s):
    from urllib.parse import quote
    return quote(s, safe="")


def main():
    setup_logging()
    app = App()
    Handler.app = app
    app.worker.start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    log.info("Dashboard on :%d  input=%s  output=%s  trash=%s  auth=%s",
             PORT, INPUT_DIR, OUTPUT_DIR, TRASH_DIR, "on" if PASSWORD else "off")
    server.serve_forever()


if __name__ == "__main__":
    main()
