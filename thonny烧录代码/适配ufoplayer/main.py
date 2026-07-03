# main.py
from motor import motor
from machine import Pin, Timer
from time import sleep_ms
import ubluetooth

_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

class UFOTW_BLE:
    def __init__(self, name="UFO-TW"):
        # ---------- 硬件初始化 ----------
        # TB6612FNG 的 STBY 引脚（根据实际接线修改）
        self.stby_pin = Pin(10, Pin.OUT)
        self.stby_pin.on()   # 必须拉高，驱动器才能工作

        # 初始化两个电机（根据您的接线调整引脚）
        # 电机A (左): 方向=GPIO1,2; PWM=GPIO3
        self.m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=self.stby_pin)
        # 电机B (右): 方向=GPIO4,5; PWM=GPIO6
        self.m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=self.stby_pin)

        # ---------- BLE 初始化 ----------
        self.led = Pin(8, Pin.OUT)
        self.timer1 = Timer(0)
        self.name = name
        self.speed = [0, 0]          # 存储直接来自UFOPlayer的编码值

        self.ble = ubluetooth.BLE()
        self.ble.active(True)
        self.ble.config(gap_name=name)

        self.ble.irq(self.ble_irq)
        self.register()               # 注册 BLE 服务（UUID匹配UFOPlayer）
        self.advertiser()

        # 初始状态为断开，启动LED闪烁
        self.disconnected()

    # ---------- BLE 事件处理 ----------
    def connected(self):
        print("Connected - LED on, timer started")
        self.timer1.init(period=100, mode=Timer.PERIODIC, callback=self.speedset)
        self.led.value(1)

    def disconnected(self):
        print("Disconnected - motors stop, LED blink")
        self.m1.stop()
        self.m2.stop()
        # 断开后 LED 慢闪
        self.timer1.init(period=1000, mode=Timer.PERIODIC,
                         callback=lambda t: self.led.value(not self.led.value()))

    def ble_irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.connected()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.advertiser()
            self.disconnected()
        elif event == _IRQ_GATTS_WRITE:
            buffer = self.ble.gatts_read(self.rx)
            # 调试输出原始数据
            print("RAW: len={}, hex={}".format(len(buffer), ' '.join('{:02x}'.format(b) for b in buffer)))
            # UFOPlayer 数据格式: [0x05, left_encoded, right_encoded]
            # left_encoded/right_encoded 已经是电机控制字节（bit7=方向，bit0-6=速度）
            if len(buffer) >= 3:
                left_encoded = buffer[1]
                right_encoded = buffer[2]
                print("Encoded L={:02x}, R={:02x}".format(left_encoded, right_encoded))
                # 直接保存编码值
                self.speed[0] = left_encoded
                self.speed[1] = right_encoded

    # ---------- BLE 服务注册（匹配UFOPlayer）----------
    def register(self):
        # 服务 UUID: 40ee0200-63ec-4b7f-8ce7-712efd55b90e
        service_uuid = ubluetooth.UUID('40ee0200-63ec-4b7f-8ce7-712efd55b90e')
        # 特征 UUID: 40ee0202-63ec-4b7f-8ce7-712efd55b90e
        rx_uuid = ubluetooth.UUID('40ee0202-63ec-4b7f-8ce7-712efd55b90e')
        services = (
            service_uuid,
            (
                (rx_uuid, ubluetooth.FLAG_WRITE),   # 仅需可写
            )
        )
        ((self.rx,),) = self.ble.gatts_register_services((services,))

    # ---------- 蓝牙广播 ----------
    def advertiser(self):
        name = bytes(self.name, 'UTF-8')
        adv_data = bytearray('\x02\x01\x02', 'UTF-8') + \
                   bytearray((len(name) + 1, 0x09), 'UTF-8') + name
        self.ble.gap_advertise(300, adv_data)

    # ---------- 定时器回调：设置电机速度 ----------
    def speedset(self, t):
        # 调试输出当前速度值
        print("speedset: m1={:02x}, m2={:02x}".format(self.speed[0], self.speed[1]))
        self.m1.rorate(self.speed[0])
        self.m2.rorate(self.speed[1])

if __name__ == "__main__":
    ble = UFOTW_BLE()
    while True:
        sleep_ms(100)