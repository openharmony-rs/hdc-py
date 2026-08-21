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
    PortForward,
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


def _random_tcp_node() -> str:
    return f"tcp:{43000 + uuid.uuid4().int % 10000}"


# _fake_device is a last resort to mock `hdc` output for error cases that are hard to trigger.
# We should always prefer using real hdc commands to test behavior.
def _fake_device(
    tmp_path: Path,
    command_handler: str,
    target: str = "fake-target",
    list_targets_output: str | None = None,
) -> HarmonyDevice:
    if list_targets_output is None:
        list_targets_output = target
    fake_hdc = tmp_path / "fake-hdc"
    fake_hdc.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                'if [ "$1" = "list" ] && [ "$2" = "targets" ]; then',
                f"  printf '%s\\n' '{list_targets_output}'",
                "  exit 0",
                "fi",
                f'if [ "$1" = "-t" ] && [ "$2" = "{target}" ]; then',
                "  shift 2",
                command_handler,
                "fi",
                "printf 'unexpected args: %s\\n' \"$*\" >&2",
                "exit 64",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_hdc.chmod(0o755)
    return HarmonyDevice(Hdc(hdc_path=fake_hdc), target)


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


def test_list_targets_treats_empty_marker_as_no_devices(tmp_path: Path) -> None:
    device = _fake_device(tmp_path, "exit 0", list_targets_output="[Empty]")
    assert device.hdc.list_targets() == []
    with pytest.raises(HdcTargetNotFoundError, match="No connected hdc devices were found"):
        device.hdc.connect()


def test_list_targets_keeps_connected_fake_target(tmp_path: Path) -> None:
    device = _fake_device(tmp_path, "exit 0")
    assert device.hdc.list_targets() == ["fake-target"]
    connected = device.hdc.connect()
    assert connected.target == "fake-target"


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


def test_forward_port_can_be_listed_and_removed() -> None:
    device = _connected_device()
    local_node = _random_tcp_node()
    remote_node = _random_tcp_node()
    port_forward = device.forward_port(local_node, remote_node)
    try:
        listed = [
            rule
            for rule in device.list_port_forwards()
            if rule.target == device.target
            and rule.direction == "Forward"
            and rule.local_node == local_node
            and rule.remote_node == remote_node
        ]
        assert listed
    finally:
        removal = device.remove_port_forward(port_forward)
        assert removal.success is True

    listed = [
        rule
        for rule in device.list_port_forwards()
        if rule.target == device.target
        and rule.direction == "Forward"
        and rule.local_node == local_node
        and rule.remote_node == remote_node
    ]
    assert not listed


def test_reverse_port_can_be_listed_and_removed() -> None:
    device = _connected_device()
    remote_node = _random_tcp_node()
    local_node = _random_tcp_node()
    port_forward = device.reverse_port(remote_node, local_node)
    try:
        listed = [
            rule
            for rule in device.list_port_forwards()
            if rule.target == device.target
            and rule.direction == "Reverse"
            and rule.local_node == local_node
            and rule.remote_node == remote_node
        ]
        assert listed
    finally:
        removal = device.remove_port_forward(port_forward)
        assert removal.success is True

    listed = [
        rule
        for rule in device.list_port_forwards()
        if rule.target == device.target
        and rule.direction == "Reverse"
        and rule.local_node == local_node
        and rule.remote_node == remote_node
    ]
    assert not listed


def test_remove_port_forward_reports_missing_rule() -> None:
    device = _connected_device()
    removal = device.remove_port_forward(_random_tcp_node(), _random_tcp_node())
    assert removal.success is False
    assert removal.not_found is True


def test_forward_port_is_idempotent_for_existing_matching_rule() -> None:
    device = _connected_device()
    local_node = _random_tcp_node()
    remote_node = _random_tcp_node()
    port_forward = device.forward_port(local_node, remote_node)
    try:
        repeated = device.forward_port(local_node, remote_node)
        assert repeated == port_forward
        listed = [
            rule
            for rule in device.list_port_forwards()
            if rule.target == device.target
            and rule.direction == "Forward"
            and rule.local_node == local_node
            and rule.remote_node == remote_node
        ]
        assert len(listed) == 1
    finally:
        removal = device.remove_port_forward(port_forward)
        assert removal.success is True


def test_reverse_port_is_idempotent_for_existing_matching_rule() -> None:
    device = _connected_device()
    remote_node = _random_tcp_node()
    local_node = _random_tcp_node()
    port_forward = device.reverse_port(remote_node, local_node)
    try:
        repeated = device.reverse_port(remote_node, local_node)
        assert repeated == port_forward
        listed = [
            rule
            for rule in device.list_port_forwards()
            if rule.target == device.target
            and rule.direction == "Reverse"
            and rule.local_node == local_node
            and rule.remote_node == remote_node
        ]
        assert len(listed) == 1
    finally:
        removal = device.remove_port_forward(port_forward)
        assert removal.success is True


