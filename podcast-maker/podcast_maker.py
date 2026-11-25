#!/usr/bin/env python3
"""Render a two-voice script to one MP3 with ElevenLabs Text to Dialogue.

Usage: podcast_maker.py SCRIPT OUT.mp3 [--cache-dir DIR] [--dry-run] [--max-chars 1900]
Script format (UTF-8, one turn per line, '#' comments and blank lines ignored):
    @voice A = <voice_id>
    @voice B = <voice_id>
    A: first turn
    B: second turn
Turns are packed into chunks at turn boundaries (a single turn longer than --max-chars is an error).
Each chunk's audio is cached in DIR as <hash>.mp3, keyed by model, language, seed, voices and text, so
re-running after an edit only re-renders (and re-bills) changed chunks. Chunks are joined with ffmpeg.
Key: ELEVENLABS_API_KEY from the environment or the repo-root .env. Never printed.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1/text-to-dialogue?output_format=mp3_44100_128"
MODEL, LANGUAGE, SEED = "eleven_v4", "he", 12345
CREDITS_PER_CHAR = 0.41  # observed on this account; the estimate is a guide, not a quote


def parse_script(text):
    """-> (voices {label: id}, turns [(label, text)])"""
    voices, turns = {}, []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"@voice\s+(\w+)\s*=\s*(\S+)$", line)
        if m:
            voices[m[1]] = m[2]
            continue
        m = re.match(r"(\w+):\s*(.+)$", line)
        if not m:
            raise ValueError(f"line {n}: expected 'NAME: text' or '@voice NAME = id'")
        turns.append((m[1], m[2].strip()))
    for label, _ in turns:
        if label not in voices:
            raise ValueError(f"speaker {label!r} has no @voice line")
    return voices, turns


def make_chunks(turns, max_chars):
    chunks, cur, size = [], [], 0
    for label, text in turns:
        if len(text) > max_chars:
            raise ValueError(f"one turn is {len(text)} chars (> {max_chars}): {text[:40]}...")
        if cur and size + len(text) > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append((label, text))
        size += len(text)
    if cur:
        chunks.append(cur)
    return chunks


def chunk_inputs(chunk, voices):
    return [{"text": t, "voice_id": voices[l]} for l, t in chunk]


def cache_key(inputs):
    payload = json.dumps([MODEL, LANGUAGE, SEED, inputs], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def load_key():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("ELEVENLABS_API_KEY not set (environment or repo-root .env)")


def render(inputs, key):
    body = json.dumps({"inputs": inputs, "model_id": MODEL, "language_code": LANGUAGE, "seed": SEED}).encode()
    req = urllib.request.Request(API, body, {"xi-api-key": key, "Content-Type": "application/json",
                                             "User-Agent": "podcast-maker"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--cache-dir", default=None, help="default: <out>.cache next to the output")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-chars", type=int, default=1900, help="per request; the API limit is 2000")
    a = ap.parse_args()

    voices, turns = parse_script(Path(a.script).read_text(encoding="utf-8"))
    chunks = make_chunks(turns, a.max_chars)
    cache = Path(a.cache_dir or a.out + ".cache")
    keys = [cache_key(chunk_inputs(c, voices)) for c in chunks]
    todo = [i for i, k in enumerate(keys) if not (cache / f"{k}.mp3").exists()]
    total = sum(len(t) for _, t in turns)
    billed = sum(len(t) for i in todo for _, t in chunks[i])
    print(f"turns={len(turns)} chunks={len(chunks)} chars={total} to_render={len(todo)} "
          f"chars_to_bill={billed} est_credits={billed * CREDITS_PER_CHAR:.0f}")
    if a.dry_run:
        return
    key = load_key()
    cache.mkdir(parents=True, exist_ok=True)
    failed = 0
    for i in todo:
        try:
            audio = render(chunk_inputs(chunks[i], voices), key)
            (cache / f"{keys[i]}.mp3.part").write_bytes(audio)
            (cache / f"{keys[i]}.mp3.part").rename(cache / f"{keys[i]}.mp3")
            print(f"chunk {i + 1}/{len(chunks)} ok ({len(audio) // 1024} KB)")
        except Exception as e:  # keep going; finished chunks stay cached for the re-run
            failed += 1
            print(f"chunk {i + 1}/{len(chunks)} FAILED: {e}", file=sys.stderr)
    if failed:
        sys.exit(f"{failed} chunk(s) failed; re-run to retry only those")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for k in keys:
            f.write(f"file '{(cache / f'{k}.mp3').resolve()}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f.name,
                    "-c:a", "libmp3lame", "-b:a", "128k", a.out], check=True)
    os.unlink(f.name)
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
