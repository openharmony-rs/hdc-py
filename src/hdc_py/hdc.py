import hashlib
import os
import pathlib
import platform
import re
import shlex
import shutil
import string
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from os import PathLike
from pathlib import PurePosixPath
from subprocess import CompletedProcess
from typing import Any, Literal, Optional


_HASH_BUFFER_SIZE = 1024 * 1024


def _is_wsl() -> bool:
    return sys.platform == "linux" and platform.uname().release.endswith("microsoft-standard-WSL2")


def _which_hdc() -> pathlib.Path:
    hdc_path = shutil.which("hdc")
    if hdc_path is None and _is_wsl():
        # When running python on windows, shutil will automatically consider the `.exe` suffix.
        # However, on wsl this is not the case, but we can still use the windows `hdc.exe` executable.
        hdc_path = shutil.which("hdc.exe")
    if hdc_path is None and sys.platform == "win32":
        # This environment variable is setup by DevEco Studio after installation.
        deveco_bin = os.getenv("DevEco Studio")
        if deveco_bin is not None:
            deveco_bin = pathlib.Path(deveco_bin)
            dev_eco_hdc = deveco_bin.parent.joinpath("sdk", "default", "openharmony", "toolchains", "hdc.exe")
            if dev_eco_hdc.is_file():
                hdc_path = dev_eco_hdc

    if hdc_path is None:
        ohos_sdk_native = os.getenv("OHOS_SDK_NATIVE")
        if ohos_sdk_native is None:
            raise RuntimeError(
                "`hdc` could not be found. Add `hdc` to PATH or construct Hdc "
                "with an explicit path to the `hdc` executable."
            )
        hdc_path = os.path.join(ohos_sdk_native, "../", "toolchains", "hdc")
        assert pathlib.Path(hdc_path).exists()
    return pathlib.Path(hdc_path).resolve()


class HdcError(RuntimeError):
    pass


class HdcConnectionError(HdcError):
    pass


class HdcTargetNotFoundError(HdcConnectionError):
    pass


class HdcAmbiguousTargetError(HdcConnectionError):
    pass


class HdcDisconnectedError(HdcConnectionError):
    pass


@dataclass(frozen=True)
class PortForward:
    target: str
    first_node: str
    second_node: str
    direction: Literal["Forward", "Reverse"]

    @property
    def local_node(self) -> str:
        if self.direction == "Forward":
            return self.first_node
        return self.second_node

    @property
    def remote_node(self) -> str:
        if self.direction == "Forward":
            return self.second_node
        return self.first_node


@dataclass(frozen=True)
class PortForwardRemovalResult:
    first_node: str
    second_node: str
    success: bool
    message: str

    @property
    def not_found(self) -> bool:
        return "not exist" in self.message.lower()


class Hdc:
    def __init__(self, hdc_path: Optional[PathLike] = None) -> None:
        if hdc_path is not None:
            hdc_path_resolved = pathlib.Path(hdc_path).resolve()
            if not hdc_path_resolved.exists():
                raise ValueError(f"hdc_path={hdc_path} does not exist")
            self.hdc_path = hdc_path_resolved
        else:
            self.hdc_path = _which_hdc()

    def _run(self, args: list[str], **kwargs) -> CompletedProcess:  # noqa: ANN003
        return subprocess.run([self.hdc_path, *args], **kwargs)

    def wait(self, timeout: float = 5) -> None:
        try:
            self._run(["wait"], timeout=timeout)
        except subprocess.TimeoutExpired as e:
            print(f"Failed to find hdc device in {timeout} seconds", file=sys.stderr)
            raise e

    def list_targets(self) -> list[str]:
        result = self._run(["list", "targets"], check=True, capture_output=True, text=True)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def is_target_connected(self, target: str) -> bool:
        return target in self.list_targets()

    def connect(self, target: Optional[str] = None) -> "HarmonyDevice":
        targets = self.list_targets()
        if target is None:
            if not targets:
                raise HdcTargetNotFoundError("No connected hdc devices were found")
            if len(targets) > 1:
                raise HdcAmbiguousTargetError(
                    "Multiple hdc devices are connected. Pass target=... to select one: " + ", ".join(targets)
                )
            target = targets[0]
        elif target not in targets:
            raise HdcTargetNotFoundError(f"Target {target!r} is not connected")
        return HarmonyDevice(self, target)


