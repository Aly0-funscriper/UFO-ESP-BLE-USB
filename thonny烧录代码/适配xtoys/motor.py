# motor.py
from machine import Pin, PWM

class motor:
    def __init__(self, pin1, pin2, pwm_pin, stby_pin=None):
        """
        初始化电机对象 (针对 TB6612FNG)
        :param pin1: 方向控制引脚 IN1 (例如, 对于电机A是 AIN1)
        :param pin2: 方向控制引脚 IN2 (例如, 对于电机A是 AIN2)
        :param pwm_pin: 速度控制引脚 PWM (例如, 对于电机A是 PWMA)
        :param stby_pin: (可选) 整个驱动器的待机引脚 STBY。如果传入，会在初始化时自动启用。
        """
        # TB6612FNG 的方向控制引脚为普通的GPIO输出
        self.p1 = Pin(pin1, Pin.OUT)
        self.p2 = Pin(pin2, Pin.OUT)

        # TB6612FNG 的速度控制需要一个单独的PWM引脚
        self.pwm = PWM(Pin(pwm_pin, Pin.OUT))
        self.pwm.freq(20000)  # 设置PWM频率为20kHz，高于人耳可听范围，减少噪音[citation:10]

        # 保存STBY引脚对象，以便在类内部使用
        self.stby_pin = stby_pin
        if self.stby_pin:
            # 如果提供了STBY引脚，立即将其拉高，使驱动器退出待机模式
            self.stby_pin.on()

        # 初始化时停止电机
        self.stop()

    def deinit(self):
        """释放PWM资源"""
        self.pwm.deinit()
        # 可以将方向引脚也恢复为输入以节省功耗，但不是必须的
        # self.p1.init(mode=Pin.IN)
        # self.p2.init(mode=Pin.IN)

    def stop(self):
        """停止电机：将两个方向引脚设置为同一电平（例如都设为0），并设置PWM占空比为0"""
        self.p1.off()  # 或 self.p1.value(0)
        self.p2.off()  # 或 self.p2.value(0)
        self.pwm.duty(0)

    def rorate(self, value):
        """
        控制电机旋转 (针对 TB6612FNG)
        与DRV8833不同，TB6612FNG通过IN1/IN2控制方向，通过PWM控制速度。
        沿用原协议的编码方式：最高位（0x80）表示方向，低7位表示速度。
        :param value: 控制字节，例如 0x45 (69) 表示正向速度69，0x85 (133) 表示反向速度5
        """
        # 解析速度和方向
        speed_raw = value & 0x7f
        # 将0-127的原始速度值映射到PWM的duty范围 0-1023
        # 注意：有些电机需要一定的启动占空比，如果电机不转，可以适当提高speed_duty的最小值
        speed_duty = int(speed_raw * 1023 / 127)

        # 判断方向
        if value & 0x80:  # 最高位为1，表示反向
            # 反转: IN1=0, IN2=1, 通过PWM控制速度
            self.p1.off()
            self.p2.on()
            self.pwm.duty(speed_duty)
        else:  # 最高位为0，表示正向
            # 正转: IN1=1, IN2=0, 通过PWM控制速度
            self.p1.on()
            self.p2.off()
            self.pwm.duty(speed_duty)

# 使用示例 (这部分会在 main.py 中实现)
if __name__ == "__main__":
    # 这是一个简化的测试，假设STBY连接到GPIO 10
    stby = Pin(10, Pin.OUT)
    stby.on() # 启用驱动器

    # 初始化电机A，使用GPIO 1,2作为方向，GPIO 3作为PWM
    m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=stby)
    # 初始化电机B，使用GPIO 4,5作为方向，GPIO 6作为PWM
    m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=stby)

    # 测试正转 (速度 63，约50%)
    m1.rorate(63)
    m2.rorate(63)
    time.sleep(2)

    # 测试反转 (速度 63，约50%)
    m1.rorate(0x80 | 63) # 0x80 是 128，加上速度值
    m2.rorate(0x80 | 63)
    time.sleep(2)

    # 停止
    m1.stop()
    m2.stop()
    m1.deinit()
    m2.deinit()
