# main.py - 诊断测试版
# 仅注册 UFOPlayer BLE 服务，详尽打印每次收到的数据
from motor import motor
from machine import Pin, Timer
from time import sleep_ms
import ubluetooth

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

# ---------- BLE UUID（仅 UFOPlayer）----------
UFO_SERVICE_UUID = ubluetooth.UUID('40ee0200-63ec-4b7f-8ce7-712efd55b90e')
UFO_CHAR_UUID = ubluetooth.UUID('40ee0202-63ec-4b7f-8ce7-712efd55b90e')


class UFOTW_BLE_TEST:
    def __init__(self, name="UFO-TW"):
        self.stby_pin = Pin(10, Pin.OUT)
        self.stby_pin.on()

        self.m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=self.stby_pin)
        self.m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=self.stby_pin)

        self.led = Pin(8, Pin.OUT)
        self.timer1 = Timer(0)
        self.name = name
        self.speed = [0, 0]
        self.write_count = 0  # 写入次数计数器

        self.ble = ubluetooth.BLE()
        self.ble.active(True)
        self.ble.config(gap_name=name)
        self.ble.irq(self.ble_irq)
        self.register()
        self.advertiser()
        self.disconnected()

        print("\n" + "=" * 56)
        print("  TEST FIRMWARE - UFOPlayer Diagnostic Mode")
        print("  Monitoring BLE writes for direction bit (bit7)")
        print("=" * 56 + "\n")

    def connected(self):
        print("[EVENT] CONNECTED")
        self.timer1.init(period=100, mode=Timer.PERIODIC, callback=self.speedset)
        self.led.value(1)

    def disconnected(self):
        print("[EVENT] DISCONNECTED")
        self.m1.stop()
        self.m2.stop()
        self.timer1.init(period=1000, mode=Timer.PERIODIC,
                         callback=lambda t: self.led.value(not self.led.value()))

    def ble_irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.connected()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.advertiser()
            self.disconnected()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            self._diagnose_write(attr_handle)

    def _diagnose_write(self, attr_handle):
        """详细的写入诊断"""
        self.write_count += 1
        try:
            buffer = self.ble.gatts_read(attr_handle)
        except Exception as e:
            print("[ERROR] gatts_read failed: {}".format(e))
            return

        print("-" * 56)
        print("WRITE #{:d} | handle={} | len={}".format(
            self.write_count, attr_handle, len(buffer)))

        if len(buffer) == 0:
            print("  [WARN] Empty buffer!")
            return

        # 原始 hex
        hex_str = ' '.join('{:02x}'.format(b) for b in buffer)
        print("  RAW hex: {}".format(hex_str))

        # 每个字节的二进制
        for i, b in enumerate(buffer):
            print("  Byte[{}]: 0x{:02x} ({:08b})".format(i, b, b))

        # 解析电机字节
        if len(buffer) >= 3:
            header = buffer[0]
            left_enc = buffer[1]
            right_enc = buffer[2]
            print("  Header: 0x{:02x}".format(header))
            self._decode_motor("LEFT", left_enc)
            self._decode_motor("RIGHT", right_enc)

            # 存储到 speed
            self.speed[0] = left_enc
            self.speed[1] = right_enc

            # 立即执行一次，确认方向
            l_dir = "REV" if (left_enc & 0x80) else "FWD"
            l_spd = left_enc & 0x7f
            r_dir = "REV" if (right_enc & 0x80) else "FWD"
            r_spd = right_enc & 0x7f
            print("  --> MOTOR: L={}:{} R={}:{}".format(l_dir, l_spd, r_dir, r_spd))
        else:
            print("  [WARN] Buffer too short, expected >=3 bytes")

        print("-" * 56)

    def _decode_motor(self, label, value):
        """解码单个电机控制字节"""
        direction = (value & 0x80) >> 7
        speed_raw = value & 0x7f
        duty = int(speed_raw * 1023 / 127)
        dir_str = "REVERSE (IN1=0,IN2=1)" if direction else "FORWARD (IN1=1,IN2=0)"

        print("  {} motor: 0x{:02x}".format(label, value))
        print("    bit7  = {} --> {}  <==== CHECK THIS!".format(direction, dir_str))
        print("    bit0-6 = {} (duty={})".format(speed_raw, duty))

    def register(self):
        # 仅注册 UFOPlayer 服务
        ufo_service = (
            UFO_SERVICE_UUID,
            (
                (UFO_CHAR_UUID, ubluetooth.FLAG_WRITE),
            )
        )
        ((self.rx,),) = self.ble.gatts_register_services((ufo_service,))
        print("[INIT] Service registered, rx handle={}".format(self.rx))

    def advertiser(self):
        name = bytes(self.name, 'UTF-8')
        adv_data = bytearray(b'\x02\x01\x02') + \
                   bytearray((len(name) + 1, 0x09)) + name
        self.ble.gap_advertise(300, adv_data=adv_data)
        print("[INIT] Advertising as '{}'".format(self.name))

    def speedset(self, t):
        self.m1.rorate(self.speed[0])
        self.m2.rorate(self.speed[1])


if __name__ == "__main__":
    ble = UFOTW_BLE_TEST()
    while True:
        sleep_ms(100)