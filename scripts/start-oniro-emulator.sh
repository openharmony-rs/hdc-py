#!/usr/bin/env bash
set -euo pipefail

connect_key="${1:-127.0.0.1:55555}"
pid_file="/tmp/oniro-emulator.pid"
connect_file="/tmp/oniro-emulator.connect"
log_file="/tmp/oniro-emulator.log"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
launcher_script="$script_dir/oniro-emulator-run.sh"

: "${ONIRO_EMULATOR_PATH:?Set ONIRO_EMULATOR_PATH to the extracted Oniro emulator images directory.}"

if [ ! -x "$launcher_script" ]; then
  echo "Error: expected executable launcher at $launcher_script"
  exit 1
fi

if ! command -v hdc >/dev/null 2>&1; then
  echo "Error: hdc is not available on PATH."
  exit 1
fi

if [ -f "$pid_file" ]; then
  existing_pid="$(cat "$pid_file")"
  if kill -0 "$existing_pid" >/dev/null 2>&1; then
    echo "Error: Oniro emulator appears to already be running with pid $existing_pid."
    echo "Run 'just emulator-stop' first if you want to restart it."
    exit 1
  fi
  rm -f "$pid_file"
fi

requested_host="${connect_key%:*}"
requested_port="${connect_key##*:}"

if [ -z "$requested_host" ] || [ -z "$requested_port" ] || [[ ! "$requested_port" =~ ^[0-9]+$ ]]; then
  echo "Error: expected connect key in host:port form, got '$connect_key'."
  exit 1
fi

actual_connect_key=""
emulator_pid=""

for port_offset in $(seq 0 9); do
  candidate_port=$((requested_port + port_offset))
  candidate_connect_key="${requested_host}:${candidate_port}"

  rm -f "$log_file"
  bash "$launcher_script" "$ONIRO_EMULATOR_PATH" "$candidate_connect_key" >"$log_file" 2>&1 &
  emulator_pid=$!

  sleep 1
  if kill -0 "$emulator_pid" >/dev/null 2>&1; then
    actual_connect_key="$candidate_connect_key"
    break
  fi

  if grep -Fq "Could not set up host forwarding rule" "$log_file"; then
    if [ "$candidate_port" -eq "$requested_port" ]; then
      echo "Port $candidate_port is unavailable for QEMU host forwarding. Retrying with another port..."
    fi
    continue
  fi

  echo "Error: emulator process exited during startup."
  echo "Check $log_file for emulator startup output."
  exit 1
done

if [ -z "$actual_connect_key" ]; then
  echo "Error: failed to find an available host forwarding port starting at $requested_port."
  echo "Check $log_file for emulator startup output."
  exit 1
fi

echo "$emulator_pid" >"$pid_file"
echo "$actual_connect_key" >"$connect_file"

echo "Starting Oniro emulator from $ONIRO_EMULATOR_PATH"
echo "Waiting for HDC endpoint at $actual_connect_key..."
for _ in $(seq 1 120); do
  if ! kill -0 "$emulator_pid" >/dev/null 2>&1; then
    echo "Error: emulator process exited before HDC became available."
    echo "Check $log_file for emulator startup output."
    rm -f "$pid_file" "$connect_file"
    exit 1
  fi
  tconn_output="$(hdc tconn "$actual_connect_key" 2>&1 || true)"
  if [[ "$tconn_output" == "Connect OK" || "$tconn_output" == *"Target is connected"* ]]; then
    echo "Connected to Oniro emulator via HDC at $actual_connect_key."
    exit 0
  fi
  sleep 1
done

echo "Error: failed to connect to the Oniro emulator at $actual_connect_key."
echo "Check $log_file for emulator startup output."
rm -f "$pid_file" "$connect_file"
exit 1
