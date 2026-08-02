#!/usr/bin/env python3
"""Validate built Obtainium packs before they ever touch a handheld.

Structural checks run offline on every app. Live checks resolve GitHub releases and
confirm the release actually carries an APK the app's filter will match.

Because the GitHub REST API allows only 60 unauthenticated requests/hour and a pack holds
~60 apps, live checks default to the locally-authored apps only. Use --scope all with a
token to sweep the whole pack:

    python validate.py                          # structure everywhere + live check the overlay
    python validate.py --scope all              # live check every app (needs a token)
    GITHUB_TOKEN=ghp_... python validate.py --scope all
    python validate.py --profile thor --scope none
"""

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

REQUIRED_KEYS = ("id", "url", "author", "name")
REGEX_SETTINGS = (
    "apkFilterRegEx", "versionExtractionRegEx", "filterReleaseTitlesByRegEx",
    "filterReleaseNotesByRegEx", "customLinkFilterRegex", "intermediateLinkRegex",
)
USER_AGENT = "NASUtils-obtainium-config/1.0"

# Obtainium's autoApkFilterByArch (default on) picks the right ABI at install time, so an
# arch-split release is not ambiguous even though it carries several APKs. Only warn about
# multiple APKs when they differ by something Obtainium cannot resolve for us - build flavours
# like root/nonRoot, mainline/fork, or vendor variants.
ARCH_TOKENS = (
    "arm64-v8a", "armeabi-v7a", "x86_64", "x86", "arm64", "arm32", "armv7", "aarch64", "universal",
)

log = logging.getLogger("validate")


class Findings:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, profile, app, message):
        self.errors.append((profile, app, message))
        log.error("[%s] %s: %s", profile, app, message)

    def warn(self, profile, app, message):
        self.warnings.append((profile, app, message))
        log.warning("[%s] %s: %s", profile, app, message)


def api_get(url, token=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()), resp.headers


def arch_split(apks):
    """True if these APKs look like one build published per ABI."""
    tagged = {
        token for name in apks for token in ARCH_TOKENS if token in name.lower()
    }
    return len(tagged) >= 2


def parse_github(url):
    """Return (owner, repo) for a github.com project URL, else None."""
    parts = urllib.parse.urlparse(url)
    if parts.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        return None
    return segments[0], segments[1].removesuffix(".git")


def check_structure(profile, apps, findings):
    seen = {}
    for app in apps:
        name = app.get("name", "<unnamed>")

        for key in REQUIRED_KEYS:
            if not app.get(key):
                findings.error(profile, name, f"missing required key {key!r}")

        app_id = app.get("id")
        if app_id in seen:
            findings.warn(
                profile, name,
                f"duplicate id {app_id!r} (also {seen[app_id]!r}); the later entry wins on import",
            )
        else:
            seen[app_id] = name

        raw = app.get("additionalSettings")
        if not isinstance(raw, str):
            findings.error(
                profile, name,
                f"additionalSettings must be a JSON-encoded string, got {type(raw).__name__}",
            )
            continue
        try:
            settings = json.loads(raw)
        except json.JSONDecodeError as exc:
            findings.error(profile, name, f"additionalSettings is not valid JSON: {exc}")
            continue
        if not isinstance(settings, dict):
            findings.error(profile, name, "additionalSettings must decode to an object")
            continue

        for key in REGEX_SETTINGS:
            pattern = settings.get(key)
            if isinstance(pattern, str) and pattern:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    findings.error(profile, name, f"{key} is not a valid regex: {exc}")

        # build.py strips these entirely; a populated one surviving means a secret leaked.
        leaked = [k for k, v in settings.items() if k.endswith("-creds") and v]
        if leaked:
            findings.error(
                profile, name,
                f"additionalSettings carries a populated credential key {leaked} - do not commit",
            )


