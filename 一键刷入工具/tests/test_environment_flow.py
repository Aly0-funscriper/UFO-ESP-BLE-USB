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

    def test_probe_refuses_to_install_when_port_is_busy(self):
        original = FLASHER.capture_mpremote
        try:
            FLASHER.capture_mpremote = lambda _args: (
                False,
                "mpremote: failed to access COM13 (it may be in use by another program)",
            )
            with self.assertRaisesRegex(RuntimeError, "serial port is busy"):
                FLASHER.probe_micropython("COM13")
        finally:
            FLASHER.capture_mpremote = original

    def test_existing_environment_skips_installation(self):
        port = SimpleNamespace(device="COM9")
        original_probe = FLASHER.probe_micropython
        original_install = FLASHER.install_micropython
        original_wait = FLASHER.wait_for_port
        try:
            FLASHER.wait_for_port = lambda previous, timeout=20.0: previous
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
            FLASHER.wait_for_port = original_wait

    def test_failed_read_only_chip_check_prevents_installation(self):
        port = SimpleNamespace(device="COM13")
        original_probe = FLASHER.probe_micropython
        original_install = FLASHER.install_micropython
        original_wait = FLASHER.wait_for_port
        original_verify = FLASHER.verify_esptool_access
        try:
            FLASHER.wait_for_port = lambda previous, timeout=20.0: previous
            FLASHER.probe_micropython = lambda _port: (False, "SerialTimeoutException")
            FLASHER.verify_esptool_access = lambda _port: (_ for _ in ()).throw(
                RuntimeError("no flash was erased")
            )
            FLASHER.install_micropython = lambda *_args: self.fail(
                "installation must not start"
            )
            with self.assertRaisesRegex(RuntimeError, "no flash was erased"):
                FLASHER.ensure_micropython(port, Path("unused.bin"))
        finally:
            FLASHER.probe_micropython = original_probe
            FLASHER.install_micropython = original_install
            FLASHER.wait_for_port = original_wait
            FLASHER.verify_esptool_access = original_verify

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