def test_forward_port_raises_for_conflicting_existing_rule() -> None:
    device = _connected_device()
    local_node = _random_tcp_node()
    remote_node = _random_tcp_node()
    conflicting_remote_node = _random_tcp_node()
    port_forward = device.forward_port(local_node, remote_node)
    try:
        with pytest.raises(RuntimeError, match="Remove the existing forward rule first"):
            device.forward_port(local_node, conflicting_remote_node)
    finally:
        removal = device.remove_port_forward(port_forward)
        assert removal.success is True


def test_forward_port_raises_when_hdc_reports_logical_failure() -> None:
    device = _connected_device()
    with pytest.raises(RuntimeError, match="Incorrect forward command"):
        device.forward_port("not-a-node", _random_tcp_node())


def test_remove_port_forward_rejects_rule_from_different_target() -> None:
    device = _connected_device()
    other_target = f"{device.target}-different"
    port_forward = PortForward(other_target, _random_tcp_node(), _random_tcp_node(), "Forward")
    with pytest.raises(ValueError, match="different target"):
        device.remove_port_forward(port_forward)


def test_parse_port_forward_handles_nodes_with_spaces() -> None:
    parsed = HarmonyDevice._parse_port_forward(
        "127.0.0.1:55556    localfilesystem:/tmp/my socket tcp:5000    [Forward]"
    )
    assert parsed.target == "127.0.0.1:55556"
    assert parsed.local_node == "localfilesystem:/tmp/my socket"
    assert parsed.remote_node == "tcp:5000"


def test_parse_port_forward_rejects_malformed_entry() -> None:
    with pytest.raises(RuntimeError, match="Could not parse port forward entry"):
        HarmonyDevice._parse_port_forward("not a valid forwarding entry")


def test_parse_port_forward_rejects_entry_without_two_nodes() -> None:
    with pytest.raises(RuntimeError, match="Could not parse port forward nodes"):
        HarmonyDevice._parse_port_forward("127.0.0.1:55556 tcp:5000 [Forward]")


def test_remove_port_forward_requires_second_node_for_string_arguments() -> None:
    device = _connected_device()
    with pytest.raises(ValueError, match="second_node is required"):
        device.remove_port_forward(_random_tcp_node())


def test_forward_port_raises_called_process_error_when_hdc_exits_nonzero(tmp_path: Path) -> None:
    device = _fake_device(
        tmp_path,
        "\n".join(
            [
                'if [ "$1" = "fport" ] && [ "$2" = "ls" ]; then',
                "  printf '[Empty]\\n'",
                "  exit 0",
                "fi",
                'if [ "$1" = "fport" ]; then',
                "  printf 'transport error\\n' >&2",
                "  exit 7",
                "fi",
            ]
        ),
    )
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        device.forward_port("tcp:6000", "tcp:7000")
    assert exc_info.value.returncode == 7


def test_forward_port_ignores_existing_reverse_rule_for_same_first_node() -> None:
    device = _connected_device()
    shared_first_node = _random_tcp_node()
    reverse_local_node = _random_tcp_node()
    forward_remote_node = _random_tcp_node()
    reverse_port_forward = device.reverse_port(shared_first_node, reverse_local_node)
    try:
        forward_port_forward = device.forward_port(shared_first_node, forward_remote_node)
        try:
            assert forward_port_forward == PortForward(
                device.target,
                shared_first_node,
                forward_remote_node,
                "Forward",
            )
        finally:
            removal = device.remove_port_forward(forward_port_forward)
            assert removal.success is True
    finally:
        removal = device.remove_port_forward(reverse_port_forward)
        assert removal.success is True


def test_forward_port_ignores_existing_forward_rule_for_different_first_node() -> None:
    device = _connected_device()
    existing_port_forward = device.forward_port(_random_tcp_node(), _random_tcp_node())
    try:
        port_forward = device.forward_port(_random_tcp_node(), _random_tcp_node())
        try:
            assert port_forward.target == device.target
            assert port_forward.direction == "Forward"
            assert port_forward != existing_port_forward
        finally:
            removal = device.remove_port_forward(port_forward)
            assert removal.success is True
    finally:
        removal = device.remove_port_forward(existing_port_forward)
        assert removal.success is True


def test_reverse_port_accepts_ambiguous_success_output_when_exit_code_is_zero(tmp_path: Path) -> None:
    device = _fake_device(
        tmp_path,
        "\n".join(
            [
                'if [ "$1" = "fport" ] && [ "$2" = "ls" ]; then',
                "  printf '[Empty]\\n'",
                "  exit 0",
                "fi",
                'if [ "$1" = "rport" ]; then',
                "  printf 'rport completed\\n'",
                "  exit 0",
                "fi",
            ]
        ),
    )
    port_forward = device.reverse_port("tcp:6000", "tcp:7000")
    assert port_forward == PortForward("fake-target", "tcp:6000", "tcp:7000", "Reverse")


def test_remove_port_forward_falls_back_to_exit_code_when_output_is_ambiguous(tmp_path: Path) -> None:
    device = _fake_device(
        tmp_path,
        "\n".join(
            [
                'if [ "$1" = "fport" ] && [ "$2" = "rm" ]; then',
                "  exit 0",
                "fi",
            ]
        ),
    )
    removal = device.remove_port_forward("tcp:6000", "tcp:7000")
    assert removal.success is True
    assert removal.message == ""


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
