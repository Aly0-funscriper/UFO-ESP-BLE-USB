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
from mpremote.main import main as mpremote_main


APP_TITLE = "UFO-ESP BLE + USB one-click flasher"
FIRMWARE_FILES = ("motor.py", "main.py", "boot.py")
OBSOLETE_FILES = ("muse_broadcast.py",)
EXPECTED_VID = 0x303A


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "firmware"


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
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                status = mpremote_main()
        else:
            status = mpremote_main()
    except SystemExit as exc:
        status = int(exc.code or 0)
    finally:
        sys.argv = previous_argv

    if status and not tolerate_failure:
        raise RuntimeError("mpremote failed: " + " ".join(map(str, arguments)))
    return status == 0


def detect_port(requested_port=None):
    ports = list(list_ports.comports())
    if requested_port:
        match = next((item for item in ports if item.device.upper() == requested_port.upper()), None)
        if match is None:
            raise RuntimeError("Requested serial port was not found: " + requested_port)
        return match

    espressif = [item for item in ports if item.vid == EXPECTED_VID]
    if len(espressif) == 1:
        return espressif[0]
    if not espressif:
        usb_ports = [item for item in ports if item.device.upper() != "COM1" and item.vid is not None]
        if len(usb_ports) == 1:
            return usb_ports[0]
        raise RuntimeError("No Espressif USB serial device was found. Connect the board and try again.")
    raise RuntimeError("More than one Espressif board is connected. Disconnect the extra board and try again.")


def backup_board(port: str, backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=False)
    required = {"boot.py", "main.py", "motor.py"}
    for name in (*FIRMWARE_FILES, *OBSOLETE_FILES):
        destination = backup_dir / name
        print("  backing up", name)
        copied = run_mpremote(
            ["connect", port, "+", "fs", "cp", ":" + name, destination],
            tolerate_failure=name not in required,
        )
        if name in required and not copied:
            raise RuntimeError("Could not back up required board file: " + name)
        if name not in required and not copied:
            print("    not present (already removed)")


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


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", help="Optional COM port override, for example COM5")
    parser.add_argument("--no-pause", action="store_true", help="Do not wait for Enter before closing")
    args = parser.parse_args()

    os.system("")
    print("=" * 64)
    print(APP_TITLE)
    print("Dual control firmware: native BLE + direct USB serial")
    print("Muse and XToys services will be removed")
    print("=" * 64)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = app_dir() / "backup" / timestamp
    verify_dir = backup_dir / "readback"

    try:
        port_info = detect_port(args.port)
        print("Device:", port_info.device, "-", port_info.description)
        print("Backup:", backup_dir)
        print("[1/4] Backing up current board files")
        backup_board(port_info.device, backup_dir)
        print("[2/4] Writing UFO-only firmware")
        upload_firmware(port_info.device, resource_dir())
        print("[3/4] Reading files back and verifying SHA-256")
        verify_board(port_info.device, resource_dir(), verify_dir)
        print("[4/4] Rebooting and checking BLE + USB operation")
        reboot_and_capture(port_info.device)
        print()
        print("SUCCESS: BLE + USB firmware was installed and verified.")
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
