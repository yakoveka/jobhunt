#!/bin/zsh
# Daily job hunt: fetch → headless Claude (/jobs daily, + /jobs weekly on Mondays) → render PDFs → dashboard → notify.
# Launched by launchd via install.sh (daily; launchd runs it on wake if the Mac was asleep, and at login).
# Idempotent per day: exits if today's digest already exists.
# Manual run: ~/.claude/skills/jobs/run-daily.sh [--force]
set -u

HERE="${0:A:h}"
STATE="$HOME/.local/state/jobhunt"
CONFIG="${JOBHUNT_CONFIG:-$HOME/.config/jobhunt/config.toml}"
TODAY=$(date +%F)
LOG="$STATE/logs/$TODAY.log"
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$STATE/logs"
exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T') start (pid $$)"

notify() { /usr/bin/osascript -e "display notification \"$1\" with title \"Job hunt\"" || true; }
fail() { echo "$1"; notify "$1"; exit 1; }

# Python ≥ 3.11 (tomllib). macOS's /usr/bin/python3 is older, so prefer mise, then whatever is on PATH.
PY=""
for cand in "$(mise which python3 2>/dev/null)" "$(command -v python3)"; do
  [[ -n "$cand" ]] && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && { PY="$cand"; break; }
done
[[ -n "$PY" ]] || fail "Python 3.11+ not found, see SETUP.md"
CLAUDE=$(command -v claude) || fail "claude CLI not found, see SETUP.md"

WHERE=$("$PY" -B "$HERE/jobhunt.py" where) || fail "config problem, see $LOG"
DIRS=("${(@f)WHERE}")
HUNT="$DIRS[1]"
mkdir -p "$HUNT/daily" "$HUNT/applications" "$HUNT/market"

if [[ "${1:-}" != "--force" && -e "$HUNT/daily/$TODAY.md" ]]; then
  echo "digest for $TODAY exists, nothing to do"; exit 0
fi

# One run at a time (launchd can fire on wake and at login close together).
LOCK="$STATE/run.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [[ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]]; then rm -rf "$LOCK"; mkdir "$LOCK"
  else echo "another run holds $LOCK"; exit 0; fi
fi
trap 'rm -rf "$LOCK"' EXIT

# After wake the network can take a while.
for i in {1..10}; do /sbin/ping -c1 -t5 1.1.1.1 >/dev/null 2>&1 && break; echo "waiting for network ($i)"; sleep 30; done

if [[ ! -s "$STATE/new/$TODAY.tsv" || "${1:-}" == "--force" ]]; then
  "$PY" -B "$HERE/jobhunt.py" fetch --state "$STATE" || fail "fetch failed, see $LOG"
fi

# Headless Claude may only read the hunt dir (cwd) and the dirs added here: state, config, profile dirs outside it.
ADD=(--add-dir "$STATE" --add-dir "${CONFIG:h}")
for d in "${(@)DIRS[2,-1]}"; do ADD+=(--add-dir "$d"); done

run_claude() {  # $1 = slash command
  ( cd "$HUNT" && "$CLAUDE" -p "$1" --model opus --effort high --permission-mode acceptEdits \
      --allowedTools "Read Write Edit Glob Grep WebFetch WebSearch" --disallowedTools "Bash" \
      "${ADD[@]}" --name "jobs-${1#/jobs }-$TODAY" )
}

OUT=$(run_claude "/jobs daily"); RC=$?
print -r -- "$OUT"
[[ $RC -eq 0 ]] || fail "daily run failed (rc $RC), see $LOG"
if [[ $(date +%u) == 1 ]]; then
  run_claude "/jobs weekly" || notify "weekly review failed, see $LOG"
fi

"$PY" -B "$HERE/jobhunt.py" render || notify "PDF render failed, see $LOG"
"$PY" -B "$HERE/jobhunt.py" dashboard || notify "dashboard failed, see $LOG"

SUMMARY=$(print -r -- "$OUT" | grep -E '^JOBS:' | tail -1)
notify "${SUMMARY:-daily run finished} · open daily/$TODAY.md"
echo "=== $(date '+%F %T') done"
