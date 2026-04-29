#!/usr/bin/env python3
"""
HaaS506 Complete Firmware Flash & Script Push Tool for macOS/Linux

Combines:
  - .pac firmware parser (from spreadtrum/unpac)
  - Spreadtrum USB BootROM flash protocol (from sharkalaka + spreadtrum_flash)
  - YMODEM transfer (from HaaS-Studio transymodem.py)
  - Raw REPL script push (reverse-engineered from HaaS-Studio)

Usage:
  python3 haas_tool.py pac info firmware.pac
  python3 haas_tool.py pac extract firmware.pac -d output_dir/
  python3 haas_tool.py flash firmware.pac
  python3 haas_tool.py push -p /dev/cu.usbserial-xxx main.py board.json
  python3 haas_tool.py run -p /dev/cu.usbserial-xxx main.py
  python3 haas_tool.py terminal -p /dev/cu.usbserial-xxx

Requires: pip3 install pyusb pyserial
"""

import struct
import os
import sys
import time
import argparse
import base64
import glob

# ============================================================================
# Section 1: .pac File Parser
# Based on spreadtrum_flash/unpac/unpac.c
# ============================================================================

PAC_MAGIC = 0xFFFAFFFA


def crc16(data):
    """CRC16 for PAC file verification."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ ((-(crc & 1)) & 0xA001)
    return crc & 0xFFFF


def u16_to_str(u16_array):
    """Convert UTF-16LE array to Python string."""
    result = []
    for val in u16_array:
        if val == 0:
            break
        result.append(chr(val) if 0x20 <= val < 0x7F else '?')
    return ''.join(result)


class PacHeader:
    """Spreadtrum .pac file header."""
    SIZE = 2124  # sizeof(sprd_head_t)

    def __init__(self):
        self.pac_version = ""
        self.pac_size = 0
        self.fw_name = ""
        self.fw_version = ""
        self.file_count = 0
        self.dir_offset = 0
        self.fw_alias = ""
        self.pac_magic = 0

    def parse(self, data):
        if len(data) < self.SIZE:
            raise Exception(f"PAC header too short: {len(data)} < {self.SIZE}")

        off = 0
        self.pac_version = u16_to_str(struct.unpack_from('24H', data, off)); off += 48
        self.pac_size, = struct.unpack_from('<I', data, off); off += 4
        self.fw_name = u16_to_str(struct.unpack_from('256H', data, off)); off += 512
        self.fw_version = u16_to_str(struct.unpack_from('256H', data, off)); off += 512
        self.file_count, = struct.unpack_from('<I', data, off); off += 4
        self.dir_offset, = struct.unpack_from('<I', data, off); off += 4

        off += 20  # unknown1[5]
        self.fw_alias = u16_to_str(struct.unpack_from('100H', data, off)); off += 200

        off += 12  # unknown2[3]
        off += 800  # unknown[200]

        self.pac_magic, = struct.unpack_from('<I', data, off)

        if self.pac_magic != PAC_MAGIC:
            raise Exception(f"Bad PAC magic: 0x{self.pac_magic:08X} (expected 0x{PAC_MAGIC:08X})")


class PacFile:
    """A single file entry inside .pac."""
    SIZE = 2580  # sizeof(sprd_file_t)

    def __init__(self):
        self.struct_size = 0
        self.id = ""
        self.name = ""
        self.size_high = 0
        self.pac_offset_high = 0
        self.size = 0
        self.type = 0
        self.flash_use = 0
        self.pac_offset = 0
        self.omit_flag = 0
        self.addr_num = 0
        self.addrs = []

    @property
    def full_size(self):
        return (self.size_high << 32) | self.size

    @property
    def full_offset(self):
        return (self.pac_offset_high << 32) | self.pac_offset

    def parse(self, data):
        off = 0
        self.struct_size, = struct.unpack_from('<I', data, off); off += 4
        self.id = u16_to_str(struct.unpack_from('256H', data, off)); off += 512
        self.name = u16_to_str(struct.unpack_from('256H', data, off)); off += 512
        off += 504  # unknown1[256-4] as uint32
        self.size_high, = struct.unpack_from('<I', data, off); off += 4
        self.pac_offset_high, = struct.unpack_from('<I', data, off); off += 4
        self.size, = struct.unpack_from('<I', data, off); off += 4
        self.type, = struct.unpack_from('<I', data, off); off += 4
        self.flash_use, = struct.unpack_from('<I', data, off); off += 4
        self.pac_offset, = struct.unpack_from('<I', data, off); off += 4
        self.omit_flag, = struct.unpack_from('<I', data, off); off += 4
        self.addr_num, = struct.unpack_from('<I', data, off); off += 4
        self.addrs = list(struct.unpack_from('5I', data, off))

    @property
    def type_str(self):
        return {0: "operation", 1: "file", 2: "xml", 0x101: "FDL"}.get(self.type, f"0x{self.type:x}")

    @property
    def flash_addr(self):
        return self.addrs[0] if self.addr_num > 0 else 0

    def __repr__(self):
        parts = [f"type={self.type_str}"]
        if self.full_size:
            parts.append(f"size=0x{self.full_size:x}")
        if self.flash_addr:
            parts.append(f"addr=0x{self.flash_addr:x}")
        if self.id:
            parts.append(f'id="{self.id}"')
        if self.name:
            parts.append(f'name="{self.name}"')
        return f"PacFile({', '.join(parts)})"


def parse_pac(filepath):
    """Parse a .pac file and return header + list of file entries."""
    with open(filepath, 'rb') as f:
        data = f.read()

    header = PacHeader()
    header.parse(data[:PacHeader.SIZE])

    files = []
    for i in range(header.file_count):
        start = header.dir_offset + i * PacFile.SIZE
        pf = PacFile()
        pf.parse(data[start:start + PacFile.SIZE])
        pf._data = data  # keep reference for extraction
        files.append(pf)

    return header, files


def extract_pac_file(pf, output_dir):
    """Extract a single file from parsed PAC data."""
    if not pf.name or not pf.full_offset or not pf.full_size:
        return None

    safe_name = os.path.basename(pf.name.replace('\\', '_').replace('/', '_'))
    out_path = os.path.join(output_dir, safe_name)

    os.makedirs(output_dir, exist_ok=True)
    with open(pf.name, 'wb') as f:
        f.write(pf._data[pf.full_offset:pf.full_offset + pf.full_size])

    return out_path


# ============================================================================
# Section 2: Spreadtrum USB Flash Protocol
# Based on sharkalaka/sprdflasher.py + spreadtrum_flash/spd_cmd.h
# ============================================================================

SPRD_VID = 0x1782
SPRD_PID = 0x4D00
SPRD_EP_IN = 0x85
SPRD_EP_OUT = 0x06
MIDST_SIZE = 528

# BSL Commands (from spd_cmd.h)
BSL_CMD_CONNECT = 0x00
BSL_CMD_START_DATA = 0x01
BSL_CMD_MIDST_DATA = 0x02
BSL_CMD_END_DATA = 0x03
BSL_CMD_EXEC_DATA = 0x04
BSL_CMD_NORMAL_RESET = 0x05
BSL_CMD_ERASE_FLASH = 0x0A
BSL_CMD_ENABLE_WRITE_FLASH = 0x1B
BSL_CMD_END_PROCESS = 0x7F

BSL_REP_ACK = 0x80
BSL_REP_VER = 0x81


def hdlc_translate(data):
    """Apply HDLC byte stuffing."""
    result = bytearray([0x7E])
    for b in data:
        if b == 0x7E:
            result += bytes([0x7D, 0x5E])
        elif b == 0x7D:
            result += bytes([0x7D, 0x5D])
        else:
            result += bytes([b])
    result += bytes([0x7E])
    return bytes(result)


def hdlc_detranslate(data):
    """Remove HDLC byte stuffing."""
    lst = list(data)
    if lst[0] != 0x7E or lst[-1] != 0x7E:
        return None
    del lst[0]; del lst[-1]
    result = b''
    i = 0
    while i <= len(lst) - 1:
        if lst[i] == 0x7D and i + 1 < len(lst):
            if lst[i+1] == 0x5E:
                result += bytes([0x7E]); i += 2
            elif lst[i+1] == 0x5D:
                result += bytes([0x7D]); i += 2
            else:
                result += bytes([lst[i]]); i += 1
        else:
            result += bytes([lst[i]]); i += 1
    return result


def crc16_spreadtrum(data):
    """CRC16 for Spreadtrum protocol (CRC-CCITT variant)."""
    import binascii
    return binascii.crc_hqx(data, 0)


def crc16_add(data):
    """Additive checksum for Spreadtrum protocol."""
    total = 0
    size = len(data)
    i = size
    while i > 1:
        total += data[size - i] + (data[size - i + 1] << 8)
        i -= 2
    if i == 1:
        total += data[size - i]
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    total = (~total) & 0xFFFF
    total = ((total >> 8) | (total << 8)) & 0xFFFF
    return total


class SprdFlasher:
    """Spreadtrum USB flash communication."""

    def __init__(self):
        self.dev = None
        self.chksum_func = crc16_spreadtrum

    def find_device(self):
        """Find Spreadtrum device in BootROM mode."""
        import usb.core
        dev = usb.core.find(idVendor=SPRD_VID, idProduct=SPRD_PID)
        if dev is None:
            return False
        dev.set_configuration()
        self.dev = dev
        return True

    def _send(self, data, timeout=5000):
        self.dev.write(SPRD_EP_OUT, data, timeout)

    def _recv(self, size=1024, timeout=5000):
        import usb.core
        try:
            return bytes(self.dev.read(SPRD_EP_IN, size, timeout))
        except usb.core.USBTimeoutError:
            return None

    def _make_packet(self, cmd, data=b''):
        """Build HDLC-framed packet with checksum."""
        pkt = struct.pack('>HH', cmd, len(data))
        if data:
            pkt += data
        pkt += struct.pack('>H', self.chksum_func(pkt))
        return hdlc_translate(pkt)

    def _parse_response(self):
        """Read and parse a response packet."""
        raw = self._recv(timeout=5000)
        if not raw:
            return None, None
        pkt = hdlc_detranslate(raw)
        if not pkt or len(pkt) < 6:
            return None, None
        cmd = struct.unpack_from('>H', pkt, 0)[0]
        length = struct.unpack_from('>H', pkt, 2)[0]
        data = pkt[4:-2] if length > 0 else b''
        return cmd, data

    def ping(self):
        self._send(b'\x7E')

    def connect(self):
        self._send(self._make_packet(BSL_CMD_CONNECT))

    def read_version(self):
        cmd, data = self._parse_response()
        if cmd == BSL_REP_VER:
            return data.decode('utf-8', errors='ignore') if data else ""
        return None

    def read_ack(self):
        cmd, data = self._parse_response()
        return cmd == BSL_REP_ACK and (not data or len(data) == 0)

    def download_to_ram(self, addr, data):
        """Download binary data to RAM at specified address."""
        size = len(data)
        self._send(self._make_packet(BSL_CMD_START_DATA,
                                     struct.pack('>II', addr, size)))
        if not self.read_ack():
            raise Exception("START_DATA NACK")

        sent = 0
        while sent < size:
            chunk = data[sent:sent + MIDST_SIZE]
            self._send(self._make_packet(BSL_CMD_MIDST_DATA, chunk))
            if not self.read_ack():
                raise Exception(f"MIDST_DATA NACK at {sent}")
            sent += len(chunk)
            pct = sent * 100 // size
            sys.stdout.write(f"\r  Download: {pct}% ({sent}/{size})")
            sys.stdout.flush()

        print()
        self._send(self._make_packet(BSL_CMD_END_DATA))
        if not self.read_ack():
            raise Exception("END_DATA NACK")

    def execute(self):
        """Execute code at the downloaded address."""
        self._send(self._make_packet(BSL_CMD_EXEC_DATA))
        if not self.read_ack():
            raise Exception("EXEC_DATA NACK")

    def erase_flash(self, addr, size):
        """Erase flash region."""
        print(f"  Erasing flash 0x{addr:08X} size 0x{size:X}...")
        self._send(self._make_packet(BSL_CMD_ERASE_FLASH,
                                     struct.pack('>II', addr, size)))
        cmd, data = self._parse_response()
        if cmd != BSL_REP_ACK:
            raise Exception(f"ERASE_FLASH failed: cmd=0x{cmd:02X}")

    def download_to_flash(self, addr, data):
        """Download data and write to flash at specified address."""
        size = len(data)
        self.erase_flash(addr, size)

        self._send(self._make_packet(BSL_CMD_START_DATA,
                                     struct.pack('>II', addr, size)))
        if not self.read_ack():
            raise Exception("START_DATA NACK")

        sent = 0
        while sent < size:
            chunk = data[sent:sent + MIDST_SIZE]
            self._send(self._make_packet(BSL_CMD_MIDST_DATA, chunk))
            if not self.read_ack():
                raise Exception(f"Flash write NACK at offset {sent}")
            sent += len(chunk)
            pct = sent * 100 // size
            sys.stdout.write(f"\r  Writing flash: {pct}% ({sent}/{size})")
            sys.stdout.flush()

        print()
        self._send(self._make_packet(BSL_CMD_END_DATA))
        if not self.read_ack():
            raise Exception("END_DATA NACK")

    def normal_reset(self):
        """Reset device to normal mode."""
        self._send(self._make_packet(BSL_CMD_NORMAL_RESET))
        print("Reset command sent.")


# ============================================================================
# Section 3: Complete Flash Workflow
# ============================================================================

def flash_pac(pac_path):
    """Flash a complete .pac firmware to HaaS506 via USB."""
    print(f"Parsing {pac_path}...")
    header, files = parse_pac(pac_path)

    print(f"\nFirmware: {header.fw_name}")
    print(f"Version: {header.fw_version}")
    print(f"Files: {header.file_count}")
    print()

    # Identify FDL1, FDL2, and data files
    fdl1 = fdl2 = None
    data_files = []

    for pf in files:
        if pf.type == 0x101:  # FDL
            if fdl1 is None:
                fdl1 = pf
            else:
                fdl2 = pf
        elif pf.type == 1 and pf.flash_use and pf.flash_addr:
            data_files.append(pf)

    if not fdl1:
        raise Exception("No FDL1 found in PAC file")
    if not fdl2:
        raise Exception("No FDL2 found in PAC file")

    print(f"FDL1: {fdl1.name} (addr=0x{fdl1.flash_addr:08X})")
    print(f"FDL2: {fdl2.name} (addr=0x{fdl2.flash_addr:08X})")
    print(f"Data files: {len(data_files)}")
    for df in data_files:
        print(f"  {df.name} -> 0x{df.flash_addr:08X} ({df.full_size} bytes)")
    print()

    # Connect to device
    flasher = SprdFlasher()
    print("Looking for Spreadtrum device in BootROM mode...")
    print("(Hold BOOT + press RST on the board)")
    if not flasher.find_device():
        print("Device not found. Please:")
        print("  1. Connect HaaS506 via USB")
        print("  2. Hold BOOT button")
        print("  3. Press and release RST button")
        print("  4. Release BOOT button")
        sys.exit(1)

    print("Device found!")

    # Step 1: BootROM - load FDL1
    print("\n=== Step 1: Loading FDL1 ===")
    flasher.ping()
    ver = flasher.read_version()
    print(f"BootROM version: {ver}")
    flasher.connect()
    assert flasher.read_ack(), "BootROM connect failed"

    fdl1_data = fdl1._data[fdl1.full_offset:fdl1.full_offset + fdl1.full_size]
    fdl1_addr = fdl1.flash_addr if fdl1.flash_addr else 0x40004000
    print(f"Downloading FDL1 to 0x{fdl1_addr:08X} ({len(fdl1_data)} bytes)")
    flasher.download_to_ram(fdl1_addr, fdl1_data)
    print("Executing FDL1...")
    flasher.execute()

    # Step 2: FDL1 - load FDL2
    print("\n=== Step 2: Loading FDL2 ===")
    flasher.chksum_func = crc16_add  # FDL1 uses additive checksum

    for i in range(10):
        flasher.ping()
        ver = flasher.read_version()
        if ver:
            break
    print(f"FDL1 version: {ver}")

    flasher.connect()
    assert flasher.read_ack(), "FDL1 connect failed"

    fdl2_data = fdl2._data[fdl2.full_offset:fdl2.full_offset + fdl2.full_size]
    fdl2_addr = fdl2.flash_addr if fdl2.flash_addr else 0x9FC00000
    print(f"Downloading FDL2 to 0x{fdl2_addr:08X} ({len(fdl2_data)} bytes)")
    flasher.download_to_ram(fdl2_addr, fdl2_data)
    print("Executing FDL2...")
    flasher.execute()

    # Wait for FDL2 to be ready
    for i in range(10):
        cmd, data = flasher._parse_response()
        if cmd == 0x96:
            print("FDL2 is running!")
            break
    else:
        # Try connecting anyway
        print("Waiting for FDL2...")
        flasher.connect()
        flasher.read_ack()

    # Step 3: FDL2 - flash each partition
    print(f"\n=== Step 3: Flashing {len(data_files)} partitions ===")

    # Re-connect under FDL2
    flasher.connect()
    assert flasher.read_ack(), "FDL2 connect failed"

    for pf in data_files:
        print(f"\nFlashing: {pf.name}")
        file_data = pf._data[pf.full_offset:pf.full_offset + pf.full_size]
        flasher.download_to_flash(pf.flash_addr, file_data)
        print(f"  Done: {pf.name}")

    # Step 4: Reset
    print("\n=== Step 4: Resetting device ===")
    flasher.normal_reset()
    print("\nFirmware flash complete!")


# ============================================================================
# Section 4: Serial Script Push (Raw REPL)
# From reverse-engineered HaaS-Studio extension
# ============================================================================

BIN_CHUNK_SIZE = 512
DEFAULT_BAUDRATE = 115200
REMOTE_BASE = "/data/pyamp"


def list_serial_ports():
    import serial.tools.list_ports
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
    else:
        print("Available serial ports:")
        for p in ports:
            print(f"  {p.device} - {p.description}")
    return ports


class SerialBoard:
    """HaaS506 serial communication via Raw REPL."""

    def __init__(self, port, baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def connect(self):
        import serial
        print(f"Connecting to {self.port} @ {self.baudrate}...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=0.5)
        time.sleep(0.5)
        print("Connected.")

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _read_until(self, expected, timeout=8):
        buf = b""
        start = time.time()
        while (time.time() - start) < timeout:
            chunk = self.ser.read(128)
            if chunk:
                buf += chunk
                if expected.encode() if isinstance(expected, str) else expected in buf:
                    return buf.decode(errors="replace")
        return buf.decode(errors="replace")

    def _send(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.ser.write(data)
        time.sleep(0.05)

    def stop_running(self):
        self._send(b"\x03\x03")
        time.sleep(0.3)
        self._read_until(">>>", timeout=2)

    def enter_raw_repl(self):
        self.stop_running()
        self._send(b"\x01")
        r = self._read_until("raw REPL; CTRL-B to exit", timeout=5)
        if "raw REPL" not in r:
            self._send(b"\x01")
            r = self._read_until("raw REPL; CTRL-B to exit", timeout=3)
            if "raw REPL" not in r:
                raise Exception("Failed to enter raw REPL")

    def exit_raw_repl(self):
        self._send(b"\x02")
        time.sleep(0.2)

    def exec_raw(self, cmd):
        self._send(cmd + "\r\n")
        time.sleep(0.1)
        return self._read_until(">", timeout=5)

    def soft_reset(self):
        self._send(b"\x04")
        time.sleep(1)

    def push_file(self, local_path, remote_path=None):
        if remote_path is None:
            remote_path = f"{REMOTE_BASE}/{os.path.basename(local_path)}"

        with open(local_path, "rb") as f:
            content = f.read()

        name = os.path.basename(local_path)
        print(f"Pushing {name} -> {remote_path} ({len(content)} bytes)")

        self.enter_raw_repl()
        self.exec_raw(f'f = open("{remote_path}", "wb")')

        total = (len(content) + BIN_CHUNK_SIZE - 1) // BIN_CHUNK_SIZE
        for i in range(total):
            s = i * BIN_CHUNK_SIZE
            e = min(s + BIN_CHUNK_SIZE, len(content))
            b64 = base64.b64encode(content[s:e]).decode()
            self.exec_raw(f"f.write(ubinascii.a2b_base64('{b64}'))")
            pct = (i + 1) * 100 // total
            sys.stdout.write(f"\r  {pct}% ({i+1}/{total})")
            sys.stdout.flush()

        print()
        self.exec_raw("f.close()")
        self.exit_raw_repl()

    def push_directory(self, local_dir):
        files = []
        for ext in ("*.py", "*.json", "*.txt"):
            files.extend(glob.glob(os.path.join(local_dir, ext)))
        if not files:
            print(f"No files found in {local_dir}")
            return
        for f in files:
            self.push_file(f)
        print(f"\nPushed {len(files)} files.")

    def terminal(self):
        print("\n=== HaaS506 Terminal (Ctrl+C to exit) ===\n")
        import threading

        def reader():
            while True:
                try:
                    data = self.ser.read(128)
                    if data:
                        sys.stdout.write(data.decode(errors="replace"))
                        sys.stdout.flush()
                except:
                    break

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        try:
            while True:
                line = input()
                self._send(line + "\r\n")
        except (EOFError, KeyboardInterrupt):
            pass


# ============================================================================
# Section 5: CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="HaaS506 Complete Firmware Flash & Script Push Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pac info firmware.pac
  %(prog)s pac extract firmware.pac -d output/
  %(prog)s flash firmware.pac
  %(prog)s push -p /dev/cu.usbserial-xxx main.py board.json
  %(prog)s run -p /dev/cu.usbserial-xxx main.py
  %(prog)s terminal -p /dev/cu.usbserial-xxx
  %(prog)s list-ports
        """)

    parser.add_argument("--list-ports", action="store_true")

    sub = parser.add_subparsers(dest="cmd")

    # pac subcommand
    pac = sub.add_parser("pac", help="Parse .pac firmware file")
    pac_sp = pac.add_subparsers(dest="pac_cmd")
    info = pac_sp.add_parser("info", help="Show PAC file info")
    info.add_argument("file", help=".pac file path")
    ext = pac_sp.add_parser("extract", help="Extract files from PAC")
    ext.add_argument("file", help=".pac file path")
    ext.add_argument("-d", "--dir", default="pac_output", help="Output directory")

    # flash subcommand
    fl = sub.add_parser("flash", help="Flash .pac firmware via USB")
    fl.add_argument("file", help=".pac firmware file")

    # push subcommand
    ps = sub.add_parser("push", help="Push scripts via serial")
    ps.add_argument("-p", "--port", required=True, help="Serial port")
    ps.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE)
    ps.add_argument("--sync", metavar="DIR", help="Push all .py/.json from directory")
    ps.add_argument("files", nargs="*", help="Files to push")

    # run subcommand
    rn = sub.add_parser("run", help="Push and run a script")
    rn.add_argument("-p", "--port", required=True)
    rn.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE)
    rn.add_argument("file", help="Python file to run")

    # terminal subcommand
    tm = sub.add_parser("terminal", help="Interactive terminal")
    tm.add_argument("-p", "--port", required=True)
    tm.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE)

    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return

    if args.cmd == "pac":
        if args.pac_cmd == "info":
            h, fs = parse_pac(args.file)
            print(f"Firmware: {h.fw_name}")
            print(f"Version:  {h.fw_version}")
            print(f"Alias:    {h.fw_alias}")
            print(f"PAC size: {h.pac_size}")
            print(f"Files:    {h.file_count}")
            print()
            for pf in fs:
                print(f"  {pf}")

        elif args.pac_cmd == "extract":
            h, fs = parse_pac(args.file)
            os.makedirs(args.dir, exist_ok=True)
            for pf in fs:
                if pf.name and pf.full_offset and pf.full_size:
                    safe = os.path.basename(pf.name.replace('\\', '_'))
                    out = os.path.join(args.dir, safe)
                    data = pf._data[pf.full_offset:pf.full_offset + pf.full_size]
                    with open(out, 'wb') as f:
                        f.write(data)
                    print(f"  Extracted: {safe} ({len(data)} bytes)")
            print(f"\nExtracted to {args.dir}/")
        else:
            pac.print_help()

    elif args.cmd == "flash":
        flash_pac(args.file)

    elif args.cmd == "push":
        board = SerialBoard(args.port, args.baudrate)
        try:
            board.connect()
            if args.sync:
                board.push_directory(args.sync)
            elif args.files:
                for f in args.files:
                    board.push_file(f)
            else:
                print("Error: specify files or --sync DIR")
            board.soft_reset()
        finally:
            board.disconnect()

    elif args.cmd == "run":
        board = SerialBoard(args.port, args.baudrate)
        try:
            board.connect()
            board.push_file(args.file)
            print("Running...")
            board.enter_raw_repl()
            board.exec_raw(f'exec(open("{REMOTE_BASE}/{os.path.basename(args.file)}").read())')
            board.exit_raw_repl()
            board.soft_reset()
        finally:
            board.disconnect()

    elif args.cmd == "terminal":
        board = SerialBoard(args.port, args.baudrate)
        try:
            board.connect()
            board.terminal()
        finally:
            board.disconnect()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
