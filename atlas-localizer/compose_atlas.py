#!/usr/bin/env python3
"""Pack per-locale sprite PNGs into a compact power-of-two atlas + .tpsheet.

usage: compose_atlas.py --manifest slices/manifest.json --sprites-dir final/fr
                        --locale fr --out-dir out/fr [--tpsheet original.tpsheet]
                        [--padding 2] [--max-width 4096]

Only the sprites present in --sprites-dir are included. Sprite sizes are kept
exactly, but positions are re-packed (shelf packing, tallest first) into the
smallest power-of-two canvas that fits — the output atlas does NOT mirror the
source layout. Output .tpsheet rows keep their original pivot/border columns
verbatim (from the source sheet) with rewritten x/y, bottom-origin as the
TexturePacker Unity exporter expects.
"""
import argparse
import json
import os
import sys

from PIL import Image

import tpsheet


def next_pot(n):
    p = 1
    while p < n:
        p *= 2
    return p


def shelf_pack(sizes, width, pad):
    """sizes: [(name, w, h)] — returns ({name: (x, top_y)}, used_height) or
    (None, 0) if some sprite is wider than the canvas."""
    x, y, shelf_h = pad, pad, 0
    placements = {}
    for name, w, h in sorted(sizes, key=lambda s: (-s[2], -s[1])):
        if w + 2 * pad > width:
            return None, 0
        if x + w + pad > width:
            x, y, shelf_h = pad, y + shelf_h + pad, 0
        placements[name] = (x, y)
        x += w + pad
        shelf_h = max(shelf_h, h)
    return placements, y + shelf_h + pad


def best_packing(sizes, pad, max_width):
    """Try power-of-two widths, keep the packing with the smallest canvas area
    (ties: the more square one)."""
    best = None
    width = next_pot(max(w for _, w, _ in sizes) + 2 * pad)
    while width <= max_width:
        placements, used_h = shelf_pack(sizes, width, pad)
        if placements:
            height = next_pot(used_h)
            key = (width * height, max(width, height))
            if best is None or key < best[0]:
                best = (key, width, height, placements)
        width *= 2
    if best is None:
        sys.exit(f"no packing fits within --max-width {max_width}")
    return best[1], best[2], best[3]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--sprites-dir", required=True)
    p.add_argument("--locale", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--tpsheet")
    p.add_argument("--padding", type=int, default=2)
    p.add_argument("--max-width", type=int, default=4096)
    a = p.parse_args()

    with open(a.manifest, encoding="utf-8") as f:
        manifest = json.load(f)
    atlas_stem = os.path.splitext(os.path.basename(manifest["atlas"]))[0]
    out_name = f"{atlas_stem}_{a.locale}"

    available = {os.path.splitext(f)[0] for f in os.listdir(a.sprites_dir)
                 if f.endswith(".png")}
    included = [s for s in manifest["sprites"] if s["name"] in available]
    if not included:
        sys.exit(f"no matching sprite PNGs in {a.sprites_dir}")

    images = {}
    for s in included:
        im = Image.open(os.path.join(a.sprites_dir, f"{s['name']}.png")).convert("RGBA")
        if im.size != (s["w"], s["h"]):
            print(f"warning: {s['name']} is {im.size[0]}x{im.size[1]}, "
                  f"resizing to rect {s['w']}x{s['h']}", file=sys.stderr)
            im = im.resize((s["w"], s["h"]), Image.LANCZOS)
        images[s["name"]] = im

    sizes = [(s["name"], s["w"], s["h"]) for s in included]
    W, H, placements = best_packing(sizes, a.padding, a.max_width)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for name, (x, top) in placements.items():
        canvas.paste(images[name], (x, top))

    os.makedirs(a.out_dir, exist_ok=True)
    png_path = os.path.join(a.out_dir, f"{out_name}.png")
    canvas.save(png_path)

    # Source sheet rows carry pivots/borders; rewrite only x/y (bottom-origin).
    sheet_source = a.tpsheet
    if not sheet_source and manifest["rect_source"].endswith(".tpsheet"):
        sheet_source = manifest["rect_source"]
    rows = {}
    if sheet_source:
        src = tpsheet.parse(sheet_source)
        rows = {s.name: s.raw_row for s in src.sprites}
        directives = [(k, v) for k, v in src.directives]
    else:
        print("warning: no source tpsheet — synthesizing rows "
              "(pivot 0.5;0.5, zero borders)", file=sys.stderr)
        directives = [("format", "40300"), ("texture", ""), ("size", ""),
                      ("pivotpoints", "enabled"), ("borders", "disabled"),
                      ("alphahandling", "ClearTransparentPixels")]

    sheet = tpsheet.Sheet(directives=[
        (k, f"{W}x{H}" if k == "size" else v) for k, v in directives])
    for s in included:
        x, top = placements[s["name"]]
        y_bottom = H - top - s["h"]
        if s["name"] in rows:
            fields = rows[s["name"]].split(";")
            fields[1], fields[2] = str(x), str(y_bottom)
            row = ";".join(fields)
        else:
            row = f"{s['name']};{x};{y_bottom};{s['w']};{s['h']}; 0.5;0.5; 0;0;0;0"
        sheet.sprites.append(tpsheet.Sprite(
            s["name"], x, y_bottom, s["w"], s["h"], raw_row=row))

    sheet_path = os.path.join(a.out_dir, f"{out_name}.tpsheet")
    tpsheet.write(sheet_path, sheet, texture_name=f"{out_name}.png")

    print(f"packed {len(included)} sprites into {W}x{H} -> {png_path}\n"
          f"tpsheet -> {sheet_path}")


if __name__ == "__main__":
    main()
