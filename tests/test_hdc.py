import os
from pathlib import Path
import shlex
import subprocess
import uuid

import pytest

from hdc_py import (
    Hdc,
    HdcAmbiguousTargetError,
    HdcDisconnectedError,
    HdcTargetNotFoundError,
    HarmonyDevice,
    HarmonyDeviceConnector,
    HarmonyDevicePerfMode,
)


REMOTE_TMP_DIR = "/data/local/tmp/hdc-py-tests"


def _device_test_path(name: str) -> str:
    return f"{REMOTE_TMP_DIR}/{uuid.uuid4()}-{name}"


def _device_file_mtime(device: HarmonyDevice, device_path: str) -> int:
    result = device.cmd(f"stat -c %Y {shlex.quote(device_path)}", capture_output=True, text=True)
    return int(result.stdout.strip())


def _connected_device() -> HarmonyDevice:
    hdc = Hdc()
    targets = hdc.list_targets()
    assert targets
    return hdc.connect(target=targets[0])


def test_hdc_resolves_hdc_binary() -> None:
    hdc = Hdc()
    assert hdc.hdc_path.exists()
    assert hdc.hdc_path.name.startswith("hdc")


def test_hdc_lists_connected_targets() -> None:
    hdc = Hdc()
    assert hdc.list_targets()


def test_hdc_connect_requires_explicit_target_when_multiple_are_connected() -> None:
    hdc = Hdc()
    targets = hdc.list_targets()
    assert targets

    if len(targets) == 1:
        device = hdc.connect()
        assert device.target == targets[0]
    else:
        with pytest.raises(HdcAmbiguousTargetError):
            hdc.connect()


def test_hdc_connect_accepts_explicit_target() -> None:
    hdc = Hdc()
    target = hdc.list_targets()[0]
    device = hdc.connect(target=target)
    assert device.target == target


def test_hdc_connect_raises_for_unknown_target() -> None:
    hdc = Hdc()
    with pytest.raises(HdcTargetNotFoundError):
        hdc.connect(target="definitely-not-a-connected-target")


def test_harmony_device_connector_compatibility_wrapper_accepts_target() -> None:
    target = Hdc().list_targets()[0]
    device = HarmonyDeviceConnector(target=target)
    assert device.target == target


def test_device_cmd_echo_roundtrip() -> None:
    device = _connected_device()
    result = device.cmd("echo hello-world!", capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "hello-world!"


def test_device_cmd_returns_real_exit_code_when_check_is_disabled() -> None:
    device = _connected_device()
    result = device.cmd("echo failing-command; exit 23", capture_output=True, text=True, check=False)
    assert result.returncode == 23
    assert result.stdout.strip() == "failing-command"


def test_device_cmd_raises_called_process_error_with_real_exit_code() -> None:
    device = _connected_device()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        device.cmd("echo failing-command; exit 17", capture_output=True, text=True)
    assert exc_info.value.returncode == 17
    assert exc_info.value.output.strip() == "failing-command"


def test_device_cmd_raises_for_disconnected_target() -> None:
    device = HarmonyDevice(Hdc(), "definitely-not-a-connected-target")
    with pytest.raises(HdcDisconnectedError):
        device.cmd("echo should-not-run", capture_output=True, text=True, check=False)


def test_send_and_read_file_roundtrip(tmp_path: Path) -> None:
    device = _connected_device()
    device_path = _device_test_path("roundtrip.txt")
    host_file = tmp_path / "roundtrip.txt"
    expected = "hello from host file transfer\nsecond line\n"
    host_file.write_text(expected, encoding="utf-8")

    device.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    device.cmd(f"rm -f {device_path}")
    try:
        device.send_file(str(host_file), device_path)
        assert device.read_file(device_path) == expected
    finally:
        device.cmd(f"rm -f {device_path}")


def test_recv_file_downloads_device_contents(tmp_path: Path) -> None:
    device = _connected_device()
    device_path = _device_test_path("recv.txt")
    host_file = tmp_path / "recv.txt"
    expected = "download me from the device\n"

    device.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    device.cmd(f"printf '{expected}' > {device_path}")
    try:
        device.recv_file(device_path, str(host_file))
        assert host_file.read_text(encoding="utf-8") == expected
    finally:
        device.cmd(f"rm -f {device_path}")


def test_send_file_skips_transfer_when_hash_matches(tmp_path: Path) -> None:
    device = _connected_device()
    device_path = _device_test_path("send-skip.txt")
    host_file = tmp_path / "send-skip.txt"
    expected = "same content on host and device\n"
    host_file.write_text(expected, encoding="utf-8")
    os.utime(host_file, None)

    device.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    device.cmd(f"printf '{expected}' > {shlex.quote(device_path)}")
    device.cmd(f"touch -t 200001010101.01 {shlex.quote(device_path)}")
    try:
        mtime_before = _device_file_mtime(device, device_path)
        device.send_file(str(host_file), device_path)
        assert _device_file_mtime(device, device_path) == mtime_before
        assert device.read_file(device_path) == expected
    finally:
        device.cmd(f"rm -f {shlex.quote(device_path)}")


def test_recv_file_skips_transfer_when_hash_matches(tmp_path: Path) -> None:
    device = _connected_device()
    device_path = _device_test_path("recv-skip.txt")
    host_file = tmp_path / "recv-skip.txt"
    expected = "same content on device and host\n"
    host_file.write_text(expected, encoding="utf-8")
    os.utime(host_file, (946688461, 946688461))

    device.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    device.cmd(f"printf '{expected}' > {shlex.quote(device_path)}")
    try:
        mtime_before = int(host_file.stat().st_mtime)
        device.recv_file(device_path, str(host_file))
        assert int(host_file.stat().st_mtime) == mtime_before
        assert host_file.read_text(encoding="utf-8") == expected
    finally:
        device.cmd(f"rm -f {shlex.quote(device_path)}")


def test_read_file_returns_none_for_missing_device_file() -> None:
    device = _connected_device()
    missing_path = _device_test_path("missing.txt")
    device.cmd(f"rm -f {missing_path}")
    assert device.read_file(missing_path) is None


def test_perf_mode_context_runs_and_restores() -> None:
    device = _connected_device()

    with HarmonyDevicePerfMode(screen_timeout_seconds=60, hdc=device):
        result = device.cmd("echo perf-mode", capture_output=True, text=True)

    assert result.stdout.strip() == "perf-mode"
