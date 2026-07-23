# Atlas Localizer

Produces per-locale translated versions of Unity sprite atlases whose sprites have baked-in text (SALE banners, rarity ribbons, event titles…). For each target locale it emits a new atlas PNG containing only the text-bearing sprites — regenerated with the translated text in the original art style — plus a matching TexturePacker `.tpsheet`.

Driven by the `localize-atlas` Claude Code skill (`.claude/skills/localize-atlas/`), which handles text detection/OCR (Claude vision), translation (game catalogs first, LLM fallback), and QC. The scripts here are the deterministic parts of the pipeline.

## Pipeline

```
atlas.png + atlas.tpsheet
  → slice_atlas.py      crop each sprite → slices/ + manifest.json
  → (Claude)            detect text sprites, OCR, translate per locale
  → generate.sh         gpt-image-2 via Codex CLI, original crop as style ref,
                        on a solid #eeeeee background (model has no alpha)
  → postprocess.py      chroma-key the background away, fit to the sprite rect
  → compose_atlas.py    shelf-pack into a power-of-two canvas → <Atlas>_<locale>.png + .tpsheet
```

Sprite **sizes, pivots, and borders** are preserved exactly (rows copied from the source `.tpsheet`), but the output atlas is re-packed: only the localized sprites are included, shelf-packed into the smallest power-of-two canvas that fits, with x/y rewritten in the output `.tpsheet` (bottom-origin, as the TexturePacker Unity exporter expects).

## Scripts

- **tpsheet.py** — parse/write the TexturePacker Unity `.tpsheet` format (stdlib). Self-test: `python3 tpsheet.py roundtrip file.tpsheet`.
- **slice_atlas.py** — crop sprites to PNGs + `manifest.json`. Y-origin defaults to `bottom` (TexturePacker measures from the bottom of the canvas — verified empirically). `--rects-json` accepts hand-estimated rects when no tpsheet exists. Small sprites also get a nearest-neighbor `ref/<name>@up.png` upscale used only as a generation style reference.
- **generate.sh** — one image via `codex exec --enable image_generation` (gpt-image-2, billed to the ChatGPT subscription — no API key). Adapted from the privateer `generate-art` skill.
- **postprocess.py** — background removal + fit to the exact sprite rect. Default `--bg key` is an edge flood-fill chroma key (removes #eeeeee reachable from the border) plus an enclosed-pocket pass with a tighter `--hole-tol` that clears letter counters (the hole in an 'o') without eating near-white content; interior white text survives, thin glyph strokes are never eaten. `--place-like <original-slice>` keeps partial-rect overlays positioned like the original. `--bg none` for fully-opaque sprites; `--bg rembg` is an ML-matting escape hatch (bootstraps a venv at `~/.cache/nasutils-artgen/venv`).
- **compose_atlas.py** — shelf-pack finals (sizes untouched, tallest first) into the smallest power-of-two canvas and write the `.tpsheet` with rewritten x/y, original pivot/border columns.

## Requirements

- Python 3 + Pillow (`pip install pillow`)
- `codex` CLI (`npm i -g @openai/codex`) logged into ChatGPT (`codex login`)

## Staging

Everything lands under `work/<AtlasName>/` (gitignored): `slices/`, `translations.json`, `gen/<locale>/` (raw model output), `final/<locale>/` (keyed + fitted), `out/<locale>/` (atlas + tpsheet). Runs are resumable — existing `final/` sprites are skipped.

## Caveats

- Image-model text fidelity is weakest for CJK and Arabic (invented/substituted characters, broken RTL shaping). The skill QCs every sprite character-for-character and retries with corrective prompts, but expect failures there; get a native-speaker review for Arabic before shipping.
- Sprites smaller than ~60px come out soft — the model renders at ~1024px and the result is heavily downscaled.
- Generated `.tpsheet` files intentionally omit the `$TexturePacker:SmartUpdate$` hash (it fingerprints the original source images and would be misleading).
