# 一键刷入器源码

发布版 EXE 已内置：

- 官方稳定版 MicroPython v1.29.0 ESP32-C3 固件；
- `firmware` 文件夹中的 `boot.py`、`main.py` 和 `motor.py`。

功能：

- 自动识别 Espressif USB 串口；
- 检测板上是否存在可用的 MicroPython REPL；
- 未检测到环境时，通过内置 esptool 擦除并安装内置 MicroPython；
- 已检测到环境时跳过环境安装，不擦除 Flash；
- 刷入前备份板上文件；
- 上传后读回并校验 SHA-256；
- 删除旧的 `muse_broadcast.py`（如果存在）；
- 验证 BLE/USB 启动日志；
- 自动测试 USB 低速控制与 500ms 心跳超时停机。

构建环境为 Python 3.12，依赖见 `requirements.txt`。示例：

```powershell
python -m pip install -r requirements.txt
pyinstaller --clean --onefile --console `
  --name UFO-ESP-BLE-USB-OneClick-Flasher `
  --add-data "firmware;firmware" `
  --add-data "micropython;micropython" `
  --collect-all esptool `
  --hidden-import mpremote.transport_serial `
  --hidden-import serial.tools.list_ports_windows `
  flasher.py
```

首次环境安装会擦除整块 Flash。若开发板不能自动进入下载模式，请按住 `BOOT`，短按并松开 `RESET`，然后松开 `BOOT` 再重新运行刷入器。
