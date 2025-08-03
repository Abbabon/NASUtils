# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

NASUtils is a collection of utilities for personal NAS management. The repository contains standalone scripts for file organization, archive creation, ROM management, and YouTube video downloading. Each utility is designed to be run independently via command line.

## Architecture

The project is organized into focused sub-projects, each in its own directory:

### File Organizer (`file-organizer/` directory)
- **filesOrganizer.py** - Daemon process that continuously organizes files by date into YYYY/MM directory structure
- **Dockerfile** - Docker configuration for containerized file organization

### YouTube Downloader (`youtube-downloader/` directory)
- **yt-download.sh** - Downloads highest quality video with multi-language audio tracks and popular subtitles
- **downloads/** - Default output directory for downloaded videos
- **formats.txt** - Temporary file for format analysis

### CBZ Creator (`cbz-creator/` directory)
- **cbzify.py** - Recursively converts image directories into CBZ comic book archives

### Playlist Cleanup (`playlist-cleanup/` directory)
- **playlist_cleanup.py** - Cleans playlist files by removing path prefixes with backup creation

### ROM Management Suite (`roms/` directory)
- **countRoms.py** - Counts ROM files by extension across directories
- **organizeRoms.py** - Automatically organizes ROM files into system-specific subdirectories based on file extensions
- **unzipRoms.py** - Recursively extracts ZIP archives and removes originals with logging

## Development Commands

### Docker (filesOrganizer)
```sh
# Build the Docker image (from file-organizer directory)
cd file-organizer
docker build -t file-organizer .

# Run container locally
docker run -d --name file-organizer-container -v /path/to/input:/input_directory -v /path/to/output:/output_parent_directory file-organizer
```

### Running Scripts
All Python scripts are standalone and follow the pattern:
```sh
python script_name.py <required_args> [optional_args]
```

Examples:
```sh
# File organization (runs as daemon)
python file-organizer/filesOrganizer.py /input_directory /output_parent_directory

# Create CBZ archives recursively
python cbz-creator/cbzify.py /path/to/comic/directories

# Clean playlists with custom prefix
python playlist-cleanup/playlist_cleanup.py /playlist/directory "C:\Music"

# Count ROM files by extension
python roms/countRoms.py /rom/directory .nes .smc .iso

# Organize ROMs by system
python roms/organizeRoms.py /mixed/rom/directory

# Extract all ZIP files recursively
python roms/unzipRoms.py /rom/directory

# Download YouTube video with best quality and multi-language audio
./youtube-downloader/yt-download.sh "https://youtube.com/watch?v=VIDEO_ID" [output_directory]
```

## Key Implementation Details

### Error Handling & Logging
- Most scripts use Python's `logging` module with both file and console output
- Playlist cleanup handles multiple text encodings (utf-8, cp1252, latin1)
- ROM scripts provide detailed success/error reporting

### File Processing Patterns
- Scripts use `pathlib.Path` for cross-platform path handling
- Recursive directory traversal with `rglob()` or `os.walk()`
- Backup creation before modifying files (playlist_cleanup creates numbered backups)
- Safe file operations with exception handling

### ROM System Detection
The `organizeRoms.py` uses a mapping of console systems to file extensions:
- NES: .nes, .NES
- SNES: .sfc, .smc  
- N64: .n64, .z64
- GBA: .gba
- Genesis: .gen, .bin, .md
- PlayStation: .bin, .iso, .cue, .img
- And more systems defined in `ROM_TYPES` dictionary

### Docker Integration
Only the file organizer (`file-organizer/filesOrganizer.py`) has Docker support with:
- Python 3.9-slim base image
- Volume mounts for input/output directories
- Continuous monitoring with 60-second intervals

### YouTube Download Features
The YouTube downloader (`youtube-downloader/yt-download.sh`) provides:
- **Smart Quality Selection**: Downloads highest quality video format available
- **Multi-Language Audio**: Automatically detects and downloads best audio track for each unique language with proper track titles
- **Popular Subtitles**: Downloads subtitles for 12 popular languages (en,es,fr,de,it,pt,ru,zh,ja,ko,ar,hi) to avoid hundreds of auto-generated tracks
- **Rate Limiting**: Built-in delays and retry logic to handle YouTube's rate limiting (HTTP 429 errors)
- **Duplicate Prevention**: Skips downloads if video already exists in output directory
- **Organized Output**: Creates unique folders per video using video ID extraction
- **Temporary Downloads**: Uses temp directory during download then moves to final location
- **MKV Container**: Merges all tracks into single MKV file with embedded subtitles and metadata
- **Clean Output**: Automatically removes temporary files and standalone subtitle files after embedding

#### Dependencies
- Requires `yt-dlp` to be installed and available in PATH
- Requires `ffmpeg` to be installed and available in PATH (for video/audio processing and metadata)
- Bash shell environment (compatible with bash 3.2+ including macOS default bash)