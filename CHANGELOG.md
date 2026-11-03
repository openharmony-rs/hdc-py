# Changelog

## 0.2.1

- Add `HarmonyDevice.cmd_without_exit_code()`. It runs a shell command with a single hdc call and returns a
  `SentCommand` with the output. It tells you that the command was delivered, not whether it succeeded; use
  `cmd()` when you need the exit code.
- `Hdc.list_targets()` no longer returns hdc's `[Empty]` placeholder, so `Hdc.connect()` raises
  `HdcTargetNotFoundError` when no device is connected.

## 0.2.0

- `Hdc` holds the global operations, and `Hdc.connect(target)` returns a `HarmonyDevice` whose commands
  run on that target. `HarmonyDeviceConnector` remains as a compatibility wrapper.
- `cmd()` reports the command's exit code on the device and, unless you pass `check=False`, raises
  `CalledProcessError` when it isn't 0. Before, a failing command went unnoticed.
- `send_file()` and `recv_file()` verify the transfer with SHA-256, and skip it when the file is already
  up to date.
- Add port forwarding (`forward_port()`, `reverse_port()`, `list_port_forwards()`, `remove_port_forward()`)
  and `mount_system_as_rw()`.
- Messages about running commands go to stderr.
