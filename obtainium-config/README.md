# Obtainium Config

Per-device [Obtainium](https://github.com/ImranR98/Obtainium) app packs for my retro handhelds,
built as a thin overlay on top of a pinned upstream base pack.

Obtainium installs and updates Android apps straight from their release pages (GitHub, GitLab,
F-Droid, HTML scraping, …) instead of an app store. Its "configuration" is just a JSON file you
import. This project generates that file — one per device — so the set of emulators and tools on
each handheld is version-controlled, diffable, and validated before it touches the device.

## Why an overlay instead of a from-scratch pack

[RJNY/Obtainium-Emulation-Pack](https://github.com/RJNY/Obtainium-Emulation-Pack) already curates
~60 emulator/frontend/utility configs with CI that re-tests every app still resolves. The Android
emulation fork landscape churns constantly (Cemu, NetherSX2, Winlator variants), and tracking it by
hand is the actual cost. So the base pack is pinned upstream and this repo owns only the delta:

- apps upstream doesn't carry (Shizuku, Wayfinder)
- apps upstream deliberately excludes from its exports (ThorTune, via `meta.excludeFromExport`)
- patches to upstream entries (ClusterTune's pre-rename repo slug)
- per-device includes/excludes

That's four entries to maintain instead of sixty.

## Layout

| File | Role |
| --- | --- |
| `base.lock.json` | Pinned upstream repo + release tag, and the asset name per variant |
| `overlay.json` | Local additions, patches, and excludes — the only file you normally edit |
| `profiles.json` | One entry per physical device: which base variant it starts from |
| `build.py` | Base + overlay → `dist/<profile>.json` |
| `validate.py` | Structural checks + live GitHub release resolution |
| `dist/` | Generated, committed — this is what you import on the device |
| `.cache/` | Downloaded upstream release assets, gitignored |

Stdlib only, no dependencies.

## Usage

```sh
cd obtainium-config

python build.py                      # build every profile
python build.py --profile thor       # build one
python build.py --bump-base          # adopt upstream's newest release, then build
python build.py --check              # exit 1 if dist/ is stale (CI gate)
python build.py --refresh            # ignore .cache/, re-download the base pack

python validate.py                   # structure everywhere, live-check local entries
python validate.py --scope all       # live-check every app (needs GITHUB_TOKEN)
python validate.py --scope none      # offline structural checks only
```

### Rate limits and the token

Live checks issue exactly one request per app — `GET /repos/{owner}/{repo}/releases` — read-only,
against public endpoints, for repos already named in the pack. The token is purely a rate-limit
lift: unauthenticated GitHub allows 60 requests/hour per IP and a pack holds ~60 apps, while any
authenticated request gets 5,000/hour.

**The token needs no scopes.** Create a classic PAT with zero boxes checked, or a fine-grained PAT
with "Public Repositories (read-only)". Do not reuse a `gh auth token` — those carry `repo`, which
is full read/write to every private repo you own, for no benefit here.

The token is only ever sent as an `Authorization` header to `api.github.com`. It is never logged,
never written to `dist/`, and never committed.

**You usually do not need one.** CI runs `--scope all` with GitHub's ephemeral workflow token on
every push, so the full sweep happens automatically. A personal token is only for running the full
sweep locally before you push.

#### Option A — one session, nothing stored (simplest)

```sh
cd obtainium-config
read -rs GITHUB_TOKEN && export GITHUB_TOKEN    # paste the token, press Enter (nothing echoes)
python3 validate.py --scope all
```

`read -rs` keeps the token out of `~/.zsh_history`. It lives only in that terminal tab and is gone
when you close it.

#### Option B — persist it in the repo's gitignored .env

The repo root already has a gitignored `.env`. Add a line to it:

```sh
GITHUB_TOKEN=github_pat_xxxxxxxx
```

Then load it before running:

```sh
cd obtainium-config
set -a; source ../.env; set +a
python3 validate.py --scope all
```

`.env` is in `.gitignore` and has never been committed. Confirm before trusting it:

```sh
git check-ignore -v ../.env      # should print the .gitignore rule
```

#### Checking it worked

Without a token you'll see `GitHub API 403` / rate-limit warnings partway through. With one, every
profile reports a clean count:

```
INFO thor   64 apps, live-checked 53/64 ok
OK    0 errors, 12 warning(s)
```

(53 of 64 because 7 apps are non-GitHub sources with no API to resolve, plus track-only entries.)

`--scope overlay` (the default) checks only locally-authored entries — a handful of requests, which
is what you want during normal editing. CI uses `--scope all` with the workflow token.

## Profiles

| Profile | Device | Base | Apps | Notes |
| --- | --- | --- | --- | --- |
| `thor` | AYN Thor | dual-screen | 64 | + Shizuku, Wayfinder, ThorTune; − OdinTools |
| `odin2` | AYN Odin 2 | standard | 58 | + Shizuku; − MelonDualDS (dual-screen fork) |
| `nova` | Anbernic RG Nova | standard | 57 | **Provisional** — device not in hand; arch and screen layout unconfirmed |

Note: upstream's `dual-screen` variant is a strict **superset** of `standard` (+4 apps as of
v7.13.0), not a separately curated dual-screen build. Genuine per-device tailoring happens in
`overlay.json`'s `excludes`, not by picking a base.

## Installing on a device

Obtainium's config import is a **file picker** (Settings → Import/Export → "Obtainium Import").
There is no fetch-from-URL for a full pack — the URL-list import exists but takes newline-separated
app URLs and discards all per-app settings. So the flow is:

1. On the handheld, open the raw URL for your profile:

   ```
   https://raw.githubusercontent.com/Abbabon/NASUtils/main/obtainium-config/dist/thor.json
   https://raw.githubusercontent.com/Abbabon/NASUtils/main/obtainium-config/dist/odin2.json
   https://raw.githubusercontent.com/Abbabon/NASUtils/main/obtainium-config/dist/nova.json
   ```

2. Download it
3. Obtainium → Import/Export → Obtainium Import → pick the file

### What importing actually does

Import is **additive and idempotent**. Apps are matched by package ID: new ones are added, existing
ones have their config updated, and nothing is ever deleted or uninstalled. Removing an app from
this pack does **not** remove it from the handheld — you uninstall that yourself.

Importing 64 apps does **not** install 64 apps. It adds 64 *entries* to Obtainium's list, all
showing as not-installed. You tap the ones you actually want. Because the pack ships
`onlyCheckInstalledOrTrackOnlyApps: true`, the ones you never install are never checked for
updates, so they cost no battery or network.

The import also applies three settings from the pack: `categories` (the colour map), 
`groupByCategory`, and `onlyCheckInstalledOrTrackOnlyApps`. No other Obtainium setting is touched.

### Two update loops, only one of which is automatic

**App versions — automatic, ignore this repo entirely.** Once an app is in Obtainium and installed,
Obtainium checks its release page on its own schedule and notifies (or installs) when a new version
appears. New Dolphin build, new RetroArch — that just happens. You never re-import for this.

**The pack itself — the repo self-updates, the handheld does not.** CI refreshes `dist/` weekly:
adopting upstream's newest release, picking up newly added apps, and re-verifying every config still
resolves. That updates the JSON *in this repo*. Obtainium has no fetch-from-URL for configs, so the
device only sees those changes when you re-import.

So: re-import when you want newly added apps or a config fix. Realistically a few times a year.
Nothing breaks if you never do — your installed apps keep updating regardless.

To see whether a re-import is worth it, check what changed:

```sh
git log --oneline -- obtainium-config/dist/
```

## Two things that will bite you

**Signature mismatch.** Android refuses to update an APK signed by a different key. If an app is
currently installed from the Play Store and this pack fetches the GitHub build, the install fails
and you must uninstall first — **losing app data** (saves, configs) unless you back it up. Audit
anything you installed from Play before importing. Emulator save data lives outside the app sandbox
often enough that this is survivable, but never assume it.

**Credentials in exports.** Obtainium's export has three settings levels; level 2 embeds `*-creds`
keys, which is where your GitHub PAT lives. Upstream ships them empty, but `build.py` strips every
`*-creds` key from both app settings and top-level settings so a populated one can never reach
`dist/`. `validate.py` errors if one survives. Never hand-edit a raw export into this repo.

## Authoring format

In `overlay.json`, `additionalSettings` is a **nested object**. Obtainium's importer expects it as a
**JSON-encoded string**; `build.py` does that conversion. This is the single most common way
hand-written Obtainium configs fail.

Only `id`, `url`, `author`, `name` are required — Obtainium's `appJSONCompatibilityModifiers` fills
every unset key with the source's default on import.

Keys prefixed with `_` are stripped at build time, so you can leave notes inline:

```json
"additionalSettings": {
  "versionDetection": false,
  "_note_versionDetection": "Tag is 'beta-v0.1' but versionName is '1.0'."
}
```

## CI

`.github/workflows/obtainium-config.yaml`:

- **weekly** — bump to upstream's newest release, rebuild, validate all, commit if changed
- **on push** to `obtainium-config/**` — rebuild, validate all, and fail if `dist/` wasn't
  regenerated alongside an overlay edit
