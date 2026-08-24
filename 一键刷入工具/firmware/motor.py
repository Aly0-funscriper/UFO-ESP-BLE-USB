# motor.py
from machine import Pin, PWM

class motor:
    # Called every 10 ms by main.py. Two stopped ticks give the TB6612 and the
    # motor about 20 ms to discharge before the direction pins are reversed.
    REVERSAL_DEAD_TICKS = 2

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
        self.pwm.freq(20000)  # 设置PWM频率为20kHz，高于人耳可听范围，减少噪音

        # 保存STBY引脚对象，以便在类内部使用
        self.stby_pin = stby_pin
        if self.stby_pin:
            # 如果提供了STBY引脚，立即将其拉高，使驱动器退出待机模式
            self.stby_pin.on()

        self._applied_value = 0
        self._reversal_dead_ticks = 0

        # 初始化时停止电机
        self.stop()

    def deinit(self):
        """释放PWM资源"""
        self.pwm.deinit()

    def stop(self):
        """停止电机：将两个方向引脚设置为同一电平（例如都设为0），并设置PWM占空比为0"""
        self.pwm.duty(0)
        self.p1.off()
        self.p2.off()

        self._applied_value = 0
        self._reversal_dead_ticks = 0

    def _output_stop(self):
        """Stop PWM without clearing the direction-change state machine."""
        self.pwm.duty(0)
        self.p1.off()
        self.p2.off()

    def update(self, value):
        """Apply the latest target with a short dead time on direction reversal."""
        value = int(value) & 0xff
        target_speed = value & 0x7f

        if target_speed == 0:
            if self._applied_value != 0 or self._reversal_dead_ticks != 0:
                self.stop()
            return

        if self._reversal_dead_ticks > 0:
            self._output_stop()
            self._reversal_dead_ticks -= 1
            if self._reversal_dead_ticks > 0:
                return

            # The newest target wins if BLE changed it during the dead time.
            self._apply(value)
            return

        applied_speed = self._applied_value & 0x7f
        direction_changed = applied_speed > 0 and ((self._applied_value ^ value) & 0x80)
        if direction_changed:
            self._output_stop()
            self._applied_value = 0
            self._reversal_dead_ticks = self.REVERSAL_DEAD_TICKS
            return

        if value != self._applied_value:
            self._apply(value)

    def rorate(self, value):
        """Backward-compatible alias for the safe non-blocking update path."""
        self.update(value)

    def _apply(self, value):
        """
        控制电机旋转 (针对 TB6612FNG)
        :param value: 控制字节，最高位（0x80）表示方向，低7位表示速度。
        """
        # 解析速度和方向
        speed_raw = value & 0x7f
        # 将0-127的原始速度值映射到PWM的duty范围 0-1023
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

        self._applied_value = value
