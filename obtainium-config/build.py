#!/usr/bin/env python3
"""Build per-device Obtainium config packs from a pinned upstream base plus a local overlay.

Reads base.lock.json, overlay.json and profiles.json; writes one importable JSON per
profile into dist/. Upstream release assets are cached under .cache/<version>/ so repeat
builds are offline and reproducible.

Usage:
    python build.py                    # build every profile
    python build.py --profile thor     # build one
    python build.py --refresh          # ignore the cache, re-download the base pack
    python build.py --check            # build in memory, fail if dist/ is stale
"""

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
CACHE = ROOT / ".cache"

# Obtainium top-level settings we are willing to ship. Anything else - notably any
# "*-creds" key, which holds source API tokens - is dropped so a public repo can never
# carry a secret that leaked in via an upstream export.
SETTINGS_ALLOWLIST = {"categories", "groupByCategory", "onlyCheckInstalledOrTrackOnlyApps"}

# Keys Obtainium's App.fromJson actually reads. "meta" and our own bookkeeping are stripped.
APP_KEYS = {
    "id", "url", "author", "name", "installedVersion", "latestVersion", "apkUrls",
    "otherAssetUrls", "preferredApkIndex", "additionalSettings", "lastUpdateCheck",
    "pinned", "categories", "releaseDate", "changeLog", "overrideSource",
    "allowIdChange", "pendingRepoRenameUrl",
}

USER_AGENT = "NASUtils-obtainium-config/1.0"

log = logging.getLogger("build")


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def get_base_pack(lock, variant, refresh=False):
    """Download (or read from cache) one upstream base pack variant."""
    try:
        template = lock["assets"][variant]
    except KeyError:
        raise SystemExit(
            f"Unknown base variant {variant!r}. Known: {sorted(lock['assets'])}"
        )

    version = lock["version"]
    name = template.format(version=version)
    cached = CACHE / version / name

    if cached.exists() and not refresh:
        log.debug("cache hit: %s", cached.relative_to(ROOT))
        return load_json(cached)

    url = f"https://github.com/{lock['repo']}/releases/download/{version}/{name}"
    log.info("downloading %s", url)
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Could not download base pack ({exc.code}): {url}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach GitHub: {exc.reason}")

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(raw)
    return json.loads(raw)


def bump_base(lock, token=None):
    """Rewrite base.lock.json to upstream's newest release. Returns True if it changed."""
    url = f"https://api.github.com/repos/{lock['repo']}/releases/latest"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30
        ) as resp:
            latest = json.loads(resp.read())["tag_name"]
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SystemExit(f"Could not query latest upstream release: {exc}")

    if latest == lock["version"]:
        log.info("base already at latest (%s)", latest)
        return False

    log.info("bumping base %s -> %s", lock["version"], latest)
    path = ROOT / "base.lock.json"
    raw = load_json(path)
    raw["version"] = latest
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    lock["version"] = latest
    return True


def wants(entry, profile):
    """True if an overlay entry applies to this profile ('*' means every profile)."""
    profiles = entry.get("profiles", [])
    return "*" in profiles or profile in profiles


def matches(app, spec):
    """True if the app equals the match spec on every field the spec names."""
    return all(app.get(key) == value for key, value in spec.items())


