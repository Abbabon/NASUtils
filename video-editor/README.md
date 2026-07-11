# Video Editor

Simple scripts that edit input video files automatically. Each edit is a
standalone script; the first one is **speed** (make a video faster or slower).

## speed.sh

Re-times a video by a speed factor:

- `2` → twice as fast, half the duration
- `0.5` → half speed, double the duration

Video timestamps are rescaled with ffmpeg's `setpts` filter and audio tempo is
adjusted with `atempo`, so **pitch is preserved** — a 2x video doesn't sound
like chipmunks. `atempo` only accepts factors between 0.5 and 2.0, so extreme
speeds (e.g. 8x timelapse or 0.25x slow-mo) are built by chaining several
`atempo` filters automatically.

### Usage

```sh
./speed.sh <input> <speed> [output]

./speed.sh clip.mp4 2               # 2x faster  -> clip_2x.mp4
./speed.sh clip.mp4 0.5x            # half speed -> clip_0.5x.mp4
./speed.sh clip.mp4 8 --mute        # 8x timelapse, drop the audio track
./speed.sh clip.mp4 2 fast.mov      # explicit output path
./speed.sh /path/to/folder 2        # re-time every video in a directory
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `--mute` | off | drop audio instead of retiming it |
| `--crf N` | 18 | x264 quality (lower = better, bigger file) |
| `--preset NAME` | medium | x264 encode speed/size trade-off |

### Behaviour

- The output is always re-encoded to H.264 + AAC (retiming requires a
  re-encode; stream copy isn't possible).
- Default output name is `<input>_<speed>x.<ext>` next to the input.
- Only the first video and first audio stream are kept. Subtitle streams are
  dropped — their timestamps would no longer match.
- `+faststart` is set for `.mp4`/`.mov`/`.m4v` outputs.
- Directory mode skips files that already look like outputs (`*_2x.mp4` etc.).
- Slowing a video down does not invent new frames — a 0.25x clip shows each
  original frame longer rather than interpolating motion.

### Requirements

`ffmpeg` and `ffprobe` in `PATH`.
