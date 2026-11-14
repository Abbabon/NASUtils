"""Self-check for the organizer + dashboard. Run: python test_service.py

Builds a throwaway input/archive/trash tree, then drives the real HTTP server.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

TMP = Path(tempfile.mkdtemp(prefix="organizer-test-"))
os.environ.update(INPUT_DIR=str(TMP / "in"), OUTPUT_DIR=str(TMP / "archive"), TRASH_DIR=str(TMP / "trash"),
                  CONFIG_DIR=str(TMP / "config"), PORT="0",
                  ARCHIVE_HOST_PATH="/volume9/Assets/Photos/Archive", ARCHIVE_SHARE="")

import filesOrganizer as fo  # noqa: E402
import library  # noqa: E402
import service  # noqa: E402

OLD = time.time() - 30 * 86400


def touch(p: Path, size: int, mtime: float = OLD):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(os.urandom(size))
    os.utime(p, (mtime, mtime))


class OrganizerRules(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=TMP))
        self.inp, self.out = self.root / "in", self.root / "out"
        self.out.mkdir()

    def test_moves_by_mtime_and_skips(self):
        touch(self.inp / "a.jpg", 10, mtime=time.mktime((2024, 5, 3, 12, 0, 0, 0, 0, -1)))
        touch(self.inp / ".IMG_0980.MP4", 10)                 # partial upload temp file
        touch(self.inp / "@eaDir" / "a.jpg" / "SYNOFILE_THUMB_M.jpg", 10)  # Synology metadata
        res = fo.organize_files_by_date(self.inp, self.out, fo.Rules(min_age_seconds=0))
        self.assertEqual([m.dest.relative_to(self.out).as_posix() for m in res.moved], ["2024/05/a.jpg"])
        self.assertEqual(res.skipped, 2)
        self.assertTrue((self.inp / ".IMG_0980.MP4").exists())

    def test_holds_files_that_just_changed(self):
        # ctime of a file written just now is "now", even when mtime is set back to capture date
        touch(self.inp / "uploading.mov", 10)
        res = fo.organize_files_by_date(self.inp, self.out, fo.Rules(min_age_seconds=60))
        self.assertEqual((len(res.moved), res.skipped), (0, 1))

    def test_never_overwrites(self):
        when = time.mktime((2024, 5, 3, 12, 0, 0, 0, 0, -1))
        touch(self.out / "2024" / "05" / "a.jpg", 5)
        touch(self.inp / "a.jpg", 7, mtime=when)
        fo.organize_files_by_date(self.inp, self.out, fo.Rules(min_age_seconds=0))
        self.assertEqual((self.out / "2024" / "05" / "a.jpg").stat().st_size, 5)
        self.assertEqual((self.out / "2024" / "05" / "a (1).jpg").stat().st_size, 7)

    def test_safe_join(self):
        for bad in ["../x", "/etc/passwd", "a/../../x", "", "..\\x"]:
            with self.assertRaises(library.PathError, msg=bad):
                library.safe_join(self.out, bad)
        self.assertEqual(library.safe_join(self.out, "2024/05/a.jpg"), (self.out / "2024/05/a.jpg").resolve())


class Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inp, arch = TMP / "in", TMP / "archive"
        arch.mkdir(parents=True, exist_ok=True)
        touch(arch / "2026" / "09" / "big.mp4", 300_000)
        touch(arch / "2026" / "09" / "@eaDir" / "big.mp4" / "SYNOFILE_THUMB_M.jpg", 50)
        touch(arch / "2026" / "10" / "mid.heic", 200_000)
        touch(arch / "2026" / "11" / "small.jpg", 1_000)
        touch(arch / "#recycle" / "ignored.jpg", 900_000)
        touch(inp / "fresh.jpg", 5_000, mtime=time.mktime((2026, 11, 14, 9, 0, 0, 0, 0, -1)))
        cls.app = service.App()
        cls.app.settings.update({"min_age_seconds": 0, "interval_seconds": 3600, "trash_retention_days": 0})
        service.Handler.app = cls.app
        cls.app.worker.start()
        cls.srv = service.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        for _ in range(50):  # wait for the first sort run
            if cls.app.worker.state["last_run"]:
                break
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req) as r:
            body = r.read()
            return r.status, dict(r.headers), body

    def getj(self, path):
        return json.loads(self.get(path)[2])

    def post(self, path, body, xrw=True):
        h = {"Content-Type": "application/json"}
        if xrw:
            h["X-Requested-With"] = "organizer"
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), headers=h, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_01_first_run_sorted_the_input(self):
        st = self.getj("/api/status?tz=0")
        self.assertEqual(st["worker"]["last_run"]["moved"], 1)
        self.assertTrue((TMP / "archive" / "2026" / "11" / "fresh.jpg").exists())
        self.assertEqual(st["library"]["files"], 4)  # #recycle and @eaDir excluded
        self.assertEqual(len(st["daily"]), 14)

    def test_02_largest_and_new(self):
        top = self.getj("/api/files?sort=size&limit=2")
        self.assertEqual([i["name"] for i in top["items"]], ["big.mp4", "mid.heic"])
        self.assertEqual(top["total"], 4)
        new = self.getj("/api/files?sort=arrived&days=1&limit=1")
        self.assertEqual(new["items"][0]["name"], "fresh.jpg")  # recorded arrival beats ctime
        vids = self.getj("/api/files?kind=video")
        self.assertEqual([i["name"] for i in vids["items"]], ["big.mp4"])

    def test_03_media_range_and_thumbs(self):
        status, headers, body = self.get("/media/2026/09/big.mp4", {"Range": "bytes=100-199"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 100)
        self.assertEqual(headers["Content-Range"], "bytes 100-199/300000")
        self.assertEqual(self.get("/thumb/2026/09/big.mp4")[0], 200)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/thumb/2026/10/mid.heic")
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("/media/..%2F..%2Fconfig/settings.json")
        self.assertEqual(e.exception.code, 400)

    def test_04_delete_restore_purge(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/delete", {"rel": "2026/09/big.mp4"}, xrw=False)
        self.assertEqual(e.exception.code, 403)

        row = self.post("/api/delete", {"rel": "2026/09/big.mp4"})
        self.assertFalse((TMP / "archive" / "2026" / "09" / "big.mp4").exists())
        self.assertFalse((TMP / "archive" / "2026" / "09" / "@eaDir" / "big.mp4").exists())
        self.assertTrue((TMP / "trash" / row["id"] / "big.mp4").exists())
        self.assertNotIn("big.mp4", [i["name"] for i in self.getj("/api/files")["items"]])
        self.assertEqual(self.getj("/api/status")["trash"]["count"], 1)
        self.assertEqual(self.get("/trash-media/" + row["id"])[0], 200)

        self.assertEqual(self.post("/api/trash/restore", {"id": row["id"]})["rel"], "2026/09/big.mp4")
        self.assertTrue((TMP / "archive" / "2026" / "09" / "big.mp4").exists())
        self.assertEqual(self.getj("/api/files?limit=1")["items"][0]["name"], "big.mp4")

        row = self.post("/api/delete", {"rel": "2026/11/small.jpg"})
        self.assertEqual(self.post("/api/trash/empty", {})["purged"], 1)
        self.assertFalse((TMP / "trash" / row["id"]).exists())
        self.assertEqual(self.getj("/api/trash")["items"], [])

    def test_05_settings_and_pause(self):
        self.post("/api/settings", {"paused": True, "daily_cap_gb": 2.5})
        time.sleep(0.2)
        st = self.getj("/api/status")
        self.assertEqual(st["worker"]["phase"], "paused")
        self.assertEqual(st["settings"]["daily_cap_gb"], 2.5)
        saved = json.loads((TMP / "config" / "settings.json").read_text())
        self.assertTrue(saved["paused"])
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.post("/api/settings", {"interval_seconds": 1})
        self.assertEqual(e.exception.code, 400)
        # a manual run still works while paused
        touch(TMP / "in" / "manual.jpg", 10)
        self.post("/api/run", {})
        for _ in range(50):
            if not (TMP / "in" / "manual.jpg").exists():
                break
            time.sleep(0.1)
        self.assertFalse((TMP / "in" / "manual.jpg").exists())
        self.post("/api/settings", {"paused": False})

    def test_06_index_and_health(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Photo Organizer", body)
        self.assertEqual(self.getj("/healthz"), {"ok": True})
        status, headers, body = self.get("/favicon.svg")
        self.assertEqual(headers["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", body)

    def test_07_share_location(self):
        self.assertEqual(self.getj("/api/status")["share"], {"host": None, "path": "Assets/Photos/Archive"})
        os.environ["ARCHIVE_SHARE"] = "\\\\nas\\Assets\\Photos\\Archive"
        try:
            self.assertEqual(service.archive_share(), {"host": "nas", "path": "Assets/Photos/Archive"})
        finally:
            os.environ["ARCHIVE_SHARE"] = ""


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
