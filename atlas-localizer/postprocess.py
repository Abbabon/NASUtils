#!/usr/bin/env python3
"""Post-process a generated sprite: remove the #eeeeee background, fit to rect.

usage: postprocess.py in.png out.png --fit WxH
                      [--bg key|none|rembg] [--key-color eeeeee] [--key-tol 28]
                      [--trim]

  --fit WxH     trim to alpha bbox, aspect-preserving fit, centered on an
                exact WxH transparent canvas (the sprite's original rect)
  --bg key      (default) edge flood-fill chroma key: flood from all border
                pixels, clearing colors within --key-tol of --key-color.
                Interior near-white pixels (white text fill, highlights)
                survive because the fill cannot reach them. Cannot eat thin
                glyph strokes, unlike ML matting.
  --bg none     keep input opaque; LANCZOS-resize to fill WxH edge-to-edge
                (for sprites whose original crop was fully opaque)
  --bg rembg    ML matting escape hatch, only when the model ignored the
                background instruction. Bootstraps a venv at
                ~/.cache/nasutils-artgen/venv (rembg[cpu]+pillow); first call
                downloads the ~170MB u2net model to ~/.u2net.
  --trim        crop to alpha bbox before fitting (default with --bg key)
  --place-like ORIGINAL.png
                place the content where the ORIGINAL slice's content sits:
                fit into the original's alpha bounding box (instead of the
                whole rect) so partially-filled sprites — e.g. a text overlay
                occupying only the bottom of its rect — stay aligned in-game
  --alpha-from ORIGINAL.png
                replace the output's alpha channel with the ORIGINAL slice's
                (sizes must match). Perfect silhouettes for sprites whose
                shape is unchanged by localization (badges/stamps where only
                interior text differs). Never use when the text itself forms
                the silhouette.
"""
import argparse
import os
import subprocess
import sys
from collections import deque

VENV = os.path.expanduser("~/.cache/nasutils-artgen/venv")
VENV_PY = os.path.join(VENV, "bin", "python")


def ensure_venv():
    # Only needed for rembg. sys.prefix identifies the venv; sys.executable can
    # be a symlink back to the base interpreter (pyenv), so it is NOT a
    # reliable membership test.
    if os.path.realpath(sys.prefix) == os.path.realpath(VENV):
        return
    if not os.path.exists(VENV_PY):
        print(f"bootstrapping venv at {VENV} (one-time, a few minutes)...", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "venv", VENV])
        subprocess.check_call([VENV_PY, "-m", "pip", "install", "--quiet", "rembg[cpu]", "pillow"])
    os.execv(VENV_PY, [VENV_PY] + sys.argv)


def flood_key(im, key_rgb, tol, hole_tol, erode=0):
    """Clear alpha of background-colored pixels reachable from the image edge,
    then clear enclosed background pockets (letter counters like the hole in an
    'o') with the tighter hole_tol — tight enough that near-key CONTENT (e.g.
    white text fill at distance ~17 from #eeeeee) survives while generated
    background (distance ~0-5) does not."""
    w, h = im.size
    px = im.load()

    def is_bg(x, y):
        r, g, b = px[x, y][:3]
        return (abs(r - key_rgb[0]) <= tol and abs(g - key_rgb[1]) <= tol
                and abs(b - key_rgb[2]) <= tol)

    seen = bytearray(w * h)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if not seen[y * w + x] and is_bg(x, y):
                seen[y * w + x] = 1
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y * w + x] and is_bg(x, y):
                seen[y * w + x] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and is_bg(nx, ny):
                seen[ny * w + nx] = 1
                queue.append((nx, ny))
    # Enclosed pockets: everything still opaque and within hole_tol of the key
    # is unreachable background (the edge flood already took the rest).
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a and (abs(r - key_rgb[0]) <= hole_tol
                      and abs(g - key_rgb[1]) <= hole_tol
                      and abs(b - key_rgb[2]) <= hole_tol):
                px[x, y] = (r, g, b, 0)
    # Halo: antialiased ring pixels that blend content into the (now cleared)
    # background read as pale key-ish specks after downscaling. Clear pixels
    # touching transparency whose color is within 2*hole_tol of the key.
    halo_tol = 2 * hole_tol
    halo = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if not a:
                continue
            if (abs(r - key_rgb[0]) <= halo_tol and abs(g - key_rgb[1]) <= halo_tol
                    and abs(b - key_rgb[2]) <= halo_tol):
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not px[nx, ny][3]:
                        halo.append((x, y))
                        break
    for x, y in halo:
        r, g, b, _ = px[x, y]
        px[x, y] = (r, g, b, 0)
    for _ in range(erode):
        ring = [(x, y) for y in range(h) for x in range(w) if px[x, y][3]
                and any(0 <= nx < w and 0 <= ny < h and not px[nx, ny][3]
                        for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)))]
        for x, y in ring:
            r, g, b, _ = px[x, y]
            px[x, y] = (r, g, b, 0)
    decontaminate(im, key_rgb)
    return im


def decontaminate(im, key_rgb, ring=2, blend_frac=0.75):
    """Un-matte the antialiased boundary: edge pixels are content blended into
    the key color (C = a*F + (1-a)*K) and read as a pale fringe on dark
    backgrounds. For opaque pixels within `ring` px of transparency, estimate
    a from the color distance to the key (full opacity assumed at
    blend_frac*255 distance), recover F = (C-(1-a)K)/a, and store (F, a)."""
    w, h = im.size
    px = im.load()
    dist = {}
    frontier = [(x, y) for y in range(h) for x in range(w) if not px[x, y][3]]
    d = 0
    while frontier and d < ring:
        d += 1
        nxt = []
        for x, y in frontier:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (0 <= nx < w and 0 <= ny < h and px[nx, ny][3]
                        and (nx, ny) not in dist):
                    dist[(nx, ny)] = d
                    nxt.append((nx, ny))
        frontier = nxt
    for (x, y), _ in dist.items():
        r, g, b, _a = px[x, y]
        delta = max(abs(r - key_rgb[0]), abs(g - key_rgb[1]), abs(b - key_rgb[2]))
        alpha = min(1.0, delta / (255.0 * blend_frac))
        if alpha >= 1.0:
            continue
        if alpha <= 0.0:
            px[x, y] = (r, g, b, 0)
            continue
        f = tuple(max(0, min(255, round((c - (1 - alpha) * k) / alpha)))
                  for c, k in zip((r, g, b), key_rgb))
        px[x, y] = (*f, round(alpha * 255))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--fit", required=True, help="target WxH (the sprite rect)")
    p.add_argument("--bg", choices=["key", "none", "rembg"], default="key")
    p.add_argument("--key-color", default="eeeeee")
    p.add_argument("--key-tol", type=int, default=28)
    p.add_argument("--hole-tol", type=int, default=12,
                   help="tolerance for clearing enclosed background pockets")
    p.add_argument("--erode", type=int, default=0,
                   help="shave N boundary pixel rings after keying — removes a "
                        "soft antialiased/glowy edge the model painted toward "
                        "the background (use ~3 at generation resolution)")
    p.add_argument("--trim", action="store_true")
    p.add_argument("--place-like", dest="place_like",
                   help="original slice PNG whose alpha bbox is the target box")
    p.add_argument("--alpha-from", dest="alpha_from",
                   help="original slice PNG whose alpha channel replaces the output's")
    a = p.parse_args()

    tw, _, th = a.fit.partition("x")
    tw, th = int(tw), int(th)

    from PIL import Image

    im = Image.open(a.src).convert("RGBA")

    if a.bg == "key":
        key = a.key_color.lstrip("#")
        key_rgb = tuple(int(key[i:i + 2], 16) for i in (0, 2, 4))
        im = flood_key(im, key_rgb, a.key_tol, a.hole_tol, a.erode)
    elif a.bg == "rembg":
        from rembg import remove
        im = remove(im)

    if a.bg == "none":
        im = im.resize((tw, th), Image.LANCZOS)
    else:
        if a.trim or a.bg == "key":
            bbox = im.getchannel("A").getbbox()
            if bbox:
                im = im.crop(bbox)
        # Target box within the rect: the whole rect, or — with --place-like —
        # the original slice's content bbox, so partial-rect overlays keep
        # their in-game position.
        bx, by, bw, bh = 0, 0, tw, th
        if a.place_like:
            orig = Image.open(a.place_like).convert("RGBA")
            obox = orig.getchannel("A").getbbox()
            if orig.size != (tw, th):
                print(f"warning: --place-like size {orig.size} != --fit {tw}x{th}",
                      file=sys.stderr)
            if obox:
                bx, by = obox[0], obox[1]
                bw, bh = obox[2] - obox[0], obox[3] - obox[1]
        scale = min(bw / im.width, bh / im.height)
        # Premultiplied-alpha resize: cleared pixels keep their RGB, and a
        # straight RGBA LANCZOS would bleed that (often near-white) color into
        # edge pixels as a visible halo.
        fitted = im.convert("RGBa").resize(
            (max(1, round(im.width * scale)),
             max(1, round(im.height * scale))), Image.LANCZOS).convert("RGBA")
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        canvas.paste(fitted, (bx + (bw - fitted.width) // 2,
                              by + (bh - fitted.height) // 2))
        im = canvas

    if a.alpha_from:
        donor = Image.open(a.alpha_from).convert("RGBA")
        if donor.size != im.size:
            sys.exit(f"--alpha-from size {donor.size} != output size {im.size}")
        # Cleared pixels kept their (often background-colored) RGB; the donor
        # alpha may re-expose a thin ring of them, so first bleed opaque RGB
        # outward into transparent areas.
        px = im.load()
        w2, h2 = im.size
        frontier = [(x, y) for y in range(h2) for x in range(w2)
                    if px[x, y][3] >= 128]
        filled = {(x, y) for x, y in frontier}
        for _ in range(8):
            nxt = []
            for x, y in frontier:
                for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1)):
                    if 0 <= nx < w2 and 0 <= ny < h2 and (nx, ny) not in filled:
                        r, g, b, _a2 = px[x, y]
                        a2 = px[nx, ny][3]
                        px[nx, ny] = (r, g, b, a2)
                        filled.add((nx, ny))
                        nxt.append((nx, ny))
            frontier = nxt
        im.putalpha(donor.getchannel("A"))

    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    im.save(a.dst, "PNG")
    print(a.dst)


if __name__ == "__main__":
    if any(arg == "rembg" or arg.endswith("=rembg") for arg in sys.argv):
        ensure_venv()
    main()
