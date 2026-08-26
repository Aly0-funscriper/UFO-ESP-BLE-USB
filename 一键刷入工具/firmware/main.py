# UFO-ESP compatibility firmware
# Only the original UFO-TW GATT motor-control service is exposed.

from machine import Pin, Timer
from time import sleep_ms, ticks_add, ticks_diff, ticks_ms
import select
import sys
import ubluetooth

from motor import motor


_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

_ADV_INTERVAL_US = const(20000)
_MOTOR_UPDATE_MS = const(10)
_USB_HEARTBEAT_TIMEOUT_MS = const(500)
_SOURCE_SWITCH_STOP_MS = const(30)
_UFO_ADV_UUID_LE = bytes.fromhex('0eb955fd2e71e78c7f4bec630002ee40')

UFO_SERVICE_UUID = ubluetooth.UUID('40ee0200-63ec-4b7f-8ce7-712efd55b90e')
UFO_CHAR_UUID = ubluetooth.UUID('40ee0202-63ec-4b7f-8ce7-712efd55b90e')

DEBUG_BLE_WRITES = False


class UFOTW_BLE:
    def __init__(self, name='UFO-ESP'):
        self.stby_pin = Pin(10, Pin.OUT)
        self.stby_pin.on()

        self.m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=self.stby_pin)
        self.m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=self.stby_pin)

        self.led = Pin(8, Pin.OUT)
        self.led_timer = Timer(0)
        self.name = name
        self.ble_speed = [0, 0]
        self.usb_speed = [0, 0]
        self._conn_handle = None
        self._advertise_pending = False
        self._last_motor_update = ticks_ms()
        self._usb_last_packet = None
        self._usb_was_active = False
        self._source_stop_until = None
        self._usb_status_requested = False
        self._usb_rx = bytearray()
        self._usb_stream = sys.stdin.buffer
        self._usb_poll = select.poll()
        self._usb_poll.register(sys.stdin, select.POLLIN)

        self.ble = ubluetooth.BLE()
        self.ble.active(True)

        try:
            # Static random address: stable across advertising sessions.
            self.ble.config(addr_mode=1)
        except Exception:
            pass

        try:
            self.ble.config(tx_power=4)
        except Exception:
            pass

        self.ble.config(gap_name=name)
        self.ble.irq(self.ble_irq)
        self._register_ufo_service()
        self._set_disconnected_state()
        self._start_advertising()
        print('USB serial control ready (UFO,left,right)')

        try:
            addr_type, addr = self.ble.config('mac')
            print('BLE address type={} mac={}'.format(
                addr_type, ':'.join('{:02X}'.format(b) for b in bytes(addr))))
        except Exception:
            pass

    def _register_ufo_service(self):
        ufo_service = (
            UFO_SERVICE_UUID,
            ((UFO_CHAR_UUID, ubluetooth.FLAG_WRITE),)
        )
        result = self.ble.gatts_register_services((ufo_service,))
        self.rx_ufo = result[0][0]
        print('UFO service registered (handle={})'.format(self.rx_ufo))

    def _set_connected_state(self):
        self.ble_speed[0] = 0
        self.ble_speed[1] = 0
        if not self._is_usb_active(ticks_ms()):
            self.m1.stop()
            self.m2.stop()
        self.led.value(1)
        try:
            self.led_timer.deinit()
        except Exception:
            pass
        self._last_motor_update = ticks_ms()

    def _set_disconnected_state(self):
        self.ble_speed[0] = 0
        self.ble_speed[1] = 0
        if not self._is_usb_active(ticks_ms()):
            self.m1.stop()
            self.m2.stop()
        try:
            self.led_timer.deinit()
        except Exception:
            pass
        self.led_timer.init(
            period=1000,
            mode=Timer.PERIODIC,
            callback=lambda _timer: self.led.value(not self.led.value()))

    def _start_advertising(self):
        try:
            self.ble.gap_advertise(None)
        except Exception:
            pass

        sleep_ms(50)
        # The advertised name is ASCII. Avoid codec lookup because some
        # minimal MicroPython builds do not include the "UTF-8" alias.
        name = bytes([ord(char) for char in self.name])
        adv_data = (bytearray(b'\x02\x01\x02')
                    + bytearray((len(name) + 1, 0x09)) + name
                    + bytearray((17, 0x07)) + _UFO_ADV_UUID_LE)
        self.ble.gap_advertise(_ADV_INTERVAL_US, adv_data=adv_data)
        print('UFO advertising started')

    def _handle_connect(self, conn_handle, _addr_type, _addr):
        if self._conn_handle is not None and self._conn_handle != conn_handle:
            try:
                self.ble.gap_disconnect(conn_handle)
            except Exception:
                pass
            return

        self._conn_handle = conn_handle
        self._advertise_pending = False
        self._set_connected_state()
        print('Connected (handle={})'.format(conn_handle))

    def _handle_disconnect(self, conn_handle):
        if self._conn_handle == conn_handle:
            self._conn_handle = None
        self._set_disconnected_state()
        # Advertising calls can block, so defer them out of the BLE IRQ.
        self._advertise_pending = True
        print('Disconnected (handle={})'.format(conn_handle))

    def _handle_write(self, _conn_handle, attr_handle):
        if attr_handle != self.rx_ufo:
            return

        try:
            packet = self.ble.gatts_read(attr_handle)
        except Exception:
            return

        if len(packet) < 3:
            return

        self.ble_speed[0] = packet[1]
        self.ble_speed[1] = packet[2]

        if DEBUG_BLE_WRITES:
            print('UFO write: {:02x} {:02x} {:02x}'.format(
                packet[0], packet[1], packet[2]))

    def ble_irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._handle_connect(*data)
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._handle_disconnect(data[0] if isinstance(data, tuple) else data)
        elif event == _IRQ_GATTS_WRITE:
            self._handle_write(*data)
        elif event == _IRQ_MTU_EXCHANGED:
            pass

    def _is_usb_active(self, now):
        return (self._usb_last_packet is not None
                and ticks_diff(now, self._usb_last_packet) <= _USB_HEARTBEAT_TIMEOUT_MS)

    def _handle_usb_line(self, line):
        try:
            text = line.decode('ascii').strip()
            if text == 'STATUS':
                self._usb_status_requested = True
                return
            fields = text.split(',')
            if len(fields) != 3 or fields[0] != 'UFO':
                return
            left = int(fields[1])
            right = int(fields[2])
            if not (0 <= left <= 255 and 0 <= right <= 255):
                return
        except Exception:
            return

        self.usb_speed[0] = left
        self.usb_speed[1] = right
        self._usb_last_packet = ticks_ms()

    def _poll_usb_serial(self):
        # ASCII framing avoids Ctrl-C/Ctrl-D bytes interfering with the
        # MicroPython USB REPL: UFO,0,255\n
        while self._usb_poll.poll(0):
            chunk = self._usb_stream.read(1)
            if not chunk:
                break

            value = chunk[0]
            if value in (10, 13):
                if self._usb_rx:
                    self._handle_usb_line(bytes(self._usb_rx))
                    self._usb_rx = bytearray()
            elif 32 <= value <= 126:
                if len(self._usb_rx) < 32:
                    self._usb_rx.append(value)
                else:
                    self._usb_rx = bytearray()
            else:
                self._usb_rx = bytearray()

    def _select_target(self, now):
        usb_active = self._is_usb_active(now)
        if usb_active != self._usb_was_active:
            # Always cross a stopped state when ownership changes. This avoids
            # a stale BLE direction being replaced by USB (or vice versa)
            # without a controlled break.
            self.m1.stop()
            self.m2.stop()
            self._source_stop_until = ticks_add(now, _SOURCE_SWITCH_STOP_MS)
            self._usb_was_active = usb_active

        if self._source_stop_until is not None:
            if ticks_diff(now, self._source_stop_until) < 0:
                return 0, 0
            self._source_stop_until = None

        if usb_active:
            return self.usb_speed[0], self.usb_speed[1]
        if self._conn_handle is not None:
            return self.ble_speed[0], self.ble_speed[1]
        return 0, 0

    def process(self):
        self._poll_usb_serial()

        if self._advertise_pending and self._conn_handle is None:
            self._advertise_pending = False
            self._start_advertising()

        now = ticks_ms()
        if (self._conn_handle is not None
                or self._usb_last_packet is not None):
            if ticks_diff(now, self._last_motor_update) < _MOTOR_UPDATE_MS:
                return
            self._last_motor_update = now
            left, right = self._select_target(now)
            self.m1.update(left)
            self.m2.update(right)

            if self._usb_status_requested:
                self._usb_status_requested = False
                print('UFO_STATUS,{},{},{},{}'.format(
                    1 if self._is_usb_active(now) else 0,
                    self.usb_speed[0],
                    self.m1._applied_value,
                    self.m2._applied_value))


if __name__ == '__main__':
    ble = UFOTW_BLE()
    while True:
        ble.process()
        sleep_ms(5)
