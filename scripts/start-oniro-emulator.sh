#!/usr/bin/env bash
set -euo pipefail

connect_key="${1:-127.0.0.1:55555}"
pid_file="/tmp/oniro-emulator.pid"

: "${ONIRO_EMULATOR_PATH:?Set ONIRO_EMULATOR_PATH to the extracted Oniro emulator images directory.}"

if [ ! -f "$ONIRO_EMULATOR_PATH/run.sh" ]; then
  echo "Error: expected run.sh at $ONIRO_EMULATOR_PATH/run.sh"
  exit 1
fi

if [ ! -e /dev/kvm ]; then
  echo "Error: /dev/kvm is not available. Enable hardware virtualization and KVM before starting the emulator."
  exit 1
fi

if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
  echo "Error: current user does not have access to /dev/kvm."
  echo "Add your user to the kvm group or otherwise grant read/write access to /dev/kvm, then try again."
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

setsid bash -c 'cd "$1" && exec bash ./run.sh' bash "$ONIRO_EMULATOR_PATH" >/tmp/oniro-emulator.log 2>&1 &
emulator_pid=$!
echo "$emulator_pid" >"$pid_file"

echo "Starting Oniro emulator from $ONIRO_EMULATOR_PATH/run.sh"
echo "Waiting for HDC endpoint at $connect_key..."
for _ in $(seq 1 50); do
  if ! kill -0 "$emulator_pid" >/dev/null 2>&1; then
    echo "Error: emulator process exited before HDC became available."
    echo "Check /tmp/oniro-emulator.log for emulator startup output."
    rm -f "$pid_file"
    exit 1
  fi
  if hdc tconn "$connect_key" >/dev/null 2>&1; then
    echo "Connected to Oniro emulator via HDC."
    exit 0
  fi
  sleep 1
done

echo "Error: failed to connect to the Oniro emulator at $connect_key."
echo "Check /tmp/oniro-emulator.log for emulator startup output."
rm -f "$pid_file"
exit 1
