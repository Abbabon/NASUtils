#!/usr/bin/env bash
#
# to-mov.sh — Convert video files to QuickTime-friendly .mov
#
# QuickTime (and many simple editors) can't decode AV1/VP9 video, so files
# downloaded from YouTube (often AV1 in an .mkv) won't open or trim. This
# helper produces a .mov that QuickTime can edit:
#   - If the video is already H.264, it just remuxes (fast, lossless).
#   - Otherwise it re-encodes the video to H.264 (audio is copied when it's
#     already AAC, otherwise re-encoded to AAC).
#
# Usage:
#   ./to-mov.sh <input> [output.mov]
#   ./to-mov.sh <input> --crf 16        # higher quality (default 18)
#   ./to-mov.sh <input> --preset fast   # faster encode (default medium)
#   ./to-mov.sh <directory>             # convert every video in a directory
#
# Requires: ffmpeg, ffprobe (in PATH).

set -euo pipefail

CRF=18
PRESET=medium
OUTPUT=""
INPUT=""

err() { printf 'Error: %s\n' "$1" >&2; exit 1; }

command -v ffmpeg  >/dev/null 2>&1 || err "ffmpeg not found in PATH"
command -v ffprobe >/dev/null 2>&1 || err "ffprobe not found in PATH"

# --- parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --crf)    CRF="${2:?--crf needs a value}"; shift 2 ;;
    --preset) PRESET="${2:?--preset needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*)
      err "unknown option: $1" ;;
    *)
      if [[ -z "$INPUT" ]]; then INPUT="$1"
      elif [[ -z "$OUTPUT" ]]; then OUTPUT="$1"
      else err "unexpected extra argument: $1"
      fi
      shift ;;
  esac
done

[[ -n "$INPUT" ]] || err "no input given (try --help)"
[[ -e "$INPUT" ]] || err "input not found: $INPUT"

# --- convert a single file ----------------------------------------------------
convert_one() {
  local in="$1" out="$2"

  local vcodec acodec
  vcodec="$(ffprobe -v error -select_streams v:0 \
            -show_entries stream=codec_name -of csv=p=0 "$in" || true)"
  acodec="$(ffprobe -v error -select_streams a:0 \
            -show_entries stream=codec_name -of csv=p=0 "$in" || true)"

  # Audio: copy if already AAC, else re-encode.
  local audio_args=(-c:a copy)
  if [[ "$acodec" != "aac" ]]; then
    audio_args=(-c:a aac -b:a 192k)
  fi

  if [[ "$vcodec" == "h264" ]]; then
    echo "→ $in"
    echo "  video is already H.264 — remuxing (lossless)"
    ffmpeg -y -i "$in" -c:v copy "${audio_args[@]}" \
      -movflags +faststart "$out"
  else
    echo "→ $in"
    echo "  video is $vcodec — re-encoding to H.264 (crf=$CRF, preset=$PRESET)"
    ffmpeg -y -i "$in" -c:v libx264 -crf "$CRF" -preset "$PRESET" \
      -pix_fmt yuv420p "${audio_args[@]}" \
      -movflags +faststart "$out"
  fi

  echo "  done: $out"
}

# --- directory or single file -------------------------------------------------
if [[ -d "$INPUT" ]]; then
  [[ -z "$OUTPUT" ]] || err "cannot combine a directory input with an output path"
  shopt -s nullglob nocaseglob
  found=0
  for f in "$INPUT"/*.{mkv,mp4,webm,avi,m4v}; do
    found=1
    convert_one "$f" "${f%.*}.mov"
  done
  shopt -u nullglob nocaseglob
  [[ "$found" -eq 1 ]] || err "no video files found in: $INPUT"
else
  [[ -n "$OUTPUT" ]] || OUTPUT="${INPUT%.*}.mov"
  convert_one "$INPUT" "$OUTPUT"
fi
