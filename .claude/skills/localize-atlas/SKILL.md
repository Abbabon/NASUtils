---
name: localize-atlas
description: Produce per-locale translated versions of a Unity sprite atlas whose sprites contain baked-in text. Use when the user asks to localize an atlas, translate baked-in text in sprites, or generate per-locale sprite sheets. Detects text sprites, translates (solaria catalogs first), regenerates each sprite with gpt-image-2 via Codex CLI, and composes per-locale atlas + .tpsheet outputs.
---

# Localize Atlas

Produce, for each target locale, an atlas PNG containing translated versions of the text-bearing sprites of a source Unity atlas, plus a matching TexturePacker `.tpsheet`. All scripts live in `atlas-localizer/` (repo root); run them from that directory.

## Locales

Source art is **en**. Target locales (from solaria's `_locales.json` — update here if the game adds locales):

| code | language |
|---|---|
| fr | French |
| de | German |
| es | Spanish |
| pt | Portuguese |
| ru | Russian |
| zh-Hans | Chinese (Simplified) |
| zh-Hant | Chinese (Traditional) |
| ja | Japanese |
| ko | Korean |
| ar | Arabic (RTL) |

The user may filter (e.g. "just fr and ja"). On a first run for a new atlas, suggest a 1-locale trial (fr) before the full set — a full run is 10 × N-sprites generations at ~30–60s each.

## Inputs

- **Atlas PNG** (required).
- **.tpsheet** — defaults to the sibling `<stem>.tpsheet`. If none exists, use degraded mode (below).
- **Catalogs dir** (optional) — e.g. `/Users/amit/repos/solaria-client-four/Assets/Localization/Catalogs/Resources/` (`<locale>_LocaleCatalog.asset` YAML files with `- key:` / `value:` entries). Also check `LocalizationPipeline/reports/atlas-text-detected.json` in that repo — the atlas may already have OCR results.
- Optional sprite subset and locale subset.

## Workflow

Work dir: `atlas-localizer/work/<AtlasName>/`. All steps are resumable — check for existing outputs before redoing work.

1. **Preflight**: `codex login status` must say "Logged in using ChatGPT" (billing is the user's ChatGPT subscription — no API key). `python3 -c "import PIL"` must succeed.

2. **Slice**: `python3 slice_atlas.py <atlas.png> --out work/<AtlasName>/slices`. Y-origin defaults to `bottom` (verified TexturePacker-Unity convention). Read 1–2 slices to confirm alignment; if sprites look cut/shifted, re-slice with `--y-origin top`.
   - *Degraded mode (no tpsheet)*: Read the atlas image, estimate sprite rects, write them to `work/<AtlasName>/rects.json` as `[{"name","x","y","w","h"}]` (top-origin coordinates — pass `--y-origin top`), slice with `--rects-json`, Read the slices, and refine rects until clean. Mark all outputs best-effort/preview quality.

3. **Detect + OCR**: Read every slice image. Build a table `sprite → {has_text, english_text}`. Sprites without text are dropped — output atlases contain only translated text sprites. Sprites whose text is **locale-invariant** (pure numerals like "14", symbols) are also dropped — they need no localization and the game keeps using the original sprite.

4. **Translate**: For each text × locale: first Grep the catalogs for the exact English string (record the matched key — baked art must match in-game strings); Claude translates only when no catalog entry exists. Persist to `work/<AtlasName>/translations.json`:
   `{"<sprite>": {"en": "...", "fr": {"text": "...", "source": "catalog:enum.X" | "claude"}, ...}}`

5. **Optional report**: If working against solaria (or asked), Write `work/<AtlasName>/reports/atlas-text-detected.json` in the AtlasTextReport schema: `{"atlases": [{"tpsheetPath", "texturePath", "sprites": [{"spriteName", "ocrText", "suggestedKey", "x", "y"}]}]}`.

6. **Generate + QC** — sequential, per locale × sprite. Skip any sprite whose `final/<locale>/<sprite>.png` already exists (resume support).
   ```sh
   ./generate.sh --prompt "<PROMPT>" \
     --out "$PWD/work/<AtlasName>/gen/<locale>/<sprite>.png" \
     --ref "$PWD/work/<AtlasName>/slices/ref/<sprite>@up.png"   # or the plain slice if no @up ref
   python3 postprocess.py work/<AtlasName>/gen/<locale>/<sprite>.png \
     work/<AtlasName>/final/<locale>/<sprite>.png --fit <W>x<H> --bg key
   ```
   Use `--bg none` when the manifest says `has_alpha: false` (fully opaque rect sprite); `--bg rembg` only as a last resort when the model ignored the background instruction. When the sprite's **silhouette is unchanged** by localization (badges/stamps where only interior text differs), add `--alpha-from <original slice>` for a pixel-perfect edge — but never when the text itself forms the silhouette (free-standing lettering). `--erode N` shaves a glowy generated edge if one appears. When the original slice's content does NOT fill its rect (e.g. a text overlay sitting at the bottom of the rect), add `--place-like work/<AtlasName>/slices/<sprite>.png` so the generated content lands in the original's alpha bbox and stays aligned in-game.

   **Identical text**: if a specific locale's translation happens to equal the source text (brand names, loanwords), skip generation and copy the original slice to `final/<locale>/<sprite>.png` — the atlas stays complete at zero cost. (Universally invariant text — pure numerals — was already dropped at detection.)

   **Cross-atlas reuse**: games reuse text art across atlases. Before generating, pixel-compare each text slice against slices of previously localized atlases under `work/` (`PIL.ImageChops.difference(...).getbbox() is None`); on a match, copy that atlas's `final/<locale>/<sprite>.png` files instead of regenerating.

   **Prompt template**:
   > In the exact art style of the attached reference image: the same graphic element, but the text reads exactly "<TRANSLATED_TEXT>" (in <LOCALE_NAME>) instead of the original text. Reproduce the reference's colors, font weight and style, outlines, shadows, and layout precisely. Solid uniform #eeeeee background, subject filling most of the frame. Do not render any other text or extra glyphs, no watermark, no signature, no border or frame, no transparent-checkerboard pattern, no added shadows.

   Addenda: **ar** — "The text is Arabic: right-to-left, with correctly joined/shaped letterforms." **zh-Hans/zh-Hant/ja/ko** — "Render each character exactly as written; do not invent, omit, or substitute characters."

   **Generation background must contrast ALL the sprite's light colors — edges AND interior fills.** Dark-outlined, dark-filled art → `#eeeeee` background (default). Any white/cream/light outline **or fill** anywhere in the design → dark `#555555` background with `--key-color 555555`. Two failure modes otherwise: near-white edges get chewed into ragged speckles, and enclosed near-white fills (e.g. white text inside a dark outline) get wrongly cleared by the pocket pass when the model renders them slightly gray. When keying against `#555555`, pass `--key-tol 40 --hole-tol 40` — nothing in light-on-dark art is near the key, and the aggressive tolerance removes shaded background pockets the defaults leave behind.

   **QC (mandatory)**: Read both the raw gen and the final PNG. Verify (a) the text matches the translation **character-for-character** — for CJK check every character individually, for ar check RTL direction and letter joining; (b) style/colors/layout match the reference; (c) the key didn't clip glyph strokes or leave background patches. On failure, regenerate to `<sprite>.try2.png` with the observed defect appended, e.g. "Previous attempt rendered '<wrong>' — the text must read exactly '<right>'." Max 2 retries, then record the sprite×locale as failed and continue. Never ship unverified text.

7. **Compose** per locale:
   ```sh
   python3 compose_atlas.py --manifest work/<AtlasName>/slices/manifest.json \
     --sprites-dir work/<AtlasName>/final/<locale> --locale <locale> \
     --out-dir work/<AtlasName>/out/<locale>
   ```
   Output: `out/<locale>/<AtlasName>_<locale>.png` + `.tpsheet`. Sprite sizes, pivots, and borders are preserved, but positions are re-packed into the smallest power-of-two canvas that fits (shelf packing) — the output layout does not mirror the source atlas.

8. **Report** to the user: a locales × sprites status table (ok / failed / skipped), translation source per string (catalog key vs Claude), output paths. Note that outputs are staged for review in `work/` (gitignored) — importing into Unity (LocaleSpriteSet / LocalizedImage) is out of scope and up to the user. Give a brief progress line after each locale during long runs.

## Caveats

- gpt-image-2 text fidelity is weakest for CJK and Arabic — expect retries and some failures; recommend native-speaker review for ar before shipping.
- Very small sprites (< ~60px) come out soft: the model outputs ~1024px which is then heavily downscaled.
- `codex` CLI must be installed (`npm i -g @openai/codex`) and logged into ChatGPT.
