import os
import pathlib
import shutil
import subprocess
import tempfile
from subprocess import CompletedProcess
from typing import Optional, Any


class HarmonyDeviceConnector:
    @staticmethod
    def _which_hdc() -> pathlib.Path:
        hdc_path = shutil.which("hdc")
        if hdc_path is None:
            ohos_sdk_native = os.getenv("OHOS_SDK_NATIVE")
            assert ohos_sdk_native, "hdc not found in PATH and OHOS_SDK_NATIVE not set."
            hdc_path = os.path.join(ohos_sdk_native, "../", "toolchains", "hdc")
            assert pathlib.Path(hdc_path).exists()
        hdc_path = pathlib.Path(hdc_path).resolve()
        return hdc_path

    def __init__(self) -> None:
        self.hdc_path = self._which_hdc()
        self._wait()

    """Run `command` on the device. Pass additional arguments through to `subprocess.run`"""

    def cmd(self, command: str, **kwargs) -> CompletedProcess:  # noqa: ANN003
        print(f"Executing hdc command: {command}")
        return subprocess.run([self.hdc_path, "shell", command], check=True, **kwargs)

    def _wait(self, timeout: float = 5) -> None:
        try:
            subprocess.run([self.hdc_path, "wait"], timeout=timeout)
        except subprocess.TimeoutExpired as e:
            print(f"Failed to find hdc device in {timeout} seconds")
            raise e

    """Wakeup system and turn screen on"""

    def wakeup(self) -> None:
        self._wait()
        self.cmd("power-shell wakeup")

    """Suspend system and turn screen off"""

    def suspend(self) -> None:
        self.cmd("power-shell suspend")

    def recv_file(self, device_filepath: str, host_filepath: Optional[str] = None) -> None:
        cmd = [self.hdc_path, "file", "recv", device_filepath]
        if host_filepath is not None:
            cmd.append(host_filepath)
        subprocess.run(cmd)

    def read_file(self, device_filepath: str) -> Optional[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            assert pathlib.Path(temp_dir).exists()
            host_file = temp_dir + "/servo.log"
            self.recv_file(device_filepath, host_file)
            if pathlib.Path(host_file).exists():
                with open(host_file, mode="r", encoding="utf-8") as logfile:
                    return logfile.read()
            else:
                return None

    def send_file(self, host_filepath: str, device_filepath: str) -> None:
        subprocess.run([self.hdc_path, "file", "send", host_filepath, device_filepath])

    def screenshot(self, host_filepath: str) -> None:
        device_path = "/data/local/tmp/servo.jpeg"
        self.cmd(f"rm -f {device_path}")
        # -t [jpeg | png] [-w width] [-h height]
        self.cmd(f"snapshot_display -f {device_path}")
        self.recv_file(device_path, host_filepath)


class HarmonyDevicePerfMode:
    """
    A helper class to enter performance mode using python `with` syntax.
    """

    def __init__(
        self,
        screen_timeout_seconds: int = 600,
        hdc: Optional[HarmonyDeviceConnector] = None,
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
            print(f"Warning: Failed to restore power-shell settings: {e}")
