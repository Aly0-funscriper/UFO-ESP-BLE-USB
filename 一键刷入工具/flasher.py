import argparse
import contextlib
import hashlib
import io
import os
from pathlib import Path
import sys
import time

from serial import Serial
from serial.tools import list_ports
from esptool import main as esptool_main
from mpremote.main import main as mpremote_main


APP_TITLE = "UFO-ESP MicroPython + BLE + USB one-click flasher"
FIRMWARE_FILES = ("motor.py", "main.py", "boot.py")
OBSOLETE_FILES = ("muse_broadcast.py",)
EXPECTED_VID = 0x303A
MICROPYTHON_IMAGE = "ESP32_GENERIC_C3-20260824-v1.29.0.bin"
MICROPYTHON_VERSION = "v1.29.0"
MICROPYTHON_SHA256 = "BF72ED9EB88AD3A8F49D02C3D371F9EA34C90A8A303AEB9E324D8EFD4A2A655A"
MICROPYTHON_MARKER = "MICROPYTHON_ENV_OK"
PORT_DISCOVERY_TIMEOUT = 20.0
ENVIRONMENT_PROBE_ATTEMPTS = 3


class EncodedStringIO(io.StringIO):
    # mpremote decodes transport output using sys.stdout.encoding. The plain
    # io.StringIO used by redirect_stdout reports encoding=None.
    @property
    def encoding(self):
        return "utf-8"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "firmware"


def micropython_image_path() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "micropython" / MICROPYTHON_IMAGE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 128), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def run_mpremote(arguments, tolerate_failure=False):
    previous_argv = sys.argv[:]
    sys.argv = ["mpremote", *[str(value) for value in arguments]]
    try:
        if tolerate_failure:
            captured = EncodedStringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                status = mpremote_main()
        else:
            status = mpremote_main()
    except SystemExit as exc:
        status = int(exc.code or 0)
    except Exception as exc:
        if not tolerate_failure:
            raise RuntimeError(
                "mpremote failed: " + " ".join(map(str, arguments))
            ) from exc
        status = 1
    finally:
        sys.argv = previous_argv

    if status and not tolerate_failure:
        raise RuntimeError("mpremote failed: " + " ".join(map(str, arguments)))
    return status == 0


def capture_mpremote(arguments):
    previous_argv = sys.argv[:]
    captured = EncodedStringIO()
    sys.argv = ["mpremote", *[str(value) for value in arguments]]
    try:
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            status = mpremote_main()
    except SystemExit as exc:
        status = int(exc.code or 0)
    except Exception as exc:
        status = 1
        captured.write("\n{}: {}".format(type(exc).__name__, exc))
    finally:
        sys.argv = previous_argv
    return status == 0, captured.getvalue()


def probe_micropython(port: str):
    command = (
        "import sys; "
        "print('{}', sys.implementation.name, ".format(MICROPYTHON_MARKER)
        + "'.'.join(str(x) for x in sys.implementation.version[:3]), sys.platform)"
    )
    ok, output = capture_mpremote(["connect", port, "+", "exec", command])
    if ok and MICROPYTHON_MARKER in output:
        marker_line = next(
            (line.strip() for line in output.splitlines() if MICROPYTHON_MARKER in line),
            MICROPYTHON_MARKER,
        )
        return True, marker_line

    lowered = output.lower()
    busy_markers = (
        "access is denied",
        "permissionerror",
        "permission denied",
        "failed to access",
        "may be in use",
        "port is busy",
        "the device does not recognize the command",
        "resource busy",
    )
    if any(marker in lowered for marker in busy_markers):
        raise RuntimeError(
            "The serial port is busy. Close MultiFunPlayer, Thonny, serial monitors, and flashing tools first."
        )
    return False, output.strip()


def run_esptool(arguments):
    try:
        result = esptool_main([str(value) for value in arguments])
    except SystemExit as exc:
        status = int(exc.code or 0)
        if status:
            raise RuntimeError("esptool failed with exit code {}".format(status)) from exc
        return
    if isinstance(result, int) and result:
        raise RuntimeError("esptool failed with exit code {}".format(result))


