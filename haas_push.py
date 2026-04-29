#!/usr/bin/env python3
"""
HaaS506 Python Script Push Tool
Replicates HaaS-Studio's "deploy" functionality for macOS/Linux

Usage:
    python3 haas_push.py --port /dev/cu.usbserial-xxx push main.py
    python3 haas_push.py --port /dev/cu.usbserial-xxx push main.py board.json
    python3 haas_push.py --port /dev/cu.usbserial-xxx push --sync ./my_project/
    python3 haas_push.py --port /dev/cu.usbserial-xxx run main.py
    python3 haas_push.py --port /dev/cu.usbserial-xxx terminal
    python3 haas_push.py --port /dev/cu.usbserial-xxx ymodem pyamp.zip

Based on reverse-engineered HaaS-Studio VS Code extension protocol.
"""

import serial
import serial.tools.list_ports
import time
import sys
import os
import base64
import argparse
import glob

# Constants
BIN_CHUNK_SIZE = 512
DEFAULT_BAUDRATE = 115200
REMOTE_BASE = "/data/pyamp"


def list_ports():
    """List available serial ports."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return []
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device} - {p.description}")
    return [p.device for p in ports]


class HaaSBoard:
    """Communicate with HaaS506 via serial Raw REPL protocol."""

    def __init__(self, port, baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.timeout = 8

    def connect(self):
        """Open serial connection."""
        print(f"Connecting to {self.port} @ {self.baudrate}...")
        self.ser = serial.Serial()
        self.ser.port = self.port
        self.ser.baudrate = self.baudrate
        self.ser.parity = serial.PARITY_NONE
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.timeout = 0.5
        try:
            self.ser.open()
        except Exception as e:
            raise Exception(f"Failed to open serial port: {e}")
        print("Connected.")
        time.sleep(0.5)

    def disconnect(self):
        """Close serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Disconnected.")

    def _read_until(self, expected, timeout=None):
        """Read from serial until expected string is found."""
        if timeout is None:
            timeout = self.timeout
        buf = b""
        start = time.time()
        while (time.time() - start) < timeout:
            chunk = self.ser.read(128)
            if chunk:
                buf += chunk
                if isinstance(expected, bytes) and expected in buf:
                    return buf.decode(errors="replace")
                elif isinstance(expected, str) and expected.encode() in buf:
                    return buf.decode(errors="replace")
        return buf.decode(errors="replace")

    def _send(self, data):
        """Send data to serial port."""
        if isinstance(data, str):
            data = data.encode()
        self.ser.write(data)
        time.sleep(0.05)

    def stop_running(self):
        """Send Ctrl+C to stop any running program."""
        self._send(b"\x03")
        time.sleep(0.2)
        self._send(b"\x03")
        time.sleep(0.3)
        self._read_until(">>>", timeout=2)

    def enter_raw_repl(self):
        """Enter MicroPython raw REPL mode (Ctrl+A)."""
        print("Entering raw REPL...")
        self.stop_running()
        self._send(b"\x01")  # Ctrl+A
        result = self._read_until("raw REPL; CTRL-B to exit", timeout=5)
        if "raw REPL" not in result:
            # Try again
            self._send(b"\x01")
            result = self._read_until("raw REPL; CTRL-B to exit", timeout=3)
            if "raw REPL" not in result:
                raise Exception("Failed to enter raw REPL mode")
        print("Entered raw REPL.")

    def exit_raw_repl(self):
        """Exit raw REPL mode (Ctrl+B)."""
        self._send(b"\x02")  # Ctrl+B
        time.sleep(0.2)

    def exec_raw(self, command):
        """Execute a command in raw REPL mode."""
        self._send(command + "\r\n")
        time.sleep(0.1)
        result = self._read_until(">", timeout=5)
        return result

    def exec_command(self, command):
        """Execute a command and return output."""
        self.enter_raw_repl()
        self._send(command + "\r\n")
        time.sleep(0.1)
        result = self._read_until(">", timeout=10)
        self.exit_raw_repl()
        return result

    def soft_reset(self):
        """Soft reset the board (Ctrl+D)."""
        self._send(b"\x04")
        time.sleep(1)
        print("Board reset.")

    def push_file(self, local_path, remote_path=None):
        """Push a single file to the board using Raw REPL + base64 chunks."""
        if remote_path is None:
            filename = os.path.basename(local_path)
            remote_path = f"{REMOTE_BASE}/{filename}"

        with open(local_path, "rb") as f:
            content = f.read()

        filename = os.path.basename(local_path)
        print(f"Pushing {filename} -> {remote_path} ({len(content)} bytes)")

        self.enter_raw_repl()

        # Open file for writing
        self.exec_raw(f'f = open("{remote_path}", "wb")')

        # Write in base64 chunks
        total_chunks = (len(content) + BIN_CHUNK_SIZE - 1) // BIN_CHUNK_SIZE
        for i in range(total_chunks):
            start = i * BIN_CHUNK_SIZE
            end = min(start + BIN_CHUNK_SIZE, len(content))
            chunk = content[start:end]
            b64 = base64.b64encode(chunk).decode("ascii")
            self.exec_raw(f"f.write(ubinascii.a2b_base64('{b64}'))")

            pct = (i + 1) * 100 // total_chunks
            sys.stdout.write(f"\r  Progress: {pct}% ({i+1}/{total_chunks} chunks)")
            sys.stdout.flush()

        print()

        # Close file
        self.exec_raw("f.close()")
        print(f"  File saved: {remote_path}")

        self.exit_raw_repl()

    def push_directory(self, local_dir):
        """Push all Python/JSON files from a directory."""
        extensions = ("*.py", "*.json", "*.txt")
        files = []
        for ext in extensions:
            files.extend(glob.glob(os.path.join(local_dir, ext)))

        if not files:
            print(f"No files found in {local_dir}")
            return

        print(f"Found {len(files)} files to push:")
        for f in files:
            print(f"  {os.path.basename(f)}")

        for filepath in files:
            self.push_file(filepath)

        print(f"\nAll {len(files)} files pushed successfully.")

    def run_file(self, local_path):
        """Push and immediately run a Python file."""
        filename = os.path.basename(local_path)
        remote_path = f"{REMOTE_BASE}/{filename}"

        self.push_file(local_path, remote_path)

        print("Running script...")
        self.enter_raw_repl()
        self.exec_raw(f'exec(open("{remote_path}").read())')
        self.exit_raw_repl()
        self.soft_reset()

    def terminal_mode(self):
        """Interactive terminal mode."""
        print("\n=== HaaS506 Terminal (Ctrl+] to exit) ===\n")
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

        while True:
            try:
                line = input()
                self._send(line + "\r\n")
            except EOFError:
                break
            except KeyboardInterrupt:
                break


