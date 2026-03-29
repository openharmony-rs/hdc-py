from pathlib import Path
import uuid

from hdc_py import HarmonyDeviceConnector, HarmonyDevicePerfMode


REMOTE_TMP_DIR = "/data/local/tmp/hdc-py-tests"


def _device_test_path(name: str) -> str:
    return f"{REMOTE_TMP_DIR}/{uuid.uuid4()}-{name}"


def test_connector_resolves_hdc_binary() -> None:
    hdc = HarmonyDeviceConnector()
    assert hdc.hdc_path.exists()
    assert hdc.hdc_path.name.startswith("hdc")


def test_cmd_echo_roundtrip() -> None:
    hdc = HarmonyDeviceConnector()
    result = hdc.cmd("echo hello-world!", capture_output=True, text=True)
    assert result.stdout.strip() == "hello-world!"


def test_send_and_read_file_roundtrip(tmp_path: Path) -> None:
    hdc = HarmonyDeviceConnector()
    device_path = _device_test_path("roundtrip.txt")
    host_file = tmp_path / "roundtrip.txt"
    expected = "hello from host file transfer\nsecond line\n"
    host_file.write_text(expected, encoding="utf-8")

    hdc.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    hdc.cmd(f"rm -f {device_path}")
    try:
        hdc.send_file(str(host_file), device_path)
        assert hdc.read_file(device_path) == expected
    finally:
        hdc.cmd(f"rm -f {device_path}")


def test_recv_file_downloads_device_contents(tmp_path: Path) -> None:
    hdc = HarmonyDeviceConnector()
    device_path = _device_test_path("recv.txt")
    host_file = tmp_path / "recv.txt"
    expected = "download me from the device\n"

    hdc.cmd(f"mkdir -p {REMOTE_TMP_DIR}")
    hdc.cmd(f"printf '{expected}' > {device_path}")
    try:
        hdc.recv_file(device_path, str(host_file))
        assert host_file.read_text(encoding="utf-8") == expected
    finally:
        hdc.cmd(f"rm -f {device_path}")


def test_read_file_returns_none_for_missing_device_file() -> None:
    hdc = HarmonyDeviceConnector()
    missing_path = _device_test_path("missing.txt")
    hdc.cmd(f"rm -f {missing_path}")
    assert hdc.read_file(missing_path) is None


# This doesn't really assert anything useful, besides the command not crashing.
# investigation needed on how we can "prove" that we entered perf mode.
def test_perf_mode_context_runs_and_restores() -> None:
    hdc = HarmonyDeviceConnector()

    with HarmonyDevicePerfMode(screen_timeout_seconds=60, hdc=hdc):
        result = hdc.cmd("echo perf-mode", capture_output=True, text=True)

    assert result.stdout.strip() == "perf-mode"
