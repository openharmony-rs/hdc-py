
emulator_connect_key := "127.0.0.1:55555"
device_check_timeout_seconds := "5"

emulator:
  bash scripts/start-oniro-emulator.sh {{emulator_connect_key}}

emulator-stop:
  bash scripts/stop-oniro-emulator.sh

test:
  #!/usr/bin/env bash
  set -euo pipefail

  if ! command -v hdc >/dev/null 2>&1; then
    echo "Error: hdc is not available on PATH."
    exit 1
  fi

  hdc start >/dev/null 2>&1 || true
  if ! timeout {{device_check_timeout_seconds}}s hdc wait >/dev/null 2>&1; then
    echo "Error: no HDC device is connected."
    echo "Connect a device or start the Oniro emulator first with 'just emulator', then rerun 'just test'."
    exit 1
  fi

  PYTHONPATH=src uv run pytest -q

build:
  uv build

format:
  uv run ruff format .
  uv run ruff check --fix .

check-format:
  uv run ruff format --check .
  uv run ruff check .