def find_matching_port(previous_port):
    ports = list(list_ports.comports())
    same_name = next(
        (item for item in ports if item.device.upper() == previous_port.device.upper()),
        None,
    )
    if same_name is not None:
        return same_name

    serial_number = getattr(previous_port, "serial_number", None)
    if serial_number:
        same_serial = next(
            (item for item in ports if item.serial_number == serial_number),
            None,
        )
        if same_serial is not None:
            return same_serial

    location = getattr(previous_port, "location", None)
    if location:
        same_location = next(
            (item for item in ports if item.location == location and item.vid == EXPECTED_VID),
            None,
        )
        if same_location is not None:
            return same_location

    espressif = [item for item in ports if item.vid == EXPECTED_VID]
    return espressif[0] if len(espressif) == 1 else None


def wait_for_port(previous_port, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        match = find_matching_port(previous_port)
        if match is not None:
            return match
        time.sleep(0.25)
    raise RuntimeError(
        "The ESP32-C3 serial port did not return after flashing. Reconnect the USB cable and run the flasher again."
    )


def install_micropython(port_info, image_path: Path):
    if not image_path.is_file():
        raise RuntimeError("Embedded MicroPython image is missing: " + str(image_path))
    if sha256(image_path) != MICROPYTHON_SHA256:
        raise RuntimeError("Embedded MicroPython image failed SHA-256 verification")

    print("  MicroPython was not detected; installing embedded", MICROPYTHON_VERSION)
    print("  target chip: ESP32-C3; the board flash will be erased")
    base = ["--chip", "esp32c3", "--port", port_info.device]
    try:
        run_esptool([*base, "erase-flash"])
        port_info = wait_for_port(port_info)
        run_esptool([
            "--chip", "esp32c3",
            "--port", port_info.device,
            "--baud", "460800",
            "write-flash", "0x0", image_path,
        ])
    except Exception as exc:
        raise RuntimeError(
            "Automatic MicroPython installation failed. If the board is not in download mode, "
            "hold BOOT, tap RESET, release BOOT, and run this flasher again. Original error: {}".format(exc)
        ) from exc

    port_info = wait_for_port(port_info)
    deadline = time.monotonic() + 20.0
    last_output = ""
    while time.monotonic() < deadline:
        try:
            installed, last_output = probe_micropython(port_info.device)
        except RuntimeError:
            installed = False
        if installed:
            print("  installed and verified:", last_output)
            return port_info
        time.sleep(0.5)
        match = find_matching_port(port_info)
        if match is not None:
            port_info = match

    raise RuntimeError(
        "MicroPython was written, but its REPL could not be verified. Last response: " + last_output
    )


def verify_esptool_access(port_info):
    print("  performing read-only ESP32-C3 chip identity check before any erase")
    try:
        run_esptool([
            "--chip", "esp32c3",
            "--port", port_info.device,
            "chip-id",
        ])
    except Exception as exc:
        raise RuntimeError(
            "The board could not be safely identified with esptool, so no flash was erased. "
            "Close MultiFunPlayer, Thonny, serial monitors, and other flashing tools, then retry. "
            "Original error: {}".format(exc)
        ) from exc
    return wait_for_port(port_info, timeout=10.0)


def ensure_micropython(port_info, image_path: Path):
    last_details = ""
    for attempt in range(1, ENVIRONMENT_PROBE_ATTEMPTS + 1):
        port_info = wait_for_port(port_info, timeout=10.0)
        if attempt > 1:
            time.sleep(0.75)
        installed, last_details = probe_micropython(port_info.device)
        if installed:
            print("  detected:", last_details)
            print("  environment installation skipped")
            return port_info, False
        if attempt < ENVIRONMENT_PROBE_ATTEMPTS:
            print("  probe {}/{} received no MicroPython REPL; retrying after USB settles".format(
                attempt, ENVIRONMENT_PROBE_ATTEMPTS
            ))

    print("  no MicroPython REPL after {} probes".format(ENVIRONMENT_PROBE_ATTEMPTS))
    if last_details:
        print("  last probe:", last_details.replace("\n", " ")[:240])
    port_info = wait_for_port(port_info, timeout=10.0)
    port_info = verify_esptool_access(port_info)
    return install_micropython(port_info, image_path), True


def detect_port(requested_port=None, timeout=PORT_DISCOVERY_TIMEOUT):
    print("  waiting up to {:.0f} seconds for an ESP32-C3 serial port".format(timeout))
    deadline = time.monotonic() + timeout
    last_ports = []
    while time.monotonic() < deadline:
        ports = list(list_ports.comports())
        last_ports = ports
        if requested_port:
            match = next(
                (item for item in ports if item.device.upper() == requested_port.upper()),
                None,
            )
            if match is not None:
                return match
        else:
            espressif = [item for item in ports if item.vid == EXPECTED_VID]
            if len(espressif) == 1:
                return espressif[0]
            if len(espressif) > 1:
                raise RuntimeError(
                    "More than one Espressif board is connected. Disconnect the extra board and try again."
                )
            usb_ports = [
                item for item in ports
                if item.device.upper() != "COM1" and item.vid is not None
            ]
            if len(usb_ports) == 1:
                return usb_ports[0]
        time.sleep(0.5)

    visible = ", ".join(
        "{} ({})".format(item.device, item.description) for item in last_ports
    ) or "none"
    if requested_port:
        raise RuntimeError(
            "Requested serial port {} did not appear. Visible ports: {}".format(
                requested_port, visible
            )
        )
    raise RuntimeError(
        "No ESP32-C3 USB serial port appeared within {:.0f} seconds. Visible ports: {}. "
        "Use a USB data cable, or hold BOOT while reconnecting the board.".format(
            timeout, visible
        )
    )


def backup_board(port: str, backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name in (*FIRMWARE_FILES, *OBSOLETE_FILES):
        destination = backup_dir / name
        print("  backing up", name)
        copied = run_mpremote(
            ["connect", port, "+", "fs", "cp", ":" + name, destination],
            tolerate_failure=True,
        )
        if not copied:
            print("    not present")


def upload_firmware(port: str, firmware_dir: Path):
    # motor.py remains compatible with the previous main.py, so upload it first.
    for name in FIRMWARE_FILES:
        source = firmware_dir / name
        if not source.is_file():
            raise RuntimeError("Embedded firmware file is missing: " + name)
        print("  writing", name)
        run_mpremote(["connect", port, "+", "fs", "cp", source, ":" + name])

    for name in OBSOLETE_FILES:
        print("  removing obsolete", name)
        removed = run_mpremote(
            ["connect", port, "+", "fs", "rm", ":" + name],
            tolerate_failure=True,
        )
        if not removed:
            print("    already absent")


def verify_board(port: str, firmware_dir: Path, verify_dir: Path):
    verify_dir.mkdir(parents=True, exist_ok=False)
    for name in FIRMWARE_FILES:
        destination = verify_dir / name
        print("  reading back", name)
        run_mpremote(["connect", port, "+", "fs", "cp", ":" + name, destination])
        expected = sha256(firmware_dir / name)
        actual = sha256(destination)
        if actual != expected:
            raise RuntimeError("Read-back SHA-256 mismatch: " + name)

    # Importing main must not require the removed Muse module.
    run_mpremote([
        "connect", port, "+", "soft-reset", "+", "exec",
        "import motor, main; print('FIRMWARE_IMPORT_OK', hasattr(main, 'UFOTW_BLE'), hasattr(motor.motor, 'update'))",
    ])


def reboot_and_capture(port: str):
    serial_port = Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=0.5)
    serial_port.dtr = False
    serial_port.rts = False
    serial_port.port = port
    with serial_port:
        serial_port.write(b"\r\x03\x03")
        time.sleep(0.25)
        serial_port.reset_input_buffer()
        serial_port.write(b"\x04")

        deadline = time.monotonic() + 3.0
        output = bytearray()
        while time.monotonic() < deadline:
            output.extend(serial_port.read(4096))

    text = output.decode("utf-8", "replace")
    print(text.strip())
    if "Traceback" in text:
        raise RuntimeError("The board reported a Python traceback after reboot")
    expected_messages = (
        "UFO service registered",
        "UFO advertising started",
        "USB serial control ready",
    )
    if any(message not in text for message in expected_messages):
        raise RuntimeError("The expected BLE + USB startup messages were not received")

    verify_usb_heartbeat(port)


def read_status(serial_port: Serial, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    pending = bytearray()
    while time.monotonic() < deadline:
        pending.extend(serial_port.read(4096))
        while b"\n" in pending:
            raw_line, _, remainder = pending.partition(b"\n")
            pending = bytearray(remainder)
            line = raw_line.decode("ascii", "replace").strip()
            if line.startswith("UFO_STATUS,"):
                print("  ", line)
                return line
    raise RuntimeError("USB firmware status response timed out")


def verify_usb_heartbeat(port: str):
    print("  running USB heartbeat and automatic-stop test")
    serial_port = Serial(port=None, baudrate=115200, timeout=0.05, write_timeout=0.5)
    serial_port.dtr = False
    serial_port.rts = False
    serial_port.port = port
    with serial_port:
        # Opening the ESP32-C3 native USB port can restart the board once.
        time.sleep(1.0)
        serial_port.reset_input_buffer()

        for _ in range(8):
            serial_port.write(b"UFO,3,0\n")
            time.sleep(0.05)
        serial_port.write(b"STATUS\n")
        active_status = read_status(serial_port, 1.0)
        active_fields = active_status.split(",")
        if len(active_fields) != 5 or active_fields[1:] != ["1", "3", "3", "0"]:
            raise RuntimeError("USB motor command was not applied correctly: " + active_status)

        time.sleep(0.7)
        serial_port.write(b"STATUS\n")
        stopped_status = read_status(serial_port, 1.0)
        stopped_fields = stopped_status.split(",")
        if len(stopped_fields) != 5 or stopped_fields[1] != "0" or stopped_fields[3:] != ["0", "0"]:
            raise RuntimeError("USB heartbeat timeout did not stop both motors: " + stopped_status)

        serial_port.write(b"UFO,0,0\n")


def run_self_test():
    image_path = micropython_image_path()
    if not image_path.is_file() or sha256(image_path) != MICROPYTHON_SHA256:
        raise RuntimeError("Embedded MicroPython self-test failed")
    for name in FIRMWARE_FILES:
        if not (resource_dir() / name).is_file():
            raise RuntimeError("Embedded UFO firmware self-test failed: " + name)
    run_esptool(["version"])
    print("SELF_TEST_OK:", MICROPYTHON_VERSION, MICROPYTHON_SHA256)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", help="Optional COM port override, for example COM5")
    parser.add_argument("--no-pause", action="store_true", help="Do not wait for Enter before closing")
    parser.add_argument("--self-test", action="store_true", help="Verify embedded resources without using a board")
    args = parser.parse_args()

    os.system("")
    print("=" * 64)
    print(APP_TITLE)
    print("Dual control firmware: native BLE + direct USB serial")
    print("Embedded environment: MicroPython", MICROPYTHON_VERSION, "for ESP32-C3")
    print("Muse and XToys services will be removed")
    print("=" * 64)

    if args.self_test:
        try:
            run_self_test()
            return 0
        except Exception as exc:
            print("SELF_TEST_FAILED:", exc)
            return 1

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = app_dir() / "backup" / timestamp
    verify_dir = backup_dir / "readback"

    try:
        port_info = detect_port(args.port)
        print("Device:", port_info.device, "-", port_info.description)
        print("Backup:", backup_dir)
        print("[1/5] Checking the MicroPython environment")
        port_info, environment_installed = ensure_micropython(
            port_info, micropython_image_path()
        )
        print("[2/5] Backing up current board files")
        if environment_installed:
            backup_dir.mkdir(parents=True, exist_ok=False)
            print("  skipped: no readable MicroPython filesystem existed before installation")
        else:
            backup_board(port_info.device, backup_dir)
        print("[3/5] Writing UFO-only firmware")
        upload_firmware(port_info.device, resource_dir())
        print("[4/5] Reading files back and verifying SHA-256")
        verify_board(port_info.device, resource_dir(), verify_dir)
        print("[5/5] Rebooting and checking BLE + USB operation")
        reboot_and_capture(port_info.device)
        print()
        print("SUCCESS: MicroPython and BLE + USB firmware were verified.")
        print("The board is advertising as UFO-ESP and accepting USB heartbeats.")
        exit_code = 0
    except Exception as exc:
        print()
        print("FAILED:", exc)
        print("The backup directory is:", backup_dir)
        exit_code = 1

    if not args.no_pause:
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
