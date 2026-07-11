#!/usr/bin/env bash
#
# speed.sh — Speed up or slow down a video
#
# Re-times a video by a speed factor: 2 plays twice as fast (half the
# duration), 0.5 plays at half speed (double the duration). Video timestamps
# are rescaled with setpts and audio tempo is adjusted with chained atempo
# filters, so pitch is preserved at any factor.
#
# Usage:
#   ./speed.sh <input> <speed> [output]
#   ./speed.sh clip.mp4 2               # 2x faster  -> clip_2x.mp4
#   ./speed.sh clip.mp4 0.5x            # half speed -> clip_0.5x.mp4
#   ./speed.sh clip.mp4 8 --mute        # 8x, drop the audio track
#   ./speed.sh <directory> <speed>      # re-time every video in a directory
#
# Options:
#   --mute          drop audio instead of retiming it
#   --crf N         x264 quality (default 18, lower = better)
#   --preset NAME   x264 preset (default medium)
#
# Requires: ffmpeg, ffprobe (in PATH).

set -euo pipefail

CRF=18
PRESET=medium
MUTE=0
INPUT=""
SPEED=""
OUTPUT=""

err() { printf 'Error: %s\n' "$1" >&2; exit 1; }

command -v ffmpeg  >/dev/null 2>&1 || err "ffmpeg not found in PATH"
command -v ffprobe >/dev/null 2>&1 || err "ffprobe not found in PATH"

# --- parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mute)   MUTE=1; shift ;;
    --crf)    CRF="${2:?--crf needs a value}"; shift 2 ;;
    --preset) PRESET="${2:?--preset needs a value}"; shift 2 ;;
    -h|--help)
      sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    -*)
      err "unknown option: $1" ;;
    *)
      if [[ -z "$INPUT" ]]; then INPUT="$1"
      elif [[ -z "$SPEED" ]]; then SPEED="$1"
      elif [[ -z "$OUTPUT" ]]; then OUTPUT="$1"
      else err "unexpected extra argument: $1"
      fi
      shift ;;
  esac
done

[[ -n "$INPUT" ]] || err "no input given (try --help)"
[[ -e "$INPUT" ]] || err "input not found: $INPUT"
[[ -n "$SPEED" ]] || err "no speed given, e.g. 2, 2x, 0.5 (try --help)"

SPEED="${SPEED%x}"   # allow "2x" as well as "2"
[[ "$SPEED" =~ ^[0-9]+(\.[0-9]+)?$ ]] || err "speed must be a number, e.g. 2 or 0.5"
awk "BEGIN{exit !($SPEED > 0)}"       || err "speed must be greater than 0"
awk "BEGIN{exit !($SPEED != 1)}"      || err "a speed of 1 changes nothing"

# atempo only accepts factors in [0.5, 2.0], so extreme speeds are built by
# chaining several atempo filters that multiply to the requested factor.
build_atempo() {
  local s="$1" chain=""
  while awk "BEGIN{exit !($s > 2.0)}"; do
    chain+="atempo=2.0,"
    s="$(awk "BEGIN{print $s / 2.0}")"
  done
  while awk "BEGIN{exit !($s < 0.5)}"; do
    chain+="atempo=0.5,"
    s="$(awk "BEGIN{print $s / 0.5}")"
  done
  printf '%s' "${chain}atempo=${s}"
}

ATEMPO="$(build_atempo "$SPEED")"

# --- re-time a single file ----------------------------------------------------
retime_one() {
  local in="$1" out="$2"

  echo "→ $in"
  echo "  re-timing to ${SPEED}x (crf=$CRF, preset=$PRESET)"

  local audio_args=(-an)
  local has_audio
  has_audio="$(ffprobe -v error -select_streams a:0 \
               -show_entries stream=codec_type -of csv=p=0 "$in" || true)"
  if [[ "$MUTE" -eq 0 && -n "$has_audio" ]]; then
    audio_args=(-map 0:a:0 -filter:a "$ATEMPO" -c:a aac -b:a 192k)
  fi

  # Subtitle/attachment streams are dropped — their timestamps would be wrong.
  local mov_args=()
  case "${out##*.}" in
    mp4|mov|m4v|MP4|MOV|M4V) mov_args=(-movflags +faststart) ;;
  esac

  ffmpeg -y -i "$in" -map 0:v:0 \
    -filter:v "setpts=PTS/$SPEED" \
    -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
    "${audio_args[@]}" "${mov_args[@]}" "$out"

  echo "  done: $out"
}

default_out() {
  local in="$1"
  printf '%s_%sx.%s' "${in%.*}" "$SPEED" "${in##*.}"
}

# --- directory or single file -------------------------------------------------
if [[ -d "$INPUT" ]]; then
  [[ -z "$OUTPUT" ]] || err "cannot combine a directory input with an output path"
  shopt -s nullglob nocaseglob
  found=0
  for f in "$INPUT"/*.{mkv,mp4,webm,avi,m4v,mov}; do
    [[ "$f" == *_*x.* ]] && continue   # skip our own previous outputs
    found=1
    retime_one "$f" "$(default_out "$f")"
  done
  shopt -u nullglob nocaseglob
  [[ "$found" -eq 1 ]] || err "no video files found in: $INPUT"
else
  [[ -n "$OUTPUT" ]] || OUTPUT="$(default_out "$INPUT")"
  retime_one "$INPUT" "$OUTPUT"
fi
