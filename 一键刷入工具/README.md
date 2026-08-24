# 一键刷入器源码

发布版 EXE 已内置 `firmware` 文件夹中的 `boot.py`、`main.py` 和 `motor.py`。

功能：

- 自动识别 Espressif USB 串口；
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
  --hidden-import mpremote.transport_serial `
  --hidden-import serial.tools.list_ports_windows `
  flasher.py
```
