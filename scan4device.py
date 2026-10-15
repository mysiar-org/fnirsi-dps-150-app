"""Find the FNIRSI DPS-150 serial port, show it, and store it in config.py.

Usage::

    python scan4device.py              # detect, display, write config.py
    python scan4device.py --dry-run    # detect and display only
    python scan4device.py --port /dev/ttyACM2
    python scan4device.py --device     # store the plain /dev/tty* path
"""

from __future__ import annotations

import argparse
import glob
import os
import re
from typing import Optional

from serial.tools import list_ports

USB_VID = 0x2E3C
USB_PID = 0x5740
BY_ID = "/dev/serial/by-id"
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")


class PortInfo:
    def __init__(self, port):
        self.device = port.device
        self.description = port.description or ""
        self.hwid = port.hwid or ""
        self.vid = port.vid
        self.pid = port.pid
        self.serial_number = port.serial_number

    @property
    def vidpid(self) -> str:
        if self.vid is None or self.pid is None:
            return "-"
        return f"{self.vid:04x}:{self.pid:04x}"

    @property
    def is_dps150(self) -> bool:
        if self.vid == USB_VID and self.pid == USB_PID:
            return True
        text = f"{self.description} {self.device}".upper()
        return "AT32" in text or "DPS-150" in text or "DPS150" in text

    @property
    def stable_path(self) -> Optional[str]:
        """Prefer a friendly /dev symlink, else the udev /dev/serial/by-id one."""
        target = os.path.realpath(self.device)
        custom = [
            link
            for link in sorted(glob.glob("/dev/tty*"))
            if os.path.islink(link) and os.path.realpath(link) == target
        ]
        if custom:
            return custom[0]
        for link in sorted(glob.glob(os.path.join(BY_ID, "*"))):
            if os.path.realpath(link) == target:
                return link
        return None


def scan() -> list[PortInfo]:
    return [PortInfo(p) for p in list_ports.comports()]


def display(ports: list[PortInfo], selected: Optional[PortInfo]) -> None:
    print("Serial ports found:")
    if not ports:
        print("  (none)")
    width = max((len(p.device) for p in ports), default=12)
    for p in ports:
        mark = " <-- FNIRSI DPS-150" if p is selected else ""
        print(f"  {p.device:<{width}}  {p.vidpid:<10}  {p.description}{mark}")
        if p is selected and p.stable_path:
            print(f"  {'':<{width}}  stable path: {p.stable_path}")


def choose(ports: list[PortInfo]) -> Optional[PortInfo]:
    for p in ports:
        if p.vid == USB_VID and p.pid == USB_PID:
            return p
    for p in ports:
        if p.is_dps150:
            return p
    return None


def resolve_port(port: PortInfo, prefer_device: bool) -> str:
    if prefer_device:
        return port.device
    return port.stable_path or port.device


def update_config(path: str) -> tuple[Optional[str], str]:
    with open(CONFIG, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r'^PORT\s*=\s*["\'](.*?)["\']', text, flags=re.MULTILINE)
    previous = match.group(1) if match else None
    if match:
        text = re.sub(rf'^PORT\s*=\s*["\'].*?["\']', f'PORT = "{path}"', text, count=1, flags=re.MULTILINE)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f'PORT = "{path}"\n'
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write(text)
    return previous, path


def main() -> int:
    parser = argparse.ArgumentParser(description="Locate the DPS-150 and update config.py")
    parser.add_argument("--port", help="use this path instead of detecting")
    parser.add_argument("--device", action="store_true", help="store the plain /dev/tty* path")
    parser.add_argument("--dry-run", action="store_true", help="do not write config.py")
    args = parser.parse_args()

    ports = scan()
    selected = choose(ports)

    if args.port:
        display(ports, selected)
        target = args.port
        print(f"\nForced port: {target}")
    else:
        display(ports, selected)
        if not selected:
            print("\nNo FNIRSI DPS-150 found.")
            return 1
        target = resolve_port(selected, args.device)
        print(f"\nDetected DPS-150: {selected.device}")
        print(f"Port to use:      {target}")

    if args.dry_run:
        print("Dry run: config.py not changed.")
        return 0

    previous, current = update_config(target)
    print(f'config.py: PORT = "{previous}" -> "{current}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
