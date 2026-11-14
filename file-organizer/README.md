# File Organizer

Moves everything the phone syncs into `Photosync/` into `Archive/YYYY/MM/` (dated by file
modification time), and serves a dashboard to watch, control and prune the archive.
Stdlib Python, one container.

## Dashboard

`http://<nas>:8310`

- **Largest**: biggest files that arrived in the last 24 h / 3 / 7 / 30 days or all time,
  filterable to photos or videos. This is the list for "what is eating my daily Backblaze upload".
- **New**: most recent arrivals.
- **Preview**: click any tile. Photos and videos open full size (videos stream with seeking).
  `←`/`→` to browse, **Delete** (click twice) moves the file to the trash, with an Undo toast.
- **Trash**: restore or delete forever. Items older than the retention setting (default 30 days)
  are purged automatically.
- **Activity**: sort runs that moved files, and the service log.
- **Settings**: pause/resume, interval, hold-back time, skip rules, daily upload budget
  (only draws the meter and chart line), trash retention. Saved to `/config/settings.json`.
- Header: status, **Sort now** (works while paused), **Pause/Resume**.

### Where the numbers come from

- *Arrived* is when the file landed in the archive. Files the service moved itself have an exact
  time in `organizer.db`; older files use the file's ctime, which on the NAS is the copy-in time.
  (A file taken in September but synced today shows up under today, in the September folder.)
- Sizes are decimal (1 GB = 10⁹ bytes), like Backblaze.
- Thumbnails come from Synology's `@eaDir` when Synology Photos / File Station has indexed the
  folder. Otherwise JPG/PNG are shown from the original, and HEIC/RAW/video tiles show a type
  label. Chrome and Firefox can't display HEIC; Safari can.

### Delete and Backblaze

Deleted files go to `TRASH_DIRECTORY` (default `./trash` next to `docker-compose.yml`), **outside
the archive**. If the trash lived inside the archive, the Backblaze sync would see the delete as a
new file and upload it again. Make sure that folder is not part of any Backblaze/Hyper Backup task.

Whether a delete also frees space in Backblaze depends on the sync task: a Cloud Sync task that
mirrors deletions will remove it there; a backup with version retention keeps it until retention
expires.

## Sorting rules

| Rule | Default | Why |
|---|---|---|
| Skip paths containing `@` | on | Synology metadata (`@eaDir`, `@SynoResource`) |
| Skip hidden files/folders | on | Sync apps upload into `.IMG_xxxx.MP4` temp files and rename when done; moving one mid-upload strands a partial copy in the archive |
| Hold files changed in the last N seconds | 120 | Same reason, for apps that write in place. Uses ctime, so it works even when mtime is set back to the capture date |
| Never overwrite | always | A name clash becomes `IMG_1234 (1).HEIC` |

## Deploy

```sh
scp -O -r file-organizer/docker-compose.yml file-organizer/.env.example file-organizer/Dockerfile \
  file-organizer/filesOrganizer.py file-organizer/library.py file-organizer/service.py \
  file-organizer/static \
  $NAS_USER@$NAS_IP:/volume1/docker/file-organizer/

ssh $NAS_USER@$NAS_IP
cd /volume1/docker/file-organizer
cp -n .env.example .env        # set DASHBOARD_PASSWORD and TZ
mkdir -p trash config
/usr/local/bin/docker compose up -d --build
/usr/local/bin/docker logs file-organizer
```

Set `DASHBOARD_PASSWORD`: the dashboard can delete files, and without it anyone on the LAN (or
your tailnet) can. The browser asks for it via basic auth; any username works.
POST requests also need an `X-Requested-With: organizer` header, so other web pages can't
trigger deletes through your browser.

## Volumes

| Container | Default host path | Contents |
|---|---|---|
| `/input_directory` | `/volume1/Assets/Photos/Photosync` | phone sync drop folder |
| `/output_parent_directory` | `/volume1/Assets/Photos/Archive` | dated archive |
| `/trash` | `./trash` (next to the compose file) | deleted files until purged |
| `/config` | `./config` (next to the compose file) | `settings.json`, `organizer.db` |

## Develop

```sh
python test_service.py          # sorter rules + full HTTP round trip on a temp tree

# run against local folders
INPUT_DIR=./in OUTPUT_DIR=./archive TRASH_DIR=./trash CONFIG_DIR=./config python service.py
```

The old daemon still works standalone: `python filesOrganizer.py <input> <output>`.
