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
- **Program.cs** - C# .NET 8 console application for downloading YouTube videos with multi-language audio and subtitles
- **YoutubeDownloader.csproj** - .NET project file
- **Dockerfile** - Docker configuration for containerized downloads
- **downloads/** - Default output directory for downloaded videos
- **yt-download.sh** - Legacy shell script (deprecated, use .NET version)
- **formats.txt** - Temporary file for format analysis

### Video Converter (`video-converter/` directory)
- **to-mov.sh** - Converts videos to a QuickTime-editable `.mov`. Probes the source codec: re-encodes AV1/VP9/other to H.264, or just remuxes if already H.264. Copies AAC audio (re-encodes otherwise) and sets `+faststart`. Useful for YouTube downloads, which are often AV1 in an `.mkv` that QuickTime can't open or trim. Supports `--crf`, `--preset`, and directory batch mode.
- **README.md** - Why AV1 won't open in QuickTime, usage, options, and behaviour

### Video Editor (`video-editor/` directory)
- **speed.sh** - Speeds up or slows down a video by a factor (e.g. `2`, `0.5x`). Rescales video timestamps with `setpts` and retimes audio with pitch preserved via chained `atempo` filters, so any factor works (8x timelapse, 0.25x slow-mo). Re-encodes to H.264/AAC, drops subtitle streams, supports `--mute`, `--crf`, `--preset`, and directory batch mode. A `video-speed` project skill (`.claude/skills/video-speed/`) wraps it.
- **README.md** - Usage, options, and behaviour notes

### CBZ Creator (`cbz-creator/` directory)
- **cbzify.py** - Recursively converts image directories into CBZ comic book archives

### Playlist Cleanup (`playlist-cleanup/` directory)
- **playlist_cleanup.py** - Cleans playlist files by removing path prefixes with backup creation

### Sync Conflict Resolver (`sync-conflict-resolver/` directory)
- **sync_conflict_resolver.py** - Interactively resolves Syncthing `*.sync-conflict-*` files: recursively scans a path, shows a colored diff (small text files) or metadata comparison (binary/large), and prompts per conflict to keep original/conflict, skip, open in editor, or quit. Stdlib only.
- **favorites.example.json** - Sample favorites config (saved scan paths)
- **README.md** - Usage, key bindings, favorites format, and the one-device-at-a-time caveat

### ROM Management Suite (`roms/` directory)
- **countRoms.py** - Counts ROM files by extension across directories
- **organizeRoms.py** - Automatically organizes ROM files into system-specific subdirectories based on file extensions
- **unzipRoms.py** - Recursively extracts ZIP archives and removes originals with logging

### Changes Detector (`changes-detector/` directory)
- **docker-compose.yml** - Docker Compose configuration for changedetection.io service
- Monitors websites for changes with configurable intervals and notifications
- Web-based interface accessible via port 8300

### Jellyfin (`jellyfin/` directory)
- **docker-compose.yml** - Managed Jellyfin media server (host networking, memory limit, auto-restart)
- **.env.example** - Paths, timezone, and memory ceiling
- **README.md** - Setup plus a 2026-06-07 crash post-mortem (OOM kill during library scan)

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

# Interactively resolve Syncthing conflict files (decide per conflict)
python sync-conflict-resolver/sync_conflict_resolver.py /path/to/folder

# Preview only / pick from saved favorites / bulk "original always wins"
python sync-conflict-resolver/sync_conflict_resolver.py /path/to/folder --dry-run
python sync-conflict-resolver/sync_conflict_resolver.py            # favorites menu
python sync-conflict-resolver/sync_conflict_resolver.py /path/to/folder --auto original

# Speed up or slow down a video (pitch-preserved audio)
video-editor/speed.sh clip.mp4 2               # 2x faster  -> clip_2x.mp4
video-editor/speed.sh clip.mp4 0.5x            # half speed -> clip_0.5x.mp4
video-editor/speed.sh clip.mp4 8 --mute        # 8x timelapse, no audio
video-editor/speed.sh /path/to/folder 2        # batch-retime a directory

# Convert a video (e.g. an AV1 .mkv from the YouTube downloader) to a QuickTime-editable .mov
video-converter/to-mov.sh "youtube-downloader/downloads/VIDEO_ID/video.mkv"
video-converter/to-mov.sh "video.mkv" --crf 16        # higher quality re-encode
video-converter/to-mov.sh /path/to/folder             # batch-convert a directory

# Count ROM files by extension
python roms/countRoms.py /rom/directory .nes .smc .iso

# Organize ROMs by system
python roms/organizeRoms.py /mixed/rom/directory

# Extract all ZIP files recursively
python roms/unzipRoms.py /rom/directory

# Start changes detector service
cd changes-detector && docker compose up -d

# View changes detector logs
cd changes-detector && docker compose logs -f

# Download YouTube video with best quality and multi-language audio (.NET version)
cd youtube-downloader && dotnet run "https://youtube.com/watch?v=VIDEO_ID" [output_directory]

# Download all videos from a YouTube playlist
cd youtube-downloader && dotnet run "https://youtube.com/playlist?list=PLAYLIST_ID" [output_directory]

# Download specific playlist items (single, multiple, range, or combined)
cd youtube-downloader && dotnet run "https://youtube.com/playlist?list=PLAYLIST_ID" --items 3
cd youtube-downloader && dotnet run "https://youtube.com/playlist?list=PLAYLIST_ID" --items 1,3,5
cd youtube-downloader && dotnet run "https://youtube.com/playlist?list=PLAYLIST_ID" --items 2-7
cd youtube-downloader && dotnet run "https://youtube.com/playlist?list=PLAYLIST_ID" --items 1,3-5,8

# Or build and run as executable
cd youtube-downloader && dotnet build && ./bin/Debug/net8.0/YoutubeDownloader "https://youtube.com/watch?v=VIDEO_ID" [output_directory]

# Docker version
cd youtube-downloader && docker build -t youtube-downloader . && docker run -v $(pwd)/downloads:/app/downloads youtube-downloader "https://youtube.com/watch?v=VIDEO_ID"
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
The file organizer, YouTube downloader, and changes detector have Docker support:

**File Organizer** (`file-organizer/filesOrganizer.py`):
- Python 3.9-slim base image
- Volume mounts for input/output directories
- Continuous monitoring with 60-second intervals

**YouTube Downloader** (`youtube-downloader/Program.cs`):
- .NET 8 runtime base image
- Pre-installed yt-dlp and ffmpeg dependencies
- Volume mounts for downloads directory

**Changes Detector** (`changes-detector/docker-compose.yml`):
- Uses ghcr.io/dgtlmoon/changedetection.io image
- Persistent data storage via named volume
- Configurable environment variables for timezone, logging, and monitoring settings
- Optional Chrome browser support for JavaScript-heavy websites
- Web interface on port 8300

## NAS Deployment

### Target Environment
- **Hardware**: Synology DS423 (AMD Ryzen R1600)
- **OS**: DSM 7.x
- **Container runtime**: Container Manager (Synology's Docker package)
- **Local IP**: see `NAS_IP` in root `.env` (copy from `.env.example`)
- **Timezone**: see `TZ` in `.env` files (IANA format)

### Synology Path Conventions
- All shared folders live under `/volume1/` (primary storage volume)
- Docker project files: `/volume1/docker/<project-name>/`
- Common shared folders: `/volume1/Assets/`, `/volume1/homes/`, `/volume1/docker/`
- USB drives mount at `/volumeUSB1/`, `/volumeUSB2/`

### Deploying Services via SSH + CLI

Containers are managed via SSH and `docker compose` CLI. The Container Manager GUI (DSM web UI) can be used to monitor containers (start/stop/logs) but **do not mix CLI and GUI management** on the same container — it can cause config mismatches.

```sh
# SSH into NAS (key auth configured — see NAS_USER and NAS_IP in .env.example)
ssh $NAS_USER@$NAS_IP

# Docker binary location (not in default PATH)
/usr/local/bin/docker compose up -d
/usr/local/bin/docker compose logs -f
/usr/local/bin/docker ps
```

**Deploying from local machine:**
```sh
# Copy project files to NAS
scp -O <local-files> $NAS_USER@$NAS_IP:/volume1/docker/<project-name>/

# SSH in and start
ssh $NAS_USER@$NAS_IP
cd /volume1/docker/<project-name>
/usr/local/bin/docker compose up -d --build
```

**Note:** `docker` is at `/usr/local/bin/docker` on the NAS — it's not in the default PATH for non-root users. Use the full path or add it to your shell profile.

### File-Organizer Deployment
The file-organizer has a `docker-compose.yml` with env var defaults:
- **Input**: `/volume1/Assets/Photos/Photosync` (recursive scan of subfolders)
- **Output**: `/volume1/Assets/Photos/Archive` (organized into `YYYY/MM` structure)

```sh
# Deploy on NAS
cd /volume1/docker/file-organizer
# Optionally create .env from .env.example to override paths
docker compose up -d

# Check logs
docker logs file-organizer
```

### Secure Remote Access (Tailscale)

Tailscale is recommended for secure remote access — zero port forwarding, works behind CGNAT, free for personal use.

**Setup:**
1. Install Tailscale from Synology Package Center (DSM 7.x native package)
2. Authenticate: `sudo tailscale up`
3. Optional subnet routing: `sudo tailscale up --advertise-routes=$NAS_SUBNET`
4. Access from anywhere: `ssh $NAS_USER@<tailscale-ip>` or `ssh $NAS_USER@<nas-hostname>` (MagicDNS)

**Alternatives** (if Tailscale doesn't fit):
- **Synology VPN Server** (OpenVPN/L2TP) — requires port forwarding
- **Cloudflare Tunnel** — zero open ports, runs as a container, good for web services
- **Synology QuickConnect** — DSM web UI only, no SSH/CLI access
- **DDNS + HTTPS** — Let's Encrypt via DSM, requires port forwarding

### NAS Best Practices

**Container management:**
- Always use `docker compose` (not bare `docker run`) for reproducibility
- Pin image versions in production (e.g., `python:3.9-slim`), use `:latest` only for testing
- Set `restart: unless-stopped` on all services
- Configure log rotation on every service to prevent filling the volume:
  ```yaml
  logging:
    driver: "json-file"
    options:
      max-size: "10m"
      max-file: "3"
  ```
- Use `.env` files for paths and secrets, never hard-code Synology paths in compose files
- Use `TZ` environment variable consistently across all services (set in each project's `.env`)
- Run containers as non-root when possible (`user: "1026:100"` for Synology default user UID:GID)

**Testing and deployment:**
- Test containers locally before deploying to NAS
- Keep compose files in this repo, deploy by copying to `/volume1/docker/<project>/`
- Monitor container health via Container Manager UI or `docker ps` / `docker logs`

**Security:**
- SSH hardening: change default port (e.g., 2222), use key-only auth, disable password login
- Enable 2FA in DSM: Control Panel → User & Group → Advanced → 2-Factor Authentication
- Enable auto-block for failed logins: Control Panel → Security → Account
- Configure DSM firewall: Control Panel → Security → Firewall (deny all, allow specific ports)
- Keep DSM and all packages updated
- Never expose SSH or DSM directly to the internet — use Tailscale or VPN

**Backups:**
- Back up `/volume1/docker/` regularly using Hyper Backup
- Include compose files, `.env` files, and persistent data volumes
- Test restores periodically

### YouTube Download Features
The YouTube downloader (`youtube-downloader/Program.cs`) provides:
- **Playlist Support**: Automatically detects playlist URLs and downloads all videos sequentially with progress tracking and summary report
- **Item Selection**: Download specific playlist items by index (`--items 3`), multiple (`--items 1,3,5`), range (`--items 2-7`), or combined (`--items 1,3-5,8`)
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
- Requires `deno` JavaScript runtime (used by yt-dlp for YouTube extraction)
- Requires `ffmpeg` to be installed and available in PATH (for video/audio processing and metadata)
- .NET 8 runtime
- Cross-platform compatibility (Windows, macOS, Linux)