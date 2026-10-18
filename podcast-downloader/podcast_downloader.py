#!/usr/bin/env python3
"""Download a podcast RSS feed's whole back catalogue (and later only new episodes).

Usage: podcast_downloader.py FEED_URL DEST_DIR [--dry-run] [--pause SECS] [--log-file PATH]
Files: "YYYY-MM-DD - Title.mp3" (pubDate + sanitized title). Existing files are skipped, so re-running is cheap.
Last stdout line: "SUMMARY total=N missing=N downloaded=N failed=N". Exit 1 if any download failed.
"""
import argparse
import logging
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
UA = "Mozilla/5.0 (podcast-downloader; personal NAS archive)"
BACKOFF = (5, 30, 120, 300)  # seconds before retries 2..5
log = logging.getLogger("podcast")


def sanitize(title, limit=150):
    t = re.sub(r'[\x00-\x1f/\\:*?"<>|]', " ", title)
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:limit].strip(" .") or "Untitled"


def plan(items):
    """items: [(datetime, title, url)] -> [(filename, url)], deterministic; same-day same-title gets " (2)", ..."""
    out, seen = [], {}
    for dt, title, url in sorted(items, key=lambda i: (i[0], i[2])):
        base = f"{dt:%Y-%m-%d} - {sanitize(title)}"
        seen[base] = seen.get(base, 0) + 1
        out.append((f"{base}.mp3" if seen[base] == 1 else f"{base} ({seen[base]}).mp3", url))
    return out


def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)


def retry(fn, what):
    for i in range(len(BACKOFF) + 1):
        try:
            return fn()
        except (urllib.error.URLError, OSError, ValueError) as e:  # HTTPError is a URLError
            code = getattr(e, "code", None)
            if i == len(BACKOFF) or (code and code < 500 and code != 429):
                raise
            log.warning("%s failed (%s), retry in %ss", what, e, BACKOFF[i])
            time.sleep(BACKOFF[i])


def parse_feed(xml_bytes):
    ch = ET.fromstring(xml_bytes).find("channel")
    items = []
    for it in ch.findall("item"):
        enc, pub = it.find("enclosure"), it.findtext("pubDate")
        if enc is None or not enc.get("url") or not pub:
            log.warning("skipping item without enclosure/pubDate: %s", it.findtext("title"))
            continue
        items.append((parsedate_to_datetime(pub), it.findtext("title") or "", enc.get("url")))
    img = ch.find(ITUNES + "image")
    cover = (img.get("href") if img is not None else None) or ch.findtext("image/url")
    return items, cover


def download(url, final):
    part = final.with_name(final.name + ".part")

    def once():
        with open_url(url) as r, open(part, "wb") as f:
            want = r.headers.get("Content-Length")
            n = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                n += len(chunk)
        if want and int(want) != n:
            raise ValueError(f"incomplete: got {n} of {want} bytes")
        if n == 0:
            raise ValueError("empty download")
        return n

    try:
        n = retry(once, final.name)
        part.rename(final)
        return n
    finally:
        part.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("dest", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pause", type=float, default=3)
    ap.add_argument("--log-file")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler()] + ([logging.FileHandler(a.log_file)] if a.log_file else []))

    items, cover = parse_feed(retry(lambda: open_url(a.feed).read(), "feed"))
    planned = plan(items)
    a.dest.mkdir(parents=True, exist_ok=True) if not a.dry_run else None
    have = {p.name for p in a.dest.iterdir()} if a.dest.is_dir() else set()
    todo = [(n, u) for n, u in planned if n not in have]
    log.info("feed has %d episodes, %d missing", len(planned), len(todo))
    if a.dry_run:
        for n, _ in todo:
            print(n)
        print(f"SUMMARY total={len(planned)} missing={len(todo)} downloaded=0 failed=0")
        return 0

    if cover and "cover.jpg" not in have:
        try:
            retry(lambda: (a.dest / "cover.jpg").write_bytes(open_url(cover).read()), "cover")
        except Exception as e:
            log.warning("cover art failed: %s", e)

    done = failed = 0
    for i, (name, url) in enumerate(todo, 1):
        try:
            n = download(url, a.dest / name)
            done += 1
            log.info("[%d/%d] %s (%.1f MB)", i, len(todo), name, n / 1e6)
        except Exception as e:
            failed += 1
            log.error("[%d/%d] %s FAILED: %s", i, len(todo), name, e)
        time.sleep(a.pause)
    print(f"SUMMARY total={len(planned)} missing={len(todo) - done} downloaded={done} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
