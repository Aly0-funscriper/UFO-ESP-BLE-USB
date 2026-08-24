# This file is executed on every boot.
# import esp
# esp.osdebug(None)
# import webrepl
# webrepl.start()

from machine import Pin

# 上电时把这些 GPIO 全部拉低，避免浮空或意外驱动电机
pins = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

for p in pins:
    gpio_pin = Pin(p, Pin.OUT)
    gpio_pin.value(0)
