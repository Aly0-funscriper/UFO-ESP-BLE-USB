import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


FLASHER_PATH = Path(__file__).resolve().parents[1] / "flasher.py"
SPEC = importlib.util.spec_from_file_location("ufo_flasher", FLASHER_PATH)
FLASHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FLASHER)


class EnvironmentFlowTests(unittest.TestCase):
    def test_probe_recognizes_micropython_marker(self):
        original = FLASHER.capture_mpremote
        try:
            FLASHER.capture_mpremote = lambda _args: (
                True,
                "MICROPYTHON_ENV_OK micropython 1.29.0 esp32\n",
            )
            installed, details = FLASHER.probe_micropython("COM9")
            self.assertTrue(installed)
            self.assertIn("1.29.0", details)
        finally:
            FLASHER.capture_mpremote = original

    def test_existing_environment_skips_installation(self):
        port = SimpleNamespace(device="COM9")
        original_probe = FLASHER.probe_micropython
        original_install = FLASHER.install_micropython
        try:
            FLASHER.probe_micropython = lambda _port: (
                True,
                "MICROPYTHON_ENV_OK micropython 1.29.0 esp32",
            )
            FLASHER.install_micropython = lambda *_args: self.fail(
                "installation must be skipped"
            )
            result, installed = FLASHER.ensure_micropython(port, Path("unused.bin"))
            self.assertIs(result, port)
            self.assertFalse(installed)
        finally:
            FLASHER.probe_micropython = original_probe
            FLASHER.install_micropython = original_install

    def test_missing_environment_erases_then_writes_address_zero(self):
        port = SimpleNamespace(device="COM9", serial_number="ABC", location="1-1")
        image = FLASHER_PATH.parent / "micropython" / FLASHER.MICROPYTHON_IMAGE
        calls = []
        original_esptool = FLASHER.run_esptool
        original_wait = FLASHER.wait_for_port
        original_probe = FLASHER.probe_micropython
        try:
            FLASHER.run_esptool = lambda args: calls.append(tuple(str(x) for x in args))
            FLASHER.wait_for_port = lambda previous, timeout=20.0: previous
            FLASHER.probe_micropython = lambda _port: (
                True,
                "MICROPYTHON_ENV_OK micropython 1.29.0 esp32",
            )
            result = FLASHER.install_micropython(port, image)
            self.assertIs(result, port)
            self.assertEqual(calls[0][-1], "erase-flash")
            self.assertIn("write-flash", calls[1])
            self.assertEqual(calls[1][-2], "0x0")
            self.assertEqual(calls[1][-1], str(image))
        finally:
            FLASHER.run_esptool = original_esptool
            FLASHER.wait_for_port = original_wait
            FLASHER.probe_micropython = original_probe


if __name__ == "__main__":
    unittest.main()
