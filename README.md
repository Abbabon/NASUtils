# NASUtils

A collection of utilities for personal NAS management, organized into focused sub-projects for file organization, archive creation, ROM management, and YouTube video downloading.

## Project Structure

The repository is organized into specialized sub-projects:

- **`file-organizer/`** - File organization daemon with Docker support
- **`youtube-downloader/`** - YouTube video downloader with multi-language audio
- **`cbz-creator/`** - Comic book archive (CBZ) creation utility
- **`playlist-cleanup/`** - Playlist file cleanup tool
- **`roms/`** - ROM file management suite

## File Organizer (`file-organizer/`)

Daemon process that continuously organizes files by date into YYYY/MM directory structure.

### Docker Commands

```sh
# Build the image
cd file-organizer
docker build -t file-organizer .

# Run container locally
docker run -d --name file-organizer-container \
  -v /path/to/input:/input_directory \
  -v /path/to/output:/output_parent_directory \
  file-organizer
```

### Direct Usage

```sh
python file-organizer/filesOrganizer.py /input_directory /output_parent_directory
```

## YouTube Downloader (`youtube-downloader/`)

Downloads highest quality video with multi-language audio tracks and popular subtitles.

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
./youtube-downloader/yt-download.sh "https://youtube.com/watch?v=VIDEO_ID" [output_directory]
```

If no output directory is specified, downloads to `youtube-downloader/downloads/` folder.

## Other Utilities

### CBZ Creator (`cbz-creator/`)
```sh
python cbz-creator/cbzify.py /path/to/comic/directories
```
Recursively converts image directories into CBZ comic book archives.

### Playlist Cleanup (`playlist-cleanup/`)
```sh
python playlist-cleanup/playlist_cleanup.py /playlist/directory "prefix_to_remove"
```
Cleans playlist files by removing path prefixes with backup creation.

### ROM Management (`roms/`)
```sh
# Count ROM files by extension
python roms/countRoms.py /rom/directory .nes .smc .iso

# Organize ROMs by system
python roms/organizeRoms.py /mixed/rom/directory

# Extract all ZIP files recursively
python roms/unzipRoms.py /rom/directory
```

## TODO

* [ ] filesOrganizer - Add progress logs of some kind (every 10 files?)