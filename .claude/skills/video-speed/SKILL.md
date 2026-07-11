---
name: video-speed
description: Speed up or slow down a video file using video-editor/speed.sh. Use when the user asks to make a video faster or slower, change playback speed, create a timelapse, or make a slow-motion clip.
---

# Video Speed

Change a video's playback speed with `video-editor/speed.sh`. It rescales
video timestamps (`setpts`) and retimes audio with pitch preserved (`atempo`,
chained automatically for factors outside 0.5–2.0).

## How to run

```sh
video-editor/speed.sh <input> <speed> [output]
```

- `<speed>` is a factor: `2` (or `2x`) = twice as fast, `0.5` = half speed.
  Must be a positive number other than 1.
- Default output is `<input>_<speed>x.<ext>` next to the input.
- Pass a directory as `<input>` to re-time every video in it (no explicit
  output path allowed in that mode).

## Options

- `--mute` — drop the audio track (good for timelapses at high factors).
- `--crf N` — x264 quality, default 18 (lower = better).
- `--preset NAME` — x264 preset, default `medium` (`fast` for quicker encodes).

## Examples

```sh
video-editor/speed.sh clip.mp4 2                # 2x -> clip_2x.mp4
video-editor/speed.sh clip.mp4 0.5              # slow-mo -> clip_0.5x.mp4
video-editor/speed.sh clip.mp4 8 --mute         # 8x timelapse, no audio
video-editor/speed.sh clip.mkv 1.5 out.mov      # explicit output, .mov container
video-editor/speed.sh ~/Movies/hikes 4          # batch a whole directory
```

## Notes for Claude

- Requires `ffmpeg`/`ffprobe` in PATH; the script errors out clearly if missing.
- Output is always re-encoded to H.264 + AAC; subtitle streams are dropped.
- If the user wants the result to open in QuickTime, prefer a `.mov`/`.mp4`
  output name (or run `video-converter/to-mov.sh` afterwards for non-H.264
  sources — not needed here since speed.sh already outputs H.264).
- After running, verify the new duration ≈ original / speed with:
  `ffprobe -v error -show_entries format=duration -of csv=p=0 <file>`
