# HaaS506-Toolkit

HaaS506-ED1 (UIS8910DM) 完整開發工具包，支援 macOS/Linux 燒錄固件、推送腳本、遠端控制。

逆向分析阿里雲 HaaS-Studio VS Code 擴展，提取全部通訊協議，用純 Python 重新實現。

## 功能一覽

| 功能 | 命令 | Mac | Linux | Windows |
|------|------|-----|-------|---------|
| 燒錄 .pac 固件 | `flash` | ✅ | ✅ | ✅ |
| 解析 .pac 文件 | `pac info/extract` | ✅ | ✅ | ✅ |
| 推送 Python 腳本 | `push` | ✅ | ✅ | ✅ |
| 推送並運行 | `run` | ✅ | ✅ | ✅ |
| 互動終端 | `terminal` | ✅ | ✅ | ✅ |

## 安裝

```bash
pip3 install pyusb pyserial
```

## 使用方法

```bash
# 查看串口
python3 sprdflash.py --list-ports

# 解析 .pac 固件
python3 sprdflash.py pac info firmware.pac
python3 sprdflash.py pac extract firmware.pac -d output/

# 燒錄固件（USB，按住 BOOT + RST 進入 BootROM）
python3 sprdflash.py flash firmware.pac

# 推送 Python 腳本（串口）
python3 sprdflash.py push -p /dev/cu.usbserial-xxx main.py board.json
python3 sprdflash.py push -p /dev/cu.usbserial-xxx --sync ./project/

# 推送並運行
python3 sprdflash.py run -p /dev/cu.usbserial-xxx main.py

# 互動終端
python3 sprdflash.py terminal -p /dev/cu.usbserial-xxx
```

## 技術原理

### 展銳 UIS8910DM 燒錄流程

```
USB BootROM → 載入 FDL1 → 執行 → 載入 FDL2 → 執行 → 燒寫 Flash → Reset
```

- **BootROM**：晶片出廠自帶，按 BOOT+RST 進入，透過 USB 等待指令
- **FDL1**：小型載入器（~50KB），初始化外部 RAM
- **FDL2**：Flash 操作程式（~500KB），提供擦除/寫入/讀取 Flash 命令
- FDL1 和 FDL2 都包含在 .pac 固件包內，用完即棄

### Python 腳本推送協議

透過串口進入 MicroPython Raw REPL，用 base64 分塊傳輸文件：

```
Ctrl+C → Ctrl+A (進入 Raw REPL) → base64 分塊寫入 → Ctrl+B → Ctrl+D (Reset)
```

### 通訊協議

| 協議 | 用途 | 傳輸方式 |
|------|------|----------|
| Spreadtrum BSL (HDLC) | 燒錄固件 | USB (VID:0x1782 PID:0x4D00) |
| YMODEM | 推送 pyamp.zip | 串口 + amp 握手 |
| MicroPython Raw REPL | 推送用戶腳本 | 串口 (115200) |

### .pac 文件格式

```
Offset    Size    Description
0x0000    2124    Header (magic: 0xFFFAFFFA, firmware name, version, file count)
0x084C    2580*N  File entries (FDL1, FDL2, bootloader, kernel, rootfs...)
...               File data (各分區映像)
```

## HaaS506-ED1 硬體規格

| 項目 | 規格 |
|------|------|
| CPU | 展銳 UIS8910DM, Cortex A5, 500MHz |
| RAM | 32MB (用戶可用 ~2MB) |
| Flash | 8MB (文件系統 ~1MB) |
| 通訊 | 4G CAT1 + Wi-Fi + BLE 4.0 + ESP32 |
| 介面 | RS-485, RS-232, 網口 |
| I/O | 類比輸入, 開關量輸入, 繼電器輸出 |
| 協議 | TCP/HTTP/MQTT/Modbus RTU |
| 開發語言 | MicroPython (Python 輕應用) |
| 供電 | 5V USB / 3.4~4.2V 鋰電池 |

## 參考項目

- [fxsheep/sharkalaka](https://github.com/fxsheep/sharkalaka) - 展銳 BootROM USB 通訊 (Python)
- [fxsheep/u-boot-uis8910](https://github.com/fxsheep/u-boot-uis8910) - UIS8910DM U-Boot
- [ilyakurdyukov/spreadtrum_flash](https://github.com/ilyakurdyukov/spreadtrum_flash) - 展銳 Flash 協議參考 (C)
- [bismoy-bot/PAC-Extractor](https://github.com/bismoy-bot/PAC-Extractor) - .pac 文件解析 (Python)
- [waybyte/platform-logicrom](https://github.com/waybyte/platform-logicrom) - 替代開發平台 (PlatformIO)
- [HaaS-Studio VS Code Extension](https://marketplace.visualstudio.com/items?itemName=haas.haas-studio) - 官方 IDE (逆向分析來源)
- [HaaS506 官方文件](https://www.yuque.com/haas506/wiki)

## 授權

MIT License
