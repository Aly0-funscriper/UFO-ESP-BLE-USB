# motor.py (test version - no debug prints, quiet)
from machine import Pin, PWM

class motor:
    def __init__(self, pin1, pin2, pwm_pin, stby_pin=None):
        self.p1 = Pin(pin1, Pin.OUT)
        self.p2 = Pin(pin2, Pin.OUT)
        self.pwm = PWM(Pin(pwm_pin, Pin.OUT))
        self.pwm.freq(20000)

        self.stby_pin = stby_pin
        if self.stby_pin:
            self.stby_pin.on()

        self.stop()

    def deinit(self):
        self.pwm.deinit()

    def stop(self):
        self.p1.off()
        self.p2.off()
        self.pwm.duty(0)

    def rorate(self, value):
        speed_raw = value & 0x7f
        speed_duty = int(speed_raw * 1023 / 127)

        if value & 0x80:
            self.p1.off()
            self.p2.on()
            self.pwm.duty(speed_duty)
        else:
            self.p1.on()
            self.p2.off()
            self.pwm.duty(speed_duty)