#!/bin/bash
# Prolonged playlist download: a LaunchAgent runs one small batch every few hours until the playlist is complete.
# Usage: prolonged.sh {install|uninstall|status|missing|check|run [--force]} <job>   (job = jobs/<job>.conf)
# Progress comes from the output folder (files "NNN. title [id].mkv"); no state file besides status/<job>.json.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/.."
DATA="$HOME/.local/share/nasutils/ytdl"      # bin/ (Release build), logs/<job>/, status/<job>.json, locks/
BIN="$DATA/bin/YoutubeDownloader.dll"
LAUNCHER="$DATA/bin/ytdl-launcher"           # the one binary that gets Full Disk Access (see README)
export PATH="$HOME/.pyenv/shims:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"   # launchd's PATH is minimal

cmd="${1:-}"; job="${2:-}"; force="${3:-}"
[ -n "$cmd" ] && [ -n "$job" ] || { sed -n '2,4p' "$0"; exit 1; }
CONF="$HERE/jobs/$job.conf"
[ -f "$CONF" ] || { echo "no config: $CONF"; exit 1; }
LABEL="com.abbabon.nasutils.ytdl.$job"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BATCH=20 DELAY=100 INTERVAL_HOURS=4 MAX_BOT_FAILURES=3
. "$CONF"
COOKIES="${COOKIES/#\~/$HOME}"; OUTPUT="${OUTPUT%/}"
PLID="$(echo "$URL" | sed -n 's/.*[?&]list=\([^&]*\).*/\1/p')"
STATUS="$DATA/status/$job.json"
LOGDIR="$DATA/logs/$job"

# load_missing: sets TOTAL and M (newline-separated missing indices)
load_missing() { local o; o=$(compute_missing) || return 1; TOTAL=$(echo "$o" | head -1); M=$(echo "$o" | tail -n +2); }

# tmo SECS cmd...: a TCC-denied SMB access can hang forever instead of erroring, so bound every touch of OUTPUT
tmo() { perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$@"; }
log() { echo "$(date '+%F %T') $*"; }

# prints playlist length, then missing indices one per line (needs network)
compute_missing() {
  local ck=(--no-warnings); [ -f "$COOKIES" ] && ck=(--cookies "$COOKIES")
  local TOTAL; TOTAL=$(yt-dlp "${ck[@]}" --flat-playlist --print id "$URL" 2>/dev/null | wc -l | tr -d ' ')
  [ "$TOTAL" -gt 0 ] || return 1
  echo "$TOTAL"
  # present = leading number of "NNN. *.mkv" in OUTPUT and OUTPUT/PLID
  local present; present=$( { tmo 30 ls "$OUTPUT" || return 1; tmo 30 ls "$OUTPUT/$PLID" 2>/dev/null; } | sed -n 's/^\([0-9][0-9]*\)\. .*\.mkv$/\1/p' | sed 's/^0*//')
  echo "$present" | awk -v n="$TOTAL" '{h[$1]=1} END{for(i=1;i<=n;i++) if(!(i in h)) print i}'
}

write_status() { # result done failed missing
  [ "${PROBE:-}" = 1 ] && { log "result=$1 (probe, status not written)"; return; }
  mkdir -p "$(dirname "$STATUS")"
  printf '{"job":"%s","last_run":"%s","last_run_epoch":%s,"result":"%s","done":%s,"failed":%s,"missing":%s,"total":%s}\n' \
    "$job" "$(date '+%FT%T%z')" "$(date +%s)" "$1" "${2:-0}" "${3:-0}" "${4:--1}" "${TOTAL:-0}" > "$STATUS"
  log "result=$1 done=${2:-0} failed=${3:-0} missing=${4:--1}"
}

fail() { log "ERROR: $2"; write_status "$1" 0 0 -1; return 1; }

# guard: fail closed unless OUTPUT is listable and writable and the missing count is plausible.
# Sets TOTAL, M, n. On failure writes status and returns 1 (caller must not download).
guard() {
  [ -d "$OUTPUT" ] || { fail not-mounted "output not available (NAS not mounted?): $OUTPUT"; return 1; }
  local e t="$OUTPUT/.ytdl-probe.$$"
  e=$(tmo 30 ls "$OUTPUT" 2>&1 >/dev/null) || { fail no-access "cannot list $OUTPUT (${e:-timed out}). Grant Full Disk Access to $LAUNCHER"; return 1; }
  e=$(tmo 30 touch "$t" 2>&1) || { fail no-access "cannot write to $OUTPUT (${e:-timed out}). Grant Full Disk Access to $LAUNCHER"; return 1; }
  rm -f "$t"
  load_missing || { fail error "could not read playlist or output dir"; return 1; }
  n=$(echo "$M" | grep -c .)
  local prev; prev=$(sed -n 's/.*"missing":\([0-9]*\).*/\1/p' "$STATUS" 2>/dev/null)
  if [ -n "$prev" ] && [ "$n" -gt $((prev + 5)) ]; then   # +5: playlist may grow
    fail error "missing=$n jumped from last status ($prev); output dir listing looks wrong. Aborting. If legit, delete $STATUS"; return 1
  fi
  log "access ok: $OUTPUT listable+writable, total=$TOTAL missing=$n"
}

case "$cmd" in
probe) PROBE=1; guard && echo "RESULT ok" || echo "RESULT failed" ;;   # runs under launchd via check

