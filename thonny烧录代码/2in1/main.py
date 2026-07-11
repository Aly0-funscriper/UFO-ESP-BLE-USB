# main.py - 2in1 整合版 (v2)
# 同时兼容 UFOPlayer 和 XToys，无需重新烧录
# 增强连接鲁棒性：拒绝重复连接、快速广播、定时器安全操作
from motor import motor
from machine import Pin, Timer
from time import sleep_ms
import ubluetooth

# ---------- BLE 事件常量 ----------
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

# ---------- 广告参数 ----------
_ADV_INTERVAL_US = const(50000)  # 50ms 快速广播，提高被发现速度

# ---------- BLE UUID 定义 ----------
UFO_SERVICE_UUID = ubluetooth.UUID('40ee0200-63ec-4b7f-8ce7-712efd55b90e')
UFO_CHAR_UUID = ubluetooth.UUID('40ee0202-63ec-4b7f-8ce7-712efd55b90e')

XTOYS_SERVICE_UUID = ubluetooth.UUID('40ee1111-63ec-4b7f-8ce7-712efd55b90e')
XTOYS_CHAR_UUID = ubluetooth.UUID('40ee2222-63ec-4b7f-8ce7-712efd55b90e')


class UFOTW_BLE:
    def __init__(self, name="UFO-TW"):
        # ---------- 硬件初始化 ----------
        self.stby_pin = Pin(10, Pin.OUT)
        self.stby_pin.on()

        self.m1 = motor(pin1=1, pin2=2, pwm_pin=3, stby_pin=self.stby_pin)
        self.m2 = motor(pin1=4, pin2=5, pwm_pin=6, stby_pin=self.stby_pin)

        # ---------- 状态变量 ----------
        self.led = Pin(8, Pin.OUT)
        self.timer1 = Timer(0)
        self.name = name
        self.speed = [0, 0]
        self._conn_handle = None  # 当前连接的 handle，用于拒绝重复连接

        # ---------- BLE 初始化 ----------
        self.ble = ubluetooth.BLE()
        self.ble.active(True)

        # 设置发射功率为最大值（ESP32: 0=最低, 3=最高）
        try:
            self.ble.config(tx_power=4)  # 4=最大发射功率，改善连接稳定性
        except Exception:
            pass  # 某些固件版本不支持此参数，忽略

        self.ble.config(gap_name=name)
        self.ble.irq(self.ble_irq)
        self.register()
        self._start_advertising()

        self._set_disconnected_state()

    # ==================== BLE 事件处理 ====================
    def _set_connected_state(self):
        """切换到已连接状态"""
        self.m1.stop()
        self.m2.stop()
        self.speed = [0, 0]
        self.led.value(1)

        # 安全重启定时器
        try:
            self.timer1.deinit()
        except Exception:
            pass
        self.timer1.init(period=100, mode=Timer.PERIODIC, callback=self._speed_set)

    def _set_disconnected_state(self):
        """切换到断开状态：停电机、LED 慢闪"""
        self.m1.stop()
        self.m2.stop()
        self.speed = [0, 0]

        try:
            self.timer1.deinit()
        except Exception:
            pass
        self.timer1.init(period=1000, mode=Timer.PERIODIC,
                         callback=lambda t: self.led.value(not self.led.value()))

    def _handle_connect(self, conn_handle, _addr_type, _addr):
        """处理连接事件，拒绝重复连接"""
        if self._conn_handle is not None and self._conn_handle != conn_handle:
            # 已有连接，拒绝新的
            print("Rejecting duplicate connection (handle={})".format(conn_handle))
            try:
                self.ble.gap_disconnect(conn_handle)
            except Exception:
                pass
            return

        self._conn_handle = conn_handle
        print("Connected (handle={})".format(conn_handle))
        self._set_connected_state()

    def _handle_disconnect(self, conn_handle):
        """处理断开事件"""
        if self._conn_handle == conn_handle:
            self._conn_handle = None
        print("Disconnected (handle={})".format(conn_handle))
        self._set_disconnected_state()
        self._start_advertising()

    def _handle_write(self, conn_handle, attr_handle):
        """处理 GATT 写入事件"""
        try:
            buffer = self.ble.gatts_read(attr_handle)
        except Exception:
            print("ERROR: gatts_read failed for handle={}".format(attr_handle))
            return

        print("WRITE: handle={} data={}".format(
            attr_handle,
            ' '.join('{:02x}'.format(b) for b in buffer)))

        if len(buffer) >= 3:
            self.speed[0] = buffer[1]
            self.speed[1] = buffer[2]

    def ble_irq(self, event, data):
        """BLE 中断回调（注意：在硬件中断上下文执行，避免阻塞）"""
        if event == _IRQ_CENTRAL_CONNECT:
            # data: (conn_handle, addr_type, addr)
            self._handle_connect(*data)

        elif event == _IRQ_CENTRAL_DISCONNECT:
            # data: (conn_handle, addr_type, addr)
            self._handle_disconnect(data[0] if isinstance(data, tuple) else data)

        elif event == _IRQ_GATTS_WRITE:
            # data: (conn_handle, attr_handle)
            self._handle_write(*data)

        elif event == _IRQ_MTU_EXCHANGED:
            # data: (conn_handle, mtu)
            mtu = data[1] if isinstance(data, tuple) else 23
            print("MTU exchanged: {}".format(mtu))

    # ==================== BLE 服务注册 ====================
    def register(self):
        ufo_service = (
            UFO_SERVICE_UUID,
            ((UFO_CHAR_UUID, ubluetooth.FLAG_WRITE),)
        )
        xtoys_service = (
            XTOYS_SERVICE_UUID,
            ((XTOYS_CHAR_UUID, ubluetooth.FLAG_WRITE),)
        )

        # UFO 必须在最后 → UFOPlayer 用 services.Last() 找特征
        services = (xtoys_service, ufo_service)
        result = self.ble.gatts_register_services(services)

        # result = (handle_xtoys, handle_ufo)
        self.rx_xtoys = result[0]
        self.rx_ufo = result[1]
        print("BLE services registered (xtoys={}, ufo={})".format(
            self.rx_xtoys, self.rx_ufo))

    # ==================== 蓝牙广播 ====================
    def _start_advertising(self):
        """启动 BLE 广播（先停止旧广播，防止冲突）"""
        try:
            self.ble.gap_advertise(None)  # 停止正在进行的广播
        except Exception:
            pass
        sleep_ms(50)  # 给 BLE 栈一点时间释放资源

        name = bytes(self.name, 'UTF-8')
        adv_data = bytearray(b'\x02\x01\x02') + \
                   bytearray((len(name) + 1, 0x09)) + name
        self.ble.gap_advertise(_ADV_INTERVAL_US, adv_data=adv_data)
        print("Advertising started")

    # ==================== 电机控制 ====================
    def _speed_set(self, t):
        """定时器回调：将 speed 应用到电机"""
        self.m1.rorate(self.speed[0])
        self.m2.rorate(self.speed[1])


if __name__ == "__main__":
    ble = UFOTW_BLE()
    while True:
        sleep_ms(100)
