# NASUtils

A collection of utilities for personal NAS management, organized into focused sub-projects for file organization, archive creation, ROM management, and YouTube video downloading.

## Project Structure

The repository is organized into specialized sub-projects:

- **`file-organizer/`** - File organization daemon with Docker support
- **`youtube-downloader/`** - YouTube video downloader with multi-language audio
- **`cbz-creator/`** - Comic book archive (CBZ) creation utility
- **`playlist-cleanup/`** - Playlist file cleanup tool
- **`roms/`** - ROM file management suite
- **`changes-detector/`** - Website change monitoring service

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

- **`changes-detector/`** - Website change monitoring service

## Changes Detector (`changes-detector/`)

Website change monitoring service using changedetection.io with Docker support.

### Docker Commands

```sh
# Start the service
cd changes-detector
docker compose up -d

# View logs
docker compose logs -f

# Stop the service
docker compose down
```

Access the web interface at `http://<NAS_IP>:8300` (set `NAS_IP` in `changes-detector/.env`).

## NAS Deployment

Services are deployed to a **Synology DS423** running DSM 7.x via **SSH + CLI** (`docker compose`). The Container Manager GUI can monitor containers but should not be used to edit CLI-deployed services.

> **Setup:** Copy `.env.example` to `.env` at the repo root and fill in `NAS_IP`, `NAS_USER`, and `NAS_SUBNET`. Commands below reference these variables.

### Deploying file-organizer

The file-organizer monitors `/volume1/Assets/Photos/Photosync` (including subfolders) and organizes files by date into `/volume1/Assets/Photos/Archive/YYYY/MM/`.

```sh
# Copy project files to NAS (use -O flag for Synology SCP compatibility)
scp -O file-organizer/docker-compose.yml file-organizer/.env.example \
  file-organizer/Dockerfile file-organizer/filesOrganizer.py \
  $NAS_USER@$NAS_IP:/volume1/docker/file-organizer/

# SSH into NAS and deploy
ssh $NAS_USER@$NAS_IP
cd /volume1/docker/file-organizer

# Optionally create .env from .env.example to override default paths
cp .env.example .env

/usr/local/bin/docker compose up -d --build
/usr/local/bin/docker logs file-organizer
```

Other services (changes-detector, immich) follow the same pattern — each has its own `docker-compose.yml`.

> **Note:** `docker` is at `/usr/local/bin/docker` on the NAS and is not in the default PATH for non-root users.

### Secure Remote Access

**Tailscale** (recommended) provides zero-config VPN access with no port forwarding:

1. Install Tailscale from Synology Package Center
2. Authenticate: `sudo tailscale up`
3. Optional subnet routing: `sudo tailscale up --advertise-routes=$NAS_SUBNET`
4. Connect from anywhere: `ssh $NAS_USER@<tailscale-ip>` or use MagicDNS (`ssh $NAS_USER@<nas-hostname>`)

Alternatives: Synology VPN Server (OpenVPN), Cloudflare Tunnel, DDNS + HTTPS.

### Best Practices

- Use `docker compose` for all deployments — never bare `docker run`
- Configure **log rotation** on every service (`max-size: 10m`, `max-file: 3`) to prevent filling the volume
- Use `.env` files for paths and secrets, keep `.env.example` in the repo
- Set `restart: unless-stopped` and `TZ` (from `.env`) on all services
- Pin image versions in production, use `:latest` only for testing
- **SSH hardening**: custom port, key-only auth, disable password login
- **Enable 2FA** and auto-block for failed logins in DSM Control Panel
- **Never expose SSH/DSM directly** to the internet — use Tailscale or VPN
- **Back up** `/volume1/docker/` regularly with Hyper Backup
- Test containers locally before deploying to NAS