check) # read-only: run the probe through the launcher as a one-off launchd job
  mkdir -p "$LOGDIR"; out="$LOGDIR/check.out"; : > "$out"; l="$LABEL.check"
  launchctl remove "$l" 2>/dev/null
  launchctl submit -l "$l" -o "$out" -e "$out" -- "$LAUNCHER" probe "$job" || exit 1
  for _ in $(seq 120); do grep -q '^RESULT ' "$out" && break; sleep 1; done
  launchctl remove "$l" 2>/dev/null; cat "$out"
  grep -q '^RESULT ok' "$out" ;;

missing)
  load_missing || { echo "could not read playlist"; exit 1; }
  echo "total=$TOTAL missing=$(echo "$M" | grep -c .)"; echo "$M" | paste -sd, - ;;

install)
  mkdir -p "$DATA" "$LOGDIR" "$(dirname "$PLIST")"
  dotnet build "$SRC/YoutubeDownloader.csproj" -c Release -o "$DATA/bin" -v q --nologo | tail -3
  # build launcher; only replace if changed so an existing Full Disk Access grant stays valid
  cc -O1 -DSCRIPT="\"$HERE/prolonged.sh\"" -o "$LAUNCHER.new" "$HERE/launcher.c" || exit 1
  cmp -s "$LAUNCHER.new" "$LAUNCHER" && rm "$LAUNCHER.new" || mv "$LAUNCHER.new" "$LAUNCHER"
  echo "launcher: $LAUNCHER  (grant Full Disk Access to exactly this path)"
  "$0" check "$job" || { echo "access check failed; NOT scheduling. Fix access, then re-run install."; exit 1; }
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$LAUNCHER</string><string>run</string><string>$job</string></array>
  <key>StartInterval</key><integer>$((INTERVAL_HOURS * 3600))</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOGDIR/launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGDIR/launchd.log</string>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "installed $LABEL (every ${INTERVAL_HOURS}h)" ;;

uninstall)
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; rm -f "$PLIST"; echo "removed $LABEL" ;;

status)
  launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E 'state =|runs =|last exit' || echo "not loaded"
  cat "$STATUS" 2>/dev/null || echo "no status yet"; ls -t "$LOGDIR"/run-*.log 2>/dev/null | head -1 ;;

run)
  mkdir -p "$DATA/locks" "$LOGDIR"
  LOCK="$DATA/locks/$job.lock"
  if ! mkdir "$LOCK" 2>/dev/null; then
    kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null && { echo "already running"; exit 0; }
    rm -rf "$LOCK"; mkdir "$LOCK" || exit 1   # stale lock from a dead run
  fi
  echo $$ > "$LOCK/pid"; trap 'rm -rf "$LOCK"' EXIT
  LOG="$LOGDIR/run-$(date +%Y%m%d-%H%M%S).log"
  exec > >(tee -a "$LOG") 2>&1
  ls -t "$LOGDIR"/run-*.log 2>/dev/null | tail -n +61 | xargs rm -f   # keep the last 60 logs

  [ -f "$COOKIES" ] || { log "waiting for cookies: $COOKIES not found"; write_status waiting-cookies; exit 0; }
  last=$(sed -n 's/.*"last_run_epoch":\([0-9]*\).*/\1/p' "$STATUS" 2>/dev/null)
  if [ "$force" != "--force" ] && [ -n "$last" ] && [ $(( $(date +%s) - last )) -lt $((INTERVAL_HOURS * 3600 - 600)) ] \
     && grep -q '"result":"\(ok\|blocked\|error\)"' "$STATUS"; then
    log "too soon since last run, skipping (RunAtLoad/wake); use run <job> --force"; exit 0
  fi

  guard || exit 0
  if [ "$n" -eq 0 ]; then
    log "complete: all $TOTAL items present"; write_status complete 0 0 0
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; exit 0
  fi
  items=$(echo "$M" | head -n "$BATCH" | paste -sd, -)
  log "missing=$n total=$TOTAL, this batch: $items"

  mkdir -p "$OUTPUT/$PLID"
  dotnet "$BIN" "$URL" "$OUTPUT" --items "$items" --cookies "$COOKIES" --delay "$DELAY" --max-consecutive-failures "$MAX_BOT_FAILURES"
  rc=$?
  # flatten new files into the output root, skipping name clashes
  for f in "$OUTPUT/$PLID"/*.mkv; do
    [ -e "$f" ] || continue
    [ -e "$OUTPUT/$(basename "$f")" ] && { log "clash, left in place: $(basename "$f")"; continue; }
    mv "$f" "$OUTPUT/"
  done
  rmdir "$OUTPUT/$PLID" 2>/dev/null
  if load_missing; then after=$(echo "$M" | grep -c .); else after=$n; fi
  done_n=$((n - after)); failed=$(echo "$items" | tr , '\n' | grep -c .); failed=$((failed - done_n)); [ "$failed" -lt 0 ] && failed=0
  res=ok; [ $rc -eq 2 ] && res=blocked; [ $rc -ne 0 ] && [ $rc -ne 2 ] && res=error
  write_status "$res" "$done_n" "$failed" "$after" ;;

*) sed -n '2,4p' "$0"; exit 1 ;;
esac
