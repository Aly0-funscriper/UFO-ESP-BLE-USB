# UFO-ESP BLE + USB 双通道固件

这是 [Mistpeach/fakeUFO](https://github.com/Mistpeach/fakeUFO) 的非商业共享衍生版本，面向 ESP32-C3 + TB6612FNG 双路 UFO-TW 兼容控制板。

本分支的主要改动：

- 只保留原始 UFO-TW BLE GATT 服务，移除 XToys/Muse 协议；
- 同时支持原生 BLE 和 USB 数据线串口控制；
- USB 采用 `UFO,left,right\n` ASCII 心跳协议，115200 波特率；
- USB 心跳有效时优先，连续 500ms 无心跳自动停止双路；
- BLE/USB 控制权切换时先经过停止状态；
- 电机每 10ms 更新，快速换向时加入 20ms 安全死区；
- 提供 Windows 一键刷入 EXE，自动备份、写入、读回校验和实板自检。
- 一键刷入 EXE 内置官方 MicroPython v1.29.0 ESP32-C3 环境和 esptool：未检测到环境时自动安装，已安装时直接继续刷 UFO 固件。

## 下载

请从 [GitHub Releases](https://github.com/Aly0-funscriper/UFO-ESP-BLE-USB/releases) 下载最新的一键刷入包。

## 一键刷入

1. 关闭 MultiFunPlayer、Thonny 和其他占用串口的软件。
2. 用 USB 数据线连接 ESP32-C3。
3. 运行 `UFO-ESP-BLE-USB-OneClick-Flasher.exe`。
4. 刷入器先检测 MicroPython；已安装则跳过，未安装则自动擦除并安装内置环境。
5. 环境可用后，刷入器会备份旧文件并上传 UFO 固件。
6. 最后会短暂以约 2% 速度测试左路，并验证 500ms 失联后双路停止。

只有检测不到 MicroPython 时才会执行整片擦除。若开发板无法自动进入下载模式，刷入器会提示使用 `BOOT` + `RESET` 进入下载模式。

开发板刷入后以 `UFO-ESP` 广播。对应的 MFP 版本位于 [Aly0-funscriper/MultiFunPlayer-UFO-TW](https://github.com/Aly0-funscriper/MultiFunPlayer-UFO-TW)。

## 协议

BLE 服务：

```text
Service:        40ee0200-63ec-4b7f-8ce7-712efd55b90e
Characteristic: 40ee0202-63ec-4b7f-8ce7-712efd55b90e
```

USB 串口：

```text
UFO,left,right\n
```

`left` 和 `right` 是固件控制字节 `0..255`。最高位表示方向，低 7 位表示速度。`0` 表示停止。

## 源码位置

- 固件：`thonny烧录代码/2in1/`
- 一键刷入器：`一键刷入工具/`

## 许可与署名

本项目沿用原项目的 [CC BY-NC-SA 4.0](LICENSE) 许可证：必须署名、禁止商业使用，并以相同许可证共享衍生版本。

原项目：[Mistpeach/fakeUFO](https://github.com/Mistpeach/fakeUFO)