def check_release(profile, app, findings, token=None):
    """Resolve a GitHub app's latest release and confirm a matching APK exists."""
    name = app.get("name", "<unnamed>")
    repo = parse_github(app["url"])
    if repo is None:
        return "skipped"

    owner, project = repo
    try:
        releases, headers = api_get(
            f"https://api.github.com/repos/{owner}/{project}/releases?per_page=10", token
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 403 and "rate limit" in str(exc.headers.get("x-ratelimit-remaining", "")):
            findings.warn(profile, name, "GitHub rate limit hit - set GITHUB_TOKEN")
            return "ratelimited"
        if exc.code == 404:
            findings.error(profile, name, f"repo not found: {owner}/{project}")
            return "failed"
        findings.warn(profile, name, f"GitHub API {exc.code} for {owner}/{project}")
        return "failed"
    except urllib.error.URLError as exc:
        findings.warn(profile, name, f"network error: {exc.reason}")
        return "failed"

    remaining = headers.get("x-ratelimit-remaining")
    if remaining is not None and int(remaining) < 5:
        log.warning("GitHub rate limit nearly exhausted (%s left)", remaining)

    settings = json.loads(app.get("additionalSettings") or "{}")
    if settings.get("trackOnly"):
        return "trackonly"

    # Mirror Obtainium's release selection (lib/app_sources/github.dart): drop prereleases and
    # drafts, then apply the title filter (inclusion, matched against the release name and
    # falling back to the tag) and the release-notes filter, and take the first survivor.
    include_pre = bool(settings.get("includePrereleases"))
    title_filter = settings.get("filterReleaseTitlesByRegEx") or None
    notes_filter = settings.get("filterReleaseNotesByRegEx") or None

    candidates = []
    for release in releases:
        if release.get("draft"):
            continue
        if release.get("prerelease") and not include_pre:
            continue
        title = (release.get("name") or release.get("tag_name") or "").strip()
        if title_filter and not re.search(title_filter, title):
            continue
        if notes_filter and not re.search(notes_filter, (release.get("body") or "").strip()):
            continue
        candidates.append(release)

    if not candidates:
        if not releases:
            findings.error(profile, name, f"{owner}/{project} has no releases")
        elif title_filter or notes_filter:
            findings.error(
                profile, name,
                "no release in the latest 10 passes the configured title/notes filter",
            )
        else:
            findings.error(
                profile, name,
                "only prereleases exist but includePrereleases is off - no update will ever resolve",
            )
        return "failed"

    release = candidates[0]
    assets = [a["name"] for a in release.get("assets", [])]
    apks = [a for a in assets if a.lower().endswith(".apk")]
    if not apks:
        findings.error(
            profile, name,
            f"release {release['tag_name']} has no .apk asset (assets: {assets or 'none'})",
        )
        return "failed"

    auto_arch = settings.get("autoApkFilterByArch", True)
    pattern = settings.get("apkFilterRegEx")
    if pattern:
        try:
            matcher = re.compile(pattern)
        except re.error:
            return "failed"  # already reported by check_structure
        matched = [a for a in apks if matcher.search(a)]
        inverted = bool(settings.get("invertAPKFilter"))
        if inverted:
            matched = [a for a in apks if not matcher.search(a)]
        if not matched:
            findings.error(
                profile, name,
                f"apkFilterRegEx {pattern!r} matches none of {apks} in {release['tag_name']}",
            )
            return "failed"
        if len(matched) > 1 and not auto_arch and app.get("preferredApkIndex", 0) == 0:
            findings.warn(
                profile, name,
                f"apkFilterRegEx matches {len(matched)} assets {matched}; index 0 wins",
            )
        elif len(matched) > 1 and auto_arch and not arch_split(matched):
            findings.warn(
                profile, name,
                f"apkFilterRegEx matches {len(matched)} non-arch variants {matched}; index 0 wins",
            )
    elif len(apks) > 1 and not (auto_arch and arch_split(apks)) \
            and app.get("preferredApkIndex", 0) == 0:
        findings.warn(
            profile, name,
            f"{len(apks)} APK variants and no apkFilterRegEx {apks}; index 0 wins",
        )

    log.debug("[%s] %s -> %s ok", profile, name, release["tag_name"])
    return "ok"


def overlay_ids(overlay):
    ids = {entry["app"]["id"] for entry in overlay.get("apps", [])}
    for rule in overlay.get("overrides", []):
        match_id = rule.get("match", {}).get("id")
        if match_id:
            ids.add(match_id)
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", help="validate only this profile")
    parser.add_argument("--scope", choices=("none", "overlay", "all"), default="overlay",
                        help="how much to live-check against GitHub (default: overlay)")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                        help="GitHub token; defaults to $GITHUB_TOKEN")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not DIST.exists():
        raise SystemExit("dist/ not found - run build.py first")

    overlay = json.loads((ROOT / "overlay.json").read_text(encoding="utf-8"))
    local_ids = overlay_ids(overlay)

    packs = sorted(DIST.glob("*.json"))
    if args.profile:
        packs = [p for p in packs if p.stem == args.profile]
        if not packs:
            raise SystemExit(f"No built pack for profile {args.profile!r}")

    if args.scope == "all" and not args.token:
        log.warning(
            "--scope all without a token will exhaust GitHub's 60/hour limit; "
            "set GITHUB_TOKEN for a clean run"
        )

    findings = Findings()
    for pack_path in packs:
        profile = pack_path.stem
        apps = json.loads(pack_path.read_text(encoding="utf-8"))["apps"]
        check_structure(profile, apps, findings)

        if args.scope == "none":
            continue
        targets = apps if args.scope == "all" else [a for a in apps if a["id"] in local_ids]
        checked = sum(1 for a in targets if check_release(profile, a, findings, args.token) == "ok")
        log.info("%-6s %d apps, live-checked %d/%d ok", profile, len(apps), checked, len(targets))

    print()
    if findings.errors:
        print(f"FAIL  {len(findings.errors)} error(s), {len(findings.warnings)} warning(s)")
        return 1
    print(f"OK    0 errors, {len(findings.warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
