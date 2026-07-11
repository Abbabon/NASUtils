# Video Converter

Convert video files to a QuickTime-friendly `.mov` so you can preview, trim, and
edit them in QuickTime Player (and other simple editors).

## Why

Videos downloaded from YouTube are frequently **AV1** (or VP9) inside an `.mkv`
container. QuickTime can't decode AV1, so those files won't open or trim — even
though the file itself is fine. Just rewrapping into `.mov` doesn't help; the
**video stream has to be re-encoded to H.264**, which QuickTime handles natively.

## Usage

```sh
# Single file (writes <name>.mov next to it)
./to-mov.sh "video.mkv"

# Explicit output path
./to-mov.sh "video.mkv" "trimmed-source.mov"

# Higher quality / faster encode
./to-mov.sh "video.mkv" --crf 16
./to-mov.sh "video.mkv" --preset fast

# Convert every video in a directory
./to-mov.sh /path/to/downloads/SomeVideoFolder
```

## Behaviour

- **AV1 / VP9 / other** video → re-encoded to **H.264** (`libx264`).
- **Already H.264** → just **remuxed** into `.mov` (fast, lossless, no quality loss).
- Audio is **copied** when it's already AAC, otherwise re-encoded to AAC 192k.
- `+faststart` is set so the `.mov` is ready for streaming/scrubbing.

## Options

| Option            | Default  | Notes                                              |
| ----------------- | -------- | -------------------------------------------------- |
| `--crf <n>`       | `18`     | Quality for re-encode. Lower = better/bigger. 16–20 is the sweet spot. |
| `--preset <p>`    | `medium` | x264 speed/efficiency: `ultrafast`…`veryslow`.     |

## Requirements

- `ffmpeg` and `ffprobe` in `PATH`.
