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
        # --- 修复Bug：硬件初始化放在最前面 ---
        # 1. 初始化STBY引脚，使TB6612FNG全程处于工作状态
        #    选择一个GPIO，例如开发板上的GPIO 10
        self.stby_pin = Pin(10, Pin.OUT)
        self.stby_pin.on()  # 必须拉高，驱动器才能工作

        # 2. 初始化两个电机 (适配TB6612FNG)
        #    根据你的接线修改引脚号！
        #    电机A: 方向=GPIO 1和2, PWM=GPIO 3
        self.m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=self.stby_pin)
        #    电机B: 方向=GPIO 4和5, PWM=GPIO 6
        self.m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=self.stby_pin)
        # --- 硬件初始化结束 ---

        # print("starting ble")
        self.led = Pin(8, Pin.OUT)
        self.timer1 = Timer(0)
        self.name = name
        self.speed = [0, 0]

        self.ble = ubluetooth.BLE()
        self.ble.active(True)
        self.ble.config(gap_name=name)

        # 注意：在调用connected()之前，m1和m2现在已存在，是安全的
        self.connected()
        self.disconnected()
        self.ble.irq(self.ble_irq)
        self.register()
        self.advertiser()

        # 原代码此处重复初始化了m1和m2，已删除
        # self.m1=motor(1,2)
        # self.m2=motor(3,4)

    def connected(self):
        # 连接时：启动速度控制的定时器，点亮LED
        self.timer1.init(period=100, mode=Timer.PERIODIC, callback=self.speedset)
        self.led.value(1)

    def disconnected(self):
        # 断开时：停止电机，熄灭LED并开始闪烁
        self.m1.stop()
        self.m2.stop()
        self.timer1.init(period=1000, mode=Timer.PERIODIC, callback=lambda t: self.led.value(not self.led.value()))

    def ble_irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.connected()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.advertiser()
            self.disconnected()
        elif event == _IRQ_GATTS_WRITE:
            # 读取蓝牙接收到的数据，格式为 [0, speed1, speed2]
            buffer = self.ble.gatts_read(self.rx)
            if len(buffer) >= 3:
                self.speed = [buffer[1], buffer[2]]
            # 原代码中全局变量values未被使用，已删除

    def register(self):
        # BLE服务注册，与原来保持一致
        service_uuid = ubluetooth.UUID('40ee1111-63ec-4b7f-8ce7-712efd55b90e')
        rx_uuid = ubluetooth.UUID('40ee2222-63ec-4b7f-8ce7-712efd55b90e')
        services = ( service_uuid, (
                ( rx_uuid , ubluetooth.FLAG_WRITE ),
            )
        )
        ((self.rx,),) = self.ble.gatts_register_services( (services,) )

    def advertiser(self):
        # 蓝牙广播，与原来保持一致
        name = bytes(self.name, 'UTF-8')
        adv_data = bytearray('\x02\x01\x02', 'UTF-8') + bytearray((len(name) + 1, 0x09), 'UTF-8') + name
        self.ble.gap_advertise(300, adv_data)

    def speedset(self, t):
        # 定时器回调，设置电机速度
        self.m1.rorate(self.speed[0])
        self.m2.rorate(self.speed[1])

if __name__ == "__main__":
    ble = UFOTW_BLE()
    while True:
        sleep_ms(100)
