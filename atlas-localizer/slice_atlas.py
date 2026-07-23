#!/usr/bin/env python3
"""Crop every sprite of a Unity atlas into individual PNGs + a manifest.

usage: slice_atlas.py <atlas.png> [--tpsheet P | --rects-json P] --out DIR
                      [--sprites a,b,c] [--y-origin top|bottom] [--ref-scale-min 256]

Rect source is the sibling .tpsheet by default, or --rects-json with a list of
{"name","x","y","w","h"} objects (degraded mode when no tpsheet exists).

The Unity TexturePacker exporter measures y from the BOTTOM of the canvas
(verified empirically on solaria atlases), so --y-origin defaults to bottom;
rects-json coordinates estimated visually should use --y-origin top.

Outputs into DIR:
  <name>.png          one crop per sprite
  ref/<name>@up.png   nearest-neighbor upscale (~512px) for sprites whose
                      longest edge is under --ref-scale-min — style reference
                      for image generation only, never composited
  manifest.json       atlas path, canvas size, y-origin, per-sprite rect,
                      pivot, borders, and has_alpha (any pixel alpha < 250)
"""
import argparse
import json
import os
import sys

from PIL import Image

import tpsheet

REF_TARGET = 512  # upscaled reference longest edge


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("atlas")
    p.add_argument("--tpsheet")
    p.add_argument("--rects-json")
    p.add_argument("--out", required=True)
    p.add_argument("--sprites", help="comma-separated subset of sprite names")
    p.add_argument("--y-origin", choices=["top", "bottom"], default="bottom")
    p.add_argument("--ref-scale-min", type=int, default=256)
    a = p.parse_args()

    if a.tpsheet and a.rects_json:
        sys.exit("pass either --tpsheet or --rects-json, not both")

    if a.rects_json:
        with open(a.rects_json, encoding="utf-8") as f:
            rects = json.load(f)
        sprites = [tpsheet.Sprite(r["name"], r["x"], r["y"], r["w"], r["h"])
                   for r in rects]
        source = a.rects_json
    else:
        sheet_path = a.tpsheet or os.path.splitext(a.atlas)[0] + ".tpsheet"
        if not os.path.exists(sheet_path):
            sys.exit(f"no tpsheet at {sheet_path} — pass --tpsheet or --rects-json")
        sprites = tpsheet.parse(sheet_path).sprites
        source = sheet_path

    if a.sprites:
        wanted = set(a.sprites.split(","))
        missing = wanted - {s.name for s in sprites}
        if missing:
            sys.exit(f"unknown sprite names: {', '.join(sorted(missing))}")
        sprites = [s for s in sprites if s.name in wanted]

    atlas = Image.open(a.atlas).convert("RGBA")
    W, H = atlas.size
    os.makedirs(a.out, exist_ok=True)

    manifest = {
        "atlas": os.path.abspath(a.atlas),
        "rect_source": os.path.abspath(source),
        "canvas_size": [W, H],
        "y_origin": a.y_origin,
        "sprites": [],
    }
    for s in sprites:
        top = s.y if a.y_origin == "top" else H - s.y - s.h
        crop = atlas.crop((s.x, top, s.x + s.w, top + s.h))
        crop.save(os.path.join(a.out, f"{s.name}.png"))

        alpha_min = crop.getchannel("A").getextrema()[0]
        if max(s.w, s.h) < a.ref_scale_min:
            scale = max(1, round(REF_TARGET / max(s.w, s.h)))
            ref = crop.resize((s.w * scale, s.h * scale), Image.NEAREST)
            os.makedirs(os.path.join(a.out, "ref"), exist_ok=True)
            ref.save(os.path.join(a.out, "ref", f"{s.name}@up.png"))

        manifest["sprites"].append({
            "name": s.name,
            "x": s.x, "y": s.y, "w": s.w, "h": s.h,
            "pivot": [s.pivot_x, s.pivot_y],
            "borders": list(s.borders),
            "has_alpha": alpha_min < 250,
        })

    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"sliced {len(sprites)} sprites from {a.atlas} -> {a.out} "
          f"(y-origin={a.y_origin})")


if __name__ == "__main__":
    main()
