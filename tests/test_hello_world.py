from hdc_py import HarmonyDeviceConnector


def test_echo() -> None:
    hdc = HarmonyDeviceConnector()
    result = hdc.cmd("echo hello-world!", capture_output=True, text=True)
    assert result.stdout.strip() == "hello-world!"
