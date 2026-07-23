#!/usr/bin/env bash
# Generate one image with gpt-image-2 via Codex CLI (ChatGPT subscription).
# Adapted from privateer's generate-art skill.
# usage: generate.sh --prompt "..." --out /abs/path/out.png [--ref /abs/ref.png ...]
set -euo pipefail

PROMPT="" OUT=""
REFS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt) PROMPT="$2"; shift 2 ;;
    --out)    OUT="$2";    shift 2 ;;
    --ref)    REFS+=("$2"); shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$PROMPT" && -n "$OUT" ]] || { echo "usage: generate.sh --prompt '...' --out out.png [--ref ref.png ...]" >&2; exit 2; }

command -v codex >/dev/null || { echo "codex CLI not found — install with: npm i -g @openai/codex" >&2; exit 1; }

mkdir -p "$(dirname "$OUT")"
OUTDIR="$(cd "$(dirname "$OUT")" && pwd)"
BASE="$(basename "$OUT")"

IARGS=()
for r in ${REFS[@]+"${REFS[@]}"}; do
  [[ -f "$r" ]] || { echo "reference image not found: $r" >&2; exit 1; }
  IARGS+=(-i "$r")
done

MARKER="$(mktemp "${TMPDIR:-/tmp}/atlasgen-marker.XXXXXX")"

INSTRUCTIONS="Use your image generation tool to generate exactly one image, then save the resulting image file to ./$BASE (relative to the working directory) and stop. Do not create any other files, do not edit anything else. Image request: $PROMPT"

# NOTE: the prompt must come BEFORE the -i flags — `-i <FILE>...` is greedy and
# would otherwise swallow a trailing positional prompt as an image path.
codex exec \
  --enable image_generation \
  -s workspace-write \
  --skip-git-repo-check \
  -C "$OUTDIR" \
  "$INSTRUCTIONS" \
  ${IARGS[@]+"${IARGS[@]}"} \
  < /dev/null >&2

# Fallback: codex sometimes leaves the artifact only under ~/.codex/generated_images.
# Claim the file with mv (not cp) so concurrent generate.sh runs that hit the
# fallback in the same window can't both grab the same image; on a lost race,
# retry — our own image may land a moment later.
if [[ ! -f "$OUT" ]]; then
  GENDIR="${CODEX_HOME:-$HOME/.codex}/generated_images"
  for _ in 1 2 3 4 5; do
    NEWEST="$(find "$GENDIR" -type f -name '*.png' -newer "$MARKER" -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1)"
    if [[ -n "$NEWEST" ]] && mv "$NEWEST" "$OUT" 2>/dev/null; then
      break
    fi
    sleep 2
  done
  if [[ ! -f "$OUT" ]]; then
    rm -f "$MARKER"
    echo "generation failed: $OUT was not produced" >&2
    exit 1
  fi
fi
rm -f "$MARKER"
echo "$OUT"