def parse_settings(value):
    """additionalSettings is a JSON-encoded string on the wire, an object when authored."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return json.loads(value)


def clean_app(app):
    """Drop authoring-only keys and serialize additionalSettings the way Obtainium wants."""
    out = {k: v for k, v in app.items() if k in APP_KEYS}
    settings = parse_settings(app.get("additionalSettings"))
    # Underscore-prefixed keys are inline documentation for humans reading overlay.json.
    # "*-creds" holds per-source API tokens; upstream ships them empty, but stripping here
    # means a populated one can never reach dist/ no matter what the base pack contains.
    settings = {
        k: v for k, v in settings.items()
        if not k.startswith("_") and not k.endswith("-creds")
    }
    out["additionalSettings"] = json.dumps(settings, separators=(",", ":"))
    return out


def clean_settings(settings):
    if not isinstance(settings, dict):
        return {}
    return {
        k: v for k, v in settings.items()
        if k in SETTINGS_ALLOWLIST and not k.endswith("-creds")
    }


def build_profile(name, profile, lock, overlay, refresh=False):
    base = get_base_pack(lock, profile["base"], refresh=refresh)
    apps = [dict(a) for a in base.get("apps", [])]
    report = {"base": len(apps), "excluded": [], "overridden": [], "added": []}

    # 1. Excludes, so a later override can never resurrect a removed app.
    for rule in overlay.get("excludes", []):
        if not wants(rule, name):
            continue
        keep, dropped = [], []
        for app in apps:
            (dropped if matches(app, rule["match"]) else keep).append(app)
        if not dropped:
            log.warning("[%s] exclude matched nothing: %s", name, rule["match"])
        for app in dropped:
            report["excluded"].append(app["name"])
        apps = keep

    # 2. Patches against upstream entries.
    for rule in overlay.get("overrides", []):
        if not wants(rule, name):
            continue
        hits = [a for a in apps if matches(a, rule["match"])]
        if not hits:
            log.warning("[%s] override matched nothing: %s", name, rule["match"])
        for app in hits:
            patch = dict(rule.get("patch", {}))
            if "additionalSettings" in patch:
                merged = parse_settings(app.get("additionalSettings"))
                merged.update(parse_settings(patch.pop("additionalSettings")))
                app["additionalSettings"] = merged
            app.update(patch)
            report["overridden"].append(app["name"])

    # 3. Local additions.
    existing = {a["id"] for a in apps}
    for entry in overlay.get("apps", []):
        if not wants(entry, name):
            continue
        app = entry["app"]
        if app["id"] in existing:
            log.warning(
                "[%s] overlay app %r (%s) already in base - skipping; use an override instead",
                name, entry["slug"], app["id"],
            )
            continue
        apps.append(dict(app))
        existing.add(app["id"])
        report["added"].append(app["name"])

    pack = {
        "apps": [clean_app(a) for a in apps],
        "settings": clean_settings(base.get("settings")),
    }
    report["total"] = len(pack["apps"])
    return pack, report


def render(pack):
    return json.dumps(pack, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", help="build only this profile")
    parser.add_argument("--refresh", action="store_true",
                        help="re-download the base pack instead of using .cache/")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if dist/ differs from a fresh build")
    parser.add_argument("--bump-base", action="store_true",
                        help="update base.lock.json to upstream's newest release first")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub token for --bump-base; defaults to $GITHUB_TOKEN")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    lock = load_json(ROOT / "base.lock.json")
    if args.bump_base:
        if args.check:
            raise SystemExit("--bump-base rewrites base.lock.json; incompatible with --check")
        bump_base(lock, args.token)
    overlay = load_json(ROOT / "overlay.json")
    profiles = load_json(ROOT / "profiles.json")["profiles"]

    if args.profile:
        if args.profile not in profiles:
            raise SystemExit(
                f"Unknown profile {args.profile!r}. Known: {sorted(profiles)}"
            )
        profiles = {args.profile: profiles[args.profile]}

    log.info("base %s @ %s", lock["repo"], lock["version"])
    stale = []

    for name, profile in profiles.items():
        pack, report = build_profile(name, profile, lock, overlay, refresh=args.refresh)
        text = render(pack)
        target = DIST / f"{name}.json"

        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != text:
                stale.append(name)
        else:
            DIST.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")

        detail = []
        if report["excluded"]:
            detail.append(f"-{len(report['excluded'])} {report['excluded']}")
        if report["overridden"]:
            detail.append(f"~{len(report['overridden'])} {report['overridden']}")
        if report["added"]:
            detail.append(f"+{len(report['added'])} {report['added']}")
        flag = " [provisional]" if profile.get("provisional") else ""
        log.info(
            "%-6s %-18s %s -> %d apps%s  %s",
            name, profile["device"], profile["base"], report["total"], flag,
            "  ".join(detail),
        )

    if args.check and stale:
        log.error("dist/ is stale for: %s (run build.py)", ", ".join(stale))
        return 1
    if args.check:
        log.info("dist/ is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