class HaaSYModem:
    """YMODEM file transfer (for firmware updates)."""

    def __init__(self, port, baudrate=DEFAULT_BAUDRATE):
        self.port = port
        self.baudrate = baudrate

    def transfer(self, filepath):
        """Transfer file using amp handshake + YMODEM protocol."""
        # Import ymodemfile from burntool directory
        burntool_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "haas-studio-analysis", "extracted", "extension", "asserts", "burntool"
        )
        if burntool_dir not in sys.path:
            sys.path.insert(0, burntool_dir)

        from transymodem import download_file

        print(f"YMODEM transfer: {filepath}")
        download_file(self.port, self.baudrate, filepath)


def main():
    parser = argparse.ArgumentParser(
        description="HaaS506 Python Script Push Tool (Mac/Linux compatible)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list-ports
  %(prog)s -p /dev/cu.usbserial-xxx push main.py
  %(prog)s -p /dev/cu.usbserial-xxx push main.py board.json
  %(prog)s -p /dev/cu.usbserial-xxx push --sync ./project/
  %(prog)s -p /dev/cu.usbserial-xxx run main.py
  %(prog)s -p /dev/cu.usbserial-xxx terminal
        """
    )

    parser.add_argument("-p", "--port", help="Serial port (e.g., /dev/cu.usbserial-xxx)")
    parser.add_argument("-b", "--baudrate", type=int, default=DEFAULT_BAUDRATE, help="Baud rate")
    parser.add_argument("--list-ports", action="store_true", help="List available serial ports")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # push command
    push_parser = subparsers.add_parser("push", help="Push file(s) to board")
    push_parser.add_argument("files", nargs="*", help="Files to push")
    push_parser.add_argument("--sync", metavar="DIR", help="Push all .py/.json files from directory")
    push_parser.add_argument("--remote-path", help="Remote path prefix (default: /data/pyamp)")

    # run command
    run_parser = subparsers.add_parser("run", help="Push and run a Python file")
    run_parser.add_argument("file", help="Python file to run")

    # terminal command
    subparsers.add_parser("terminal", help="Interactive terminal")

    # ymodem command
    ymodem_parser = subparsers.add_parser("ymodem", help="YMODEM file transfer")
    ymodem_parser.add_argument("file", help="File to transfer via YMODEM")

    args = parser.parse_args()

    if args.list_ports:
        list_ports()
        return

    if not args.command:
        parser.print_help()
        return

    if not args.port:
        print("Error: --port is required. Use --list-ports to see available ports.")
        list_ports()
        return

    board = HaaSBoard(args.port, args.baudrate)

    try:
        board.connect()

        if args.command == "push":
            if args.sync:
                board.push_directory(args.sync)
            elif args.files:
                for f in args.files:
                    board.push_file(f)
            else:
                print("Error: specify files or --sync DIR")
            board.soft_reset()

        elif args.command == "run":
            board.run_file(args.file)

        elif args.command == "terminal":
            board.terminal_mode()

        elif args.command == "ymodem":
            ymodem = HaaSYModem(args.port, args.baudrate)
            ymodem.transfer(args.file)

    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        board.disconnect()


if __name__ == "__main__":
    main()
