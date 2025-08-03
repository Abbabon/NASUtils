# NASUtils

A collection of utilities for personal NAS management, including file organization, archive creation, ROM management, and YouTube video downloading.

## filesOrganizer

This image includes a python cron script that on activation will look for files under the volume `/input_directory` and divide them into subfolders structures `YYYY/MM` in the volume `/output_parent_directory`.

### Dev Commands

#### Build Image

```sh
 docker build -t file-organizer .
```

#### Start headless (locally)

```sh
 docker run -d --name file-organizer-container -v /path/to/input:/input_directory -v /path/to/output:/output_parent_directory file-organizer
```

## yt-download.sh

YouTube downloader script that downloads the highest quality video with multi-language audio tracks and popular subtitles.

### Features

- **Smart Quality Selection**: Downloads highest quality video format available
- **Multi-Language Audio**: Automatically detects and downloads best audio track for each unique language with proper track titles
- **Popular Subtitles**: Downloads subtitles for 12 popular languages to avoid hundreds of auto-generated tracks
- **Rate Limiting**: Built-in delays and retry logic to handle YouTube's rate limiting
- **Duplicate Prevention**: Skips downloads if video already exists
- **Organized Output**: Creates unique folders per video using video ID
- **MKV Container**: Merges all tracks into single file with embedded subtitles and metadata
- **Clean Output**: Automatically removes temporary files and standalone subtitle files after embedding

### Requirements

- `yt-dlp` installed and available in PATH
- `ffmpeg` installed and available in PATH (for video/audio processing and metadata)
- Bash shell environment (works with bash 3.2+ including macOS default)

### Usage

```sh
./yt-download.sh "https://youtube.com/watch?v=VIDEO_ID" [output_directory]
```

If no output directory is specified, downloads to `downloads/` folder.

## Other Utilities

- **cbzify.py** - Converts image directories into CBZ comic book archives
- **playlist_cleanup.py** - Cleans playlist files by removing path prefixes
- **roms/countRoms.py** - Counts ROM files by extension
- **roms/organizeRoms.py** - Organizes ROM files into system-specific subdirectories
- **roms/unzipRoms.py** - Recursively extracts ZIP archives

## TODO

* [ ] filesOrganizer - Add progress logs of some kind (every 10 files?)