class HarmonyDevice:
    _DEVICE_HASH_COMMAND = "openssl dgst -sha256 {path}"
    _DEVICE_TMP_DIR = "/data/local/tmp"
    _PORT_NODE_PATTERN = re.compile(
        r"(?:(?<=^)|(?<=\s))(tcp:|localfilesystem:|localreserved:|localabstract:|dev:|jdwp:)"
    )

    def __init__(self, hdc: Hdc, target: str) -> None:
        if not target:
            raise ValueError("target must not be empty")
        self.hdc = hdc
        self.target = target

    @property
    def hdc_path(self) -> pathlib.Path:
        return self.hdc.hdc_path

    def _ensure_connected(self) -> None:
        if not self.hdc.is_target_connected(self.target):
            raise HdcDisconnectedError(f"Target {self.target!r} is no longer connected")

    def _run_target(self, args: list[str], verify_connected: bool = True, **kwargs) -> CompletedProcess:  # noqa: ANN003
        if verify_connected:
            self._ensure_connected()
        return subprocess.run([self.hdc_path, "-t", self.target, *args], **kwargs)

    def _device_temp_path(self, prefix: str) -> str:
        return f"{self._DEVICE_TMP_DIR}/{prefix}-{uuid.uuid4().hex}"

    def _cleanup_device_file(self, device_filepath: str) -> None:
        quoted_path = shlex.quote(device_filepath)
        self._run_target(
            ["shell", f"rm -f {quoted_path}"],
            verify_connected=False,
            check=False,
            capture_output=True,
            text=True,
        )

    def _read_device_exit_code(self, device_filepath: str) -> int:
        quoted_path = shlex.quote(device_filepath)
        result = self._run_target(["shell", f"cat {quoted_path}"], capture_output=True, text=True)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        for line in reversed(output.splitlines()):
            stripped = line.strip()
            if stripped.lstrip("-").isdigit():
                return int(stripped)
        raise RuntimeError(f"Could not read device exit code from {device_filepath!r}")

    """Run `command` on the device. Pass additional arguments through to `subprocess.run`"""

    def cmd(self, command: str, **kwargs) -> CompletedProcess:  # noqa: ANN003
        check = kwargs.pop("check", True)
        print(f"Executing hdc command on {self.target}: {command}", file=sys.stderr)

        exit_code_file = self._device_temp_path("hdc-py-exit-code")
        quoted_exit_code_file = shlex.quote(exit_code_file)
        wrapped_command = (
            f"rm -f {quoted_exit_code_file}; "
            f"sh -c {shlex.quote(command)}; "
            f"hdc_py_rc=$?; printf '%s' \"$hdc_py_rc\" > {quoted_exit_code_file}"
        )
        result = self._run_target(["shell", wrapped_command], check=False, **kwargs)
        cmd_args = [self.hdc_path, "-t", self.target, "shell", command]
        if result.returncode != 0:
            if check:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    cmd_args,
                    output=result.stdout,
                    stderr=result.stderr,
                )
            return CompletedProcess(cmd_args, result.returncode, result.stdout, result.stderr)

        try:
            device_returncode = self._read_device_exit_code(exit_code_file)
        finally:
            self._cleanup_device_file(exit_code_file)

        completed = CompletedProcess(cmd_args, device_returncode, result.stdout, result.stderr)
        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                completed.args,
                output=completed.stdout,
                stderr=completed.stderr,
            )
        return completed

    def wakeup(self) -> None:
        self.cmd("power-shell wakeup")

    def suspend(self) -> None:
        self.cmd("power-shell suspend")

    def mount_system_as_rw(self) -> None:
        """Set /system /vendor partition read-write
        This option only affects rooted devices.
        """
        self._run_target(["target", "mount"], check=True)

    @staticmethod
    def _parse_port_forward(line: str) -> PortForward:
        match = re.match(r"^(?P<target>\S+)\s+(?P<body>.+)\s+\[(?P<direction>Forward|Reverse)\]$", line)
        if match is None:
            raise RuntimeError(f"Could not parse port forward entry: {line!r}")
        target = match.group("target")
        body = match.group("body")
        normalized_direction = match.group("direction")
        node_matches = list(HarmonyDevice._PORT_NODE_PATTERN.finditer(body))
        if len(node_matches) < 2:
            raise RuntimeError(f"Could not parse port forward nodes: {line!r}")
        first_node = body[node_matches[0].start() : node_matches[1].start()].rstrip()
        second_node = body[node_matches[1].start() :].strip()
        return PortForward(
            target=target,
            first_node=first_node,
            second_node=second_node,
            direction=normalized_direction,
        )

    def _run_port_command(self, args: list[str], success_fragment: str) -> str:
        result = self._run_target(args, check=False, capture_output=True, text=True)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        normalized_output = output.lower()
        if success_fragment.lower() in normalized_output:
            return output
        if "[fail]" in normalized_output or "failed" in normalized_output:
            raise RuntimeError(output)
        return output

    def _existing_port_forward_conflict(
        self,
        first_node: str,
        second_node: str,
        direction: Literal["Forward", "Reverse"],
    ) -> Optional[PortForward]:
        for port_forward in self.list_port_forwards():
            if port_forward.target != self.target or port_forward.direction != direction:
                continue
            if port_forward.first_node != first_node:
                continue
            if port_forward.second_node == second_node:
                return port_forward
            raise RuntimeError(
                "A different port forward already exists for "
                f"{first_node!r} on target {self.target!r}. Remove the existing forward rule first."
            )
        return None

    def list_port_forwards(self) -> list[PortForward]:
        result = self._run_target(["fport", "ls"], check=True, capture_output=True, text=True)
        forwards: list[PortForward] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "[Empty]":
                continue
            forwards.append(self._parse_port_forward(stripped))
        return forwards

    def forward_port(self, local_node: str, remote_node: str) -> PortForward:
        existing = self._existing_port_forward_conflict(local_node, remote_node, "Forward")
        if existing is not None:
            return existing
        self._run_port_command(["fport", local_node, remote_node], "Forwardport result:OK")
        return PortForward(self.target, local_node, remote_node, "Forward")

    def reverse_port(self, remote_node: str, local_node: str) -> PortForward:
        existing = self._existing_port_forward_conflict(remote_node, local_node, "Reverse")
        if existing is not None:
            return existing
        self._run_port_command(["rport", remote_node, local_node], "Forwardport result:OK")
        return PortForward(self.target, remote_node, local_node, "Reverse")

    def remove_port_forward(
        self,
        port_forward: PortForward | str,
        second_node: Optional[str] = None,
    ) -> PortForwardRemovalResult:
        if isinstance(port_forward, PortForward):
            if port_forward.target != self.target:
                raise ValueError(
                    f"Port forward belongs to different target {port_forward.target!r}; expected {self.target!r}"
                )
            first_node = port_forward.first_node
            second_node = port_forward.second_node
        elif second_node is None:
            raise ValueError("second_node is required when removing a port forward by endpoint strings")
        else:
            first_node = port_forward
        result = self._run_target(
            ["fport", "rm", first_node, second_node],
            check=False,
            capture_output=True,
            text=True,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        normalized_output = output.lower()
        success = "remove forward ruler success" in normalized_output
        if not success and "[fail]" not in normalized_output and "failed" not in normalized_output:
            success = result.returncode == 0
        return PortForwardRemovalResult(first_node, second_node, success, output)

    @staticmethod
    def _host_file_hash(host_filepath: PathLike[str] | str, algorithm: str) -> str:
        digest = hashlib.new(algorithm)
        with open(host_filepath, mode="rb") as file:
            for chunk in iter(lambda: file.read(_HASH_BUFFER_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _extract_hash(output: str) -> Optional[str]:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "=" in stripped:
                candidate = stripped.rsplit("=", maxsplit=1)[1].strip().split()[0]
            else:
                candidate = stripped.split()[0]
            if candidate and all(character in string.hexdigits for character in candidate):
                return candidate.lower()
        return None

    @staticmethod
    def _verify_matching_hashes(
        source_path: PathLike[str] | str,
        target_path: str,
        algorithm: str,
        source_hash: str,
        target_hash: str,
    ) -> None:
        if source_hash != target_hash:
            raise RuntimeError(
                "File transfer verification failed: "
                f"{algorithm} mismatch for host={source_path} and device={target_path} "
                f"({source_hash} != {target_hash})"
            )

    @staticmethod
    def _resolve_recv_target_path(device_filepath: str, host_filepath: Optional[str]) -> pathlib.Path:
        device_name = PurePosixPath(device_filepath).name
        if not device_name:
            raise ValueError(f"Could not resolve a local filename for device path {device_filepath!r}")
        if host_filepath is None:
            return pathlib.Path.cwd() / device_name
        host_path = pathlib.Path(host_filepath)
        if host_path.exists() and host_path.is_dir():
            return host_path / device_name
        return host_path

    def _device_file_exists(self, device_filepath: str) -> bool:
        quoted_path = shlex.quote(device_filepath)
        result = self.cmd(
            f"if [ -f {quoted_path} ]; then echo __HDC_EXISTS__; exit 0; fi; echo __HDC_MISSING__; exit 1",
            capture_output=True,
            text=True,
            check=False,
        )
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if "__HDC_EXISTS__" in output:
            return True
        if "__HDC_MISSING__" in output:
            return False
        raise RuntimeError(f"Could not determine whether device file {device_filepath!r} exists")

    def _device_file_hash(self, device_filepath: str) -> str:
        algorithm = "sha256"
        if not self._device_file_exists(device_filepath):
            raise FileNotFoundError(f"Device file {device_filepath!r} does not exist")

        quoted_path = shlex.quote(device_filepath)
        result = self.cmd(self._DEVICE_HASH_COMMAND.format(path=quoted_path), capture_output=True, text=True)
        output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        digest = self._extract_hash(output)
        if digest is None:
            raise RuntimeError(f"Could not parse {algorithm} digest for device file {device_filepath}")
        return digest

    def _host_and_device_hashes(self, host_filepath: PathLike[str] | str, device_filepath: str) -> tuple[str, str, str]:
        algorithm = "sha256"
        device_hash = self._device_file_hash(device_filepath)
        host_hash = self._host_file_hash(host_filepath, algorithm)
        return algorithm, host_hash, device_hash

    def recv_file(self, device_filepath: str, host_filepath: Optional[str] = None) -> None:
        if not self._device_file_exists(device_filepath):
            raise FileNotFoundError(f"Device file {device_filepath!r} does not exist")

        resolved_host_path = self._resolve_recv_target_path(device_filepath, host_filepath)
        if resolved_host_path.exists() and resolved_host_path.is_file():
            algorithm, host_hash, device_hash = self._host_and_device_hashes(resolved_host_path, device_filepath)
            if host_hash == device_hash:
                return

        cmd = ["file", "recv", device_filepath]
        if host_filepath is not None:
            cmd.append(host_filepath)
        self._run_target(cmd, check=True)

        algorithm, host_hash, device_hash = self._host_and_device_hashes(resolved_host_path, device_filepath)
        self._verify_matching_hashes(resolved_host_path, device_filepath, algorithm, host_hash, device_hash)

    def read_file(self, device_filepath: str) -> Optional[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            assert pathlib.Path(temp_dir).exists()
            host_file = temp_dir + "/servo.log"
            try:
                self.recv_file(device_filepath, host_file)
            except FileNotFoundError:
                return None
            if pathlib.Path(host_file).exists():
                with open(host_file, mode="r", encoding="utf-8") as logfile:
                    return logfile.read()
            return None

    def send_file(self, host_filepath: str, device_filepath: str) -> None:
        host_path = pathlib.Path(host_filepath)
        if not host_path.is_file():
            raise FileNotFoundError(f"Host file {host_filepath!r} does not exist")

        if self._device_file_exists(device_filepath):
            algorithm, host_hash, device_hash = self._host_and_device_hashes(host_path, device_filepath)
            if host_hash == device_hash:
                return

        self._run_target(["file", "send", host_filepath, device_filepath], check=True)

        algorithm, host_hash, device_hash = self._host_and_device_hashes(host_path, device_filepath)
        self._verify_matching_hashes(host_path, device_filepath, algorithm, host_hash, device_hash)

    def screenshot(self, host_filepath: str) -> None:
        device_path = "/data/local/tmp/servo.jpeg"
        self.cmd(f"rm -f {device_path}")
        # -t [jpeg | png] [-w width] [-h height]
        self.cmd(f"snapshot_display -f {device_path}")
        self.recv_file(device_path, host_filepath)


class HarmonyDeviceConnector(HarmonyDevice):
    def __init__(self, hdc_path: Optional[PathLike] = None, target: Optional[str] = None) -> None:
        hdc = Hdc(hdc_path=hdc_path)
        device = hdc.connect(target=target)
        super().__init__(hdc=hdc, target=device.target)


class HarmonyDevicePerfMode:
    """
    A helper class to enter performance mode using python `with` syntax.
    """

    def __init__(
        self,
        screen_timeout_seconds: int = 600,
        hdc: Optional[HarmonyDevice] = None,
    ) -> None:
        if hdc is None:
            self.hdc = HarmonyDeviceConnector()
        else:
            self.hdc = hdc
        self.screen_timeout_seconds: int = screen_timeout_seconds

    def __enter__(self) -> None:
        self.hdc.cmd("power-shell setmode 602")
        screen_timeout_ms = self.screen_timeout_seconds * 1000
        self.hdc.cmd(f"power-shell timeout -o {screen_timeout_ms}")
        self.hdc.wakeup()

    def __exit__(
        self,
        exception_type: Any,  # noqa: ANN401
        exception_value: Any,  # noqa: ANN401
        exception_traceback: Any,  # noqa: ANN401
    ) -> None:
        # Back to normal mode
        try:
            self.hdc.cmd("power-shell setmode 600")
            self.hdc.cmd("power-shell timeout -r")
        except Exception as e:
            print(f"Warning: Failed to restore power-shell settings: {e}", file=sys.stderr)
