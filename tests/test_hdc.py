import unittest
from hdc_py import HarmonyDeviceConnector


class TestHDC(unittest.TestCase):
    def test_hdc_py(self) -> None:
        hdc = HarmonyDeviceConnector()
        assert hdc is not None


if __name__ == "__main__":
    unittest.main()
