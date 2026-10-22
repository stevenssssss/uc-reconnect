#!/bin/zsh
set -u

BASE_DIR="$HOME/Library/Application Support/UCReconnect"
LOG_DIR="$BASE_DIR/logs"
STATE_FILE="$LOG_DIR/universal-control-link.state"
WATCHDOG_LOG="$LOG_DIR/universal-control-watchdog.log"
LOCK_FILE="$BASE_DIR/watchdog.lock"
PYTHON="$(cat "$BASE_DIR/python-path" 2>/dev/null)"
[[ -x "$PYTHON" ]] || { print -u2 "UC Reconnect Python runtime missing; reinstall."; exit 2; }
config_values="$("$PYTHON" "$BASE_DIR/uc_config.py" "$BASE_DIR/config.json")" || exit 2
TARGET_ID="${config_values%%$'\n'*}"
TARGET_HOST="${config_values#*$'\n'}"
RETRY_SECONDS=1
RECONNECT_APP="$HOME/Applications/UC Reconnect Helper.app"
RECONNECT_RESULT="$LOG_DIR/reconnect-result"

event_state=""
event_pid=""
if [[ "${1:-}" == --event && "${2:-}" == (connected|disconnected) ]] &&
   { (( $# == 2 )) || { (( $# == 3 )) && [[ "$3" == <-> ]]; }; }; then
  event_state="$2"
  event_pid="${3:-}"
elif (( $# != 0 )); then
  exit 2
fi

log_msg() {
  printf "%s %s\n" "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*" >> "$WATCHDOG_LOG"
}

# Idle AWDL diagnostics are not proof that this MacBook disconnected.
latest_connection_state() {
  awk -v target="$TARGET_ID" -v pid="$current_pid" '
    /UniversalControl\[/ && !index($0, "UniversalControl[" pid ":") { next }
    /Connected Devices IDS: \[/ {
      devices=$0
      sub(/^.*Connected Devices IDS: \[/, "", devices)
      sub(/\].*$/, "", devices)
      gsub(/ /, "", devices)
      link=index("," devices ",", "," target ",") ? "connected" : "disconnected"
    }
    /Excluded the following unavailable devices: \[/ {
      devices=$0
      sub(/^.*Excluded the following unavailable devices: \[/, "", devices)
      sub(/\].*$/, "", devices)
      gsub(/ /, "", devices)
      if (index("," devices ",", "," target ",")) link="disconnected"
    }
    index($0, "IDS " target ": Disconnected") ||
    index($0, "Disconnected " target ", update connections:") { link="disconnected" }
    END { if (link != "") print link }
  '
}

mkdir -p "$LOG_DIR"
zmodload zsh/system
zmodload zsh/datetime
worker_started="$EPOCHREALTIME"
: >> "$LOCK_FILE"
lock_wait=0
[[ -n "$event_state" ]] && lock_wait=2
zsystem flock -t "$lock_wait" -f lock_fd "$LOCK_FILE" 2>/dev/null || exit 75

now="$(date +%s)"
last_check=0
connection_state="unknown"
disconnected_since=0
last_restart=0
attempts=0
last_pid=0
if [[ -r "$STATE_FILE" ]]; then
  read -r last_check connection_state disconnected_since last_restart attempts last_pid < "$STATE_FILE"
fi
last_pid="${last_pid:-0}"
current_pid="$(/usr/bin/pgrep -u "$(id -u)" -x UniversalControl | head -n 1)"
current_pid="${current_pid:-0}"
save_state() {
  printf '%s %s %s %s %s %s\n' "$now" "$connection_state" "$disconnected_since" "$last_restart" "$attempts" "$current_pid" > "${STATE_FILE}.$$"
  mv "${STATE_FILE}.$$" "$STATE_FILE"
}
trap 'save_state' EXIT

observed_state=""
if [[ "$current_pid" == 0 ]]; then
  observed_state=disconnected
  /bin/launchctl kickstart "gui/$(id -u)/com.apple.ensemble" 2>> "$LOG_DIR/universal-control-watchdog.stderr.log" || true
elif [[ -n "$event_state" && ( -z "$event_pid" || "$event_pid" == "$current_pid" ) ]]; then
  observed_state="$event_state"
else
  predicate='process == "UniversalControl" AND ((category == "CONN" AND eventMessage CONTAINS "'$TARGET_ID'" AND eventMessage CONTAINS "Disconnected") OR (category == "EVNT" AND eventMessage CONTAINS "Connected Devices IDS:") OR (category == "CIRC" AND eventMessage CONTAINS "Excluded the following unavailable devices:" AND eventMessage CONTAINS "'$TARGET_ID'"))'
  if (( last_check == 0 || last_check > now )); then
    query_time=(--last 12h)
  else
    query_time=(--start "$(date -r $((last_check - 3)) '+%Y-%m-%d %H:%M:%S')")
  fi
  if ! recent_log="$(/usr/bin/log show "${query_time[@]}" --style compact --predicate "$predicate" 2>> "$LOG_DIR/universal-control-watchdog.stderr.log")"; then
    now="$last_check"
    current_pid="$last_pid"
    exit 1
  fi
  observed_state="$(printf '%s\n' "$recent_log" | latest_connection_state)"
  if [[ -z "$observed_state" && "$last_pid" != "$current_pid" ]]; then
    # Never carry a healthy state from a dead UC process into a new generation.
    observed_state=disconnected
  fi
fi
if [[ -n "$observed_state" && "$observed_state" != "$connection_state" ]]; then
  connection_state="$observed_state"
  attempts=0
  if [[ "$connection_state" == "connected" ]]; then
    disconnected_since=0
    log_msg "verified input channel connected: $TARGET_HOST ($TARGET_ID); retries stopped"
  else
    disconnected_since="$now"
    last_restart=0
    log_msg "connection lost: $TARGET_HOST ($TARGET_ID); retries remain active until input channel is ready"
  fi
fi

[[ "$connection_state" == "disconnected" ]] || exit 0
(( now - last_restart >= RETRY_SECONDS )) || exit 0

stop_if_recovered() {
  local live_at live_state live_pid actual_pid
  [[ -r "$LOG_DIR/live-input.state" ]] || return 1
  read -r live_at live_state live_pid < "$LOG_DIR/live-input.state"
  [[ "$live_at" == <->.<-> && "$live_state" == connected && "$live_pid" == <-> ]] || return 1
  (( live_at >= worker_started )) || return 1
  actual_pid="$(/usr/bin/pgrep -u "$(id -u)" -x UniversalControl | head -n 1)"
  [[ "$live_pid" == "$actual_pid" ]] || return 1
  connection_state=connected
  current_pid="$actual_pid"
  disconnected_since=0
  attempts=0
  log_msg "input channel recovered during repair; cancelling stale repair action"
  return 0
}
stop_if_recovered && exit 0

# Native UC discovery remains authoritative even if LAN ping or mDNS fails.

if [[ ! -d "$RECONNECT_APP" ]]; then
  log_msg "reconnect helper missing; no service reset performed"
  exit 1
fi

attempts=$((attempts + 1))
last_restart="$now"
previous_result="$(cat "$RECONNECT_RESULT" 2>/dev/null || true)"
# A checked menu with no input channel is also a failed connection.
# Never reset on UI permission errors or while Settings is in use.
if { (( attempts % 3 == 2 )) && [[ "$previous_result" == (add-menu-not-found|device-menu-not-found|target-not-available|already-selected) ]]; } ||
   { (( attempts % 3 == 0 )) && [[ "$previous_result" == connection-requested ]]; }; then
  stop_if_recovered && exit 0
  log_msg "connection not restored ($previous_result); restarting UniversalControl before retry"
  /usr/bin/killall -KILL UniversalControl 2>> "$LOG_DIR/universal-control-watchdog.stderr.log" || true
  /bin/launchctl kickstart "gui/$(id -u)/com.apple.ensemble" 2>> "$LOG_DIR/universal-control-watchdog.stderr.log" || true
  sleep 2
fi
stop_if_recovered && exit 0
printf '%s helper-open attempt=%s\n' "$EPOCHREALTIME" "$attempts" >> "$LOG_DIR/universal-control-events.log"
log_msg "connection attempt $attempts: requesting the MacBook through the UC menu"
printf 'starting\n' > "$RECONNECT_RESULT"
"$PYTHON" - "$RECONNECT_APP" "$RECONNECT_RESULT" <<'PY' 2>> "$LOG_DIR/universal-control-watchdog.stderr.log"
import re
from pathlib import Path
import subprocess
import sys

app, result = sys.argv[1:]
try:
    outcome = subprocess.run(['/usr/bin/open', '-g', '-W', app], timeout=20)
    if outcome.returncode:
        Path(result).write_text('helper-launch-failed\n')
except subprocess.TimeoutExpired:
    # Match only this helper, never other AppleScript apps or System Settings.
    executable = str(Path(app) / 'Contents/MacOS/applet')
    subprocess.run(['/usr/bin/pkill', '-TERM', '-f', '^' + re.escape(executable) + r'($| )'])
    Path(result).write_text('helper-timeout\n')
PY
helper_result="$(cat "$RECONNECT_RESULT" 2>/dev/null || true)"
log_msg "connection action: $helper_result; success still requires the MacBook in the input channel"
