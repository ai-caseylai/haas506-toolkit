<div align="center">

# HaaS506 Toolkit

### 讓 Mac 用戶也能輕鬆開發 HaaS506 物聯網設備

**English version below | [English](#english)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3](https://img.shields.io/badge/Python-3-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green.svg)](https://github.com/ai-caseylai/haas506-toolkit)

</div>

---

## 為什麼需要這個工具？

HaaS506-ED1 是一款基於展銳 UIS8910DM 的 4G 物聯網開發板，支援 MicroPython 開發。但官方只提供 Windows 專用的燒錄工具（ResearchDownload / SPD Flash Tool），Mac 和 Linux 用戶被完全排除在外。

**這個項目改變了這一切。**

我們逆向分析了阿里雲官方的 HaaS-Studio VS Code 擴展，提取了全部通訊協議，並用純 Python 重新實現。現在，無論你用的是 Mac、Linux 還是 Windows，一條命令就能完成從燒錄固件到推送腳本的所有操作。

> **不再需要虛擬機。不再需要借 Windows 電腦。不再被作業系統綁架。**

## 功能一覽

| 功能 | 命令 | 說明 |
|:-----|:-----|:-----|
| 解析固件 | `pac info firmware.pac` | 查看 .pac 文件內的分區、版本資訊 |
| 提取固件 | `pac extract firmware.pac` | 從 .pac 提取 FDL、bootloader 等映像 |
| 燒錄固件 | `flash firmware.pac` | 一鍵燒錄完整固件到開發板 |
| 推送腳本 | `push -p PORT main.py` | 推送 Python 腳本到開發板 |
| 批量推送 | `push --sync ./project/` | 推送整個專案目錄 |
| 運行腳本 | `run -p PORT main.py` | 推送並立即執行 |
| 互動終端 | `terminal -p PORT` | 連接開發板 REPL 互動調試 |

## 快速開始

### 安裝

```bash
git clone https://github.com/ai-caseylai/haas506-toolkit.git
cd haas506-toolkit
pip3 install pyusb pyserial
```

### 燒錄固件（首次設定，只需一次）

```bash
# 1. 用 USB 連接 HaaS506-ED1
# 2. 按住 BOOT 鍵，按一下 RST，鬆開 BOOT（進入 BootROM 模式）
# 3. 執行燒錄
python3 sprdflash.py flash firmware.pac
```

### 推送 Python 腳本（日常開發）

```bash
# 用 USB-TTL 連接開發板 UART 接口
python3 sprdflash.py push -p /dev/cu.usbserial-xxx main.py board.json
python3 sprdflash.py run -p /dev/cu.usbserial-xxx main.py
```

### 水耕菜自動化範例

```python
# main.py - 水耕菜 pH/EC 監控 + 種植燈控制
from machine import UART
import utime

# 讀取 RS485 pH/EC 感測器（Modbus RTU）
# 控制 MQTT 上報數據
# 繼電器控制種植燈開關
```

## 技術原理

### 展銳晶片燒錄是怎麼運作的？

```
┌──────────┐    USB     ┌──────────┐    USB     ┌──────────┐
│ BootROM  │ ─────────→ │   FDL1   │ ─────────→ │   FDL2   │
│ (晶片內建) │   載入     │ (初始化   │   載入     │ (操作     │
│           │            │  外部RAM)  │            │  Flash)  │
└──────────┘            └──────────┘            └─────┬────┘
                                                      │
                                            ┌─────────▼──────────┐
                                            │ 擦除 → 寫入 → 重啟   │
                                            └────────────────────┘
```

1. **BootROM** — 晶片出廠燒死，按 BOOT+RST 進入，透過 USB 接收指令
2. **FDL1** — 小型載入器（~50KB），初始化外部 RAM，讓晶片有足夠空間載入更大的程式
3. **FDL2** — Flash 操作程式（~500KB），提供擦除、寫入、讀取 Flash 的完整命令
4. FDL1 和 FDL2 都包含在 `.pac` 固件包內，燒錄完成後不會保留在 Flash 中

### Python 腳本推送協議

透過串口進入 MicroPython Raw REPL，用 base64 分塊傳輸文件：

```
Ctrl+C → Ctrl+A (Raw REPL) → base64 分塊寫入 → Ctrl+B → Ctrl+D (Reset)
```

### 通訊協議

| 協議 | 用途 | 傳輸方式 |
|:-----|:-----|:---------|
| Spreadtrum BSL (HDLC) | 燒錄固件 | USB (VID:0x1782 PID:0x4D00) |
| MicroPython Raw REPL | 推送腳本 | 串口 UART (115200) |

### .pac 文件格式

```
Offset    Size      Description
0x0000    2124      Header (magic: 0xFFFAFFFA)
0x084C    2580×N    File entries (FDL1, FDL2, bootloader, rootfs...)
...       ...       Partition images (各分區映像數據)
```

## HaaS506-ED1 硬體規格

| 項目 | 規格 |
|:-----|:-----|
| CPU | 展銳 UIS8910DM, Cortex A5, 500MHz |
| 記憶體 | 32MB RAM / 8MB Flash |
| 4G | CAT1 (FDD B1/B3/B5/B8, TDD B34/B38/B39/B40/B41) |
| 無線 | Wi-Fi + BLE 4.0 + ESP32 |
| 介面 | RS-485, RS-232, 乙太網口 |
| I/O | 類比輸入, 數位輸入, 繼電器輸出 |
| 協議 | TCP/HTTP/MQTT/Modbus RTU |
| 開發 | MicroPython |
| 供電 | 5V USB / 3.4~4.2V 鋰電池 |

## 適用場景

- 智慧農業 / 水耕栽培（pH/EC 感測 + 自動灌溉）
- 工業物聯網（RS-485 Modbus 設備監控）
- 遠端數據採集（4G + MQTT 上報）
- 智慧家居（繼電器控制 + 感測器整合）
- 車聯網 / 資產追蹤（4G + GPS）

## 鳴謝

本項目的實現離不開以下開源項目的啟發和參考：

- [sharkalaka](https://github.com/fxsheep/sharkalaka) — 展銳 BootROM USB 通訊協議 (Python)
- [u-boot-uis8910](https://github.com/fxsheep/u-boot-uis8910) — UIS8910DM U-Boot 適配
- [spreadtrum_flash](https://github.com/ilyakurdyukov/spreadtrum_flash) — 展銳 Flash 協議完整參考 (C)
- [PAC-Extractor](https://github.com/bismoy-bot/PAC-Extractor) — .pac 文件格式解析 (Python)
- [platform-logicrom](https://github.com/waybyte/platform-logicrom) — 替代開發平台 (PlatformIO)
- [HaaS-Studio](https://marketplace.visualstudio.com/items?itemName=haas.haas-studio) — 阿里雲官方 VS Code 擴展（逆向分析來源）

## 授權

[MIT License](LICENSE) — 自由使用、修改、分發。

---

<a id="english"></a>

<div align="center">

# HaaS506 Toolkit

### Enabling macOS & Linux users to develop HaaS506 IoT devices with ease

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3](https://img.shields.io/badge/Python-3-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-green.svg)](https://github.com/ai-caseylai/haas506-toolkit)

</div>

---

## Why This Project?

The HaaS506-ED1 is a powerful 4G IoT development board based on the Unisoc UIS8910DM chip, with MicroPython support. However, the official firmware flashing tools (ResearchDownload / SPD Flash Tool) are **Windows-only**, leaving Mac and Linux developers completely locked out.

**This project changes everything.**

We reverse-engineered Alibaba Cloud's official HaaS-Studio VS Code extension, extracted all communication protocols, and reimplemented them in pure Python. Now, whether you're on Mac, Linux, or Windows, you can flash firmware and push scripts with a single command.

> **No VMs. No borrowing Windows machines. No OS lock-in.**

## Features

| Feature | Command | Description |
|:--------|:--------|:------------|
| Parse firmware | `pac info firmware.pac` | Inspect partitions, versions in .pac files |
| Extract firmware | `pac extract firmware.pac` | Extract FDL, bootloader images from .pac |
| Flash firmware | `flash firmware.pac` | One-command full firmware flash |
| Push scripts | `push -p PORT main.py` | Push Python scripts to the board |
| Batch push | `push --sync ./project/` | Push entire project directory |
| Run scripts | `run -p PORT main.py` | Push and execute immediately |
| Interactive terminal | `terminal -p PORT` | Connect to board REPL for debugging |

## Quick Start

### Install

```bash
git clone https://github.com/ai-caseylai/haas506-toolkit.git
cd haas506-toolkit
pip3 install pyusb pyserial
```

### Flash Firmware (First Time Only)

```bash
# 1. Connect HaaS506-ED1 via USB
# 2. Hold BOOT, press RST, release BOOT (enter BootROM mode)
# 3. Run flash
python3 sprdflash.py flash firmware.pac
```

### Push Python Scripts (Daily Development)

```bash
# Connect via USB-TTL to UART port
python3 sprdflash.py push -p /dev/cu.usbserial-xxx main.py board.json
python3 sprdflash.py run -p /dev/cu.usbserial-xxx main.py
```

## How It Works

### Unisoc Chip Flashing Protocol

```
┌──────────┐    USB     ┌──────────┐    USB     ┌──────────┐
│ BootROM  │ ─────────→ │   FDL1   │ ─────────→ │   FDL2   │
│ (built-in)│   load     │  (init   │   load     │  (flash  │
│           │            │  ext RAM) │            │  ops)    │
└──────────┘            └──────────┘            └─────┬────┘
                                                      │
                                            ┌─────────▼──────────┐
                                            │ Erase → Write → Reset│
                                            └────────────────────┘
```

1. **BootROM** — Factory-burned, enter via BOOT+RST, accepts USB commands
2. **FDL1** — Small loader (~50KB), initializes external RAM
3. **FDL2** — Flash operation program (~500KB), provides erase/write/read commands
4. FDL1 and FDL2 are included inside the `.pac` firmware package

### Python Script Push Protocol

Serial communication via MicroPython Raw REPL with base64 chunked transfer:

```
Ctrl+C → Ctrl+A (Raw REPL) → base64 chunked write → Ctrl+B → Ctrl+D (Reset)
```

## HaaS506-ED1 Hardware Specs

| Spec | Details |
|:-----|:--------|
| CPU | Unisoc UIS8910DM, Cortex A5, 500MHz |
| Memory | 32MB RAM / 8MB Flash |
| 4G | CAT1 (FDD B1/B3/B5/B8, TDD B34/B38/B39/B40/B41) |
| Wireless | Wi-Fi + BLE 4.0 + ESP32 |
| Interfaces | RS-485, RS-232, Ethernet |
| I/O | Analog input, Digital input, Relay output |
| Protocols | TCP/HTTP/MQTT/Modbus RTU |
| Development | MicroPython |
| Power | 5V USB / 3.4~4.2V Li-ion battery |

## Use Cases

- Smart agriculture / Hydroponics (pH/EC sensing + automated irrigation)
- Industrial IoT (RS-485 Modbus device monitoring)
- Remote data collection (4G + MQTT reporting)
- Smart home (relay control + sensor integration)
- Fleet tracking / Asset management (4G + GPS)

## Credits

- [sharkalaka](https://github.com/fxsheep/sharkalaka) — Unisoc BootROM USB communication (Python)
- [u-boot-uis8910](https://github.com/fxsheep/u-boot-uis8910) — UIS8910DM U-Boot adaptation
- [spreadtrum_flash](https://github.com/ilyakurdyukov/spreadtrum_flash) — Complete Spreadtrum flash protocol reference (C)
- [PAC-Extractor](https://github.com/bismoy-bot/PAC-Extractor) — .pac file format parsing (Python)
- [platform-logicrom](https://github.com/waybyte/platform-logicrom) — Alternative dev platform (PlatformIO)
- [HaaS-Studio](https://marketplace.visualstudio.com/items?itemName=haas.haas-studio) — Official VS Code extension (reverse-engineered)

## License

[MIT License](LICENSE) — Free to use, modify, and distribute.
