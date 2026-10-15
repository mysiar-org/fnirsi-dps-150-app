"""Standalone async driver for the FNIRSI DPS-150 programmable power supply.

Wire protocol reverse-engineered by cho45 (https://github.com/cho45/fnirsi-dps-150);
documented at https://deepwiki.com/cho45/fnirsi-dps-150/4.1-communication-protocol

Packet layout, both directions::

    [header, command, type, length, data..., checksum]
    checksum = (type + length + sum(data)) % 256

Outgoing header 0xF1, incoming header 0xF0. Floats are little-endian IEEE-754.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

import serial_asyncio
from serial.tools import list_ports

HEADER_OUT = 0xF1
HEADER_IN = 0xF0

CMD_GET = 0xA1
CMD_BAUD = 0xB0
CMD_SET = 0xB1
CMD_SESSION = 0xC1

BAUD_RATE = 115200
BAUD_CHOICES = (9600, 19200, 38400, 57600, 115200)

VOLTAGE_SET = 193
CURRENT_SET = 194

GROUP_VOLTAGE_SET = 197
GROUP_CURRENT_SET = 198

OVP = 209
OCP = 210
OPP = 211
OTP = 212
LVP = 213

BRIGHTNESS = 214
VOLUME = 215
METERING_ENABLE = 216
OUTPUT_ENABLE = 219

INPUT_VOLTAGE = 192
OUTPUT_MEASUREMENTS = 195
TEMPERATURE = 196
OUTPUT_CAPACITY = 217
OUTPUT_ENERGY = 218
PROTECTION_STATE = 220
MODE = 221
MODEL_NAME = 222
HARDWARE_VERSION = 223
FIRMWARE_VERSION = 224
UPPER_LIMIT_VOLTAGE = 226
UPPER_LIMIT_CURRENT = 227

ALL = 255

PROTECTION_STATES = ("", "OVP", "OCP", "OPP", "OTP", "LVP", "REP")

USB_VID = 0x2E3C
USB_PID = 0x5740

STATE_LENGTH = 139


class DPS150Error(Exception):
    """Base error for this driver."""


class DPS150ConnectionError(DPS150Error):
    """Raised when the serial port cannot be opened or is closed."""


class DPS150TimeoutError(DPS150Error):
    """Raised when a expected response does not arrive in time."""


def find_port() -> Optional[str]:
    """Return the first serial device that looks like a DPS-150."""
    for port in list_ports.comports():
        if port.vid == USB_VID and port.pid == USB_PID:
            return port.device
    for port in list_ports.comports():
        if "AT32" in (port.description or "") or "DPS" in (port.device or ""):
            return port.device
    return None


def encode(command: int, type_code: int, data: bytes = b"") -> bytes:
    """Build an outgoing packet."""
    checksum = (type_code + len(data) + sum(data)) % 256
    return bytes([HEADER_OUT, command, type_code, len(data)]) + data + bytes([checksum])


def checksum_ok(type_code: int, data: bytes, checksum: int) -> bool:
    return (type_code + len(data) + sum(data)) % 256 == checksum


@dataclass
class DeviceInfo:
    model: str = ""
    hardware: str = ""
    firmware: str = ""


@dataclass
class State:
    input_voltage: float = 0.0
    set_voltage: float = 0.0
    set_current: float = 0.0
    output_voltage: float = 0.0
    output_current: float = 0.0
    output_power: float = 0.0
    temperature: float = 0.0
    groups: list[tuple[float, float]] = field(
        default_factory=lambda: [(0.0, 0.0)] * 6
    )
    ovp: float = 0.0
    ocp: float = 0.0
    opp: float = 0.0
    otp: float = 0.0
    lvp: float = 0.0
    brightness: int = 0
    volume: int = 0
    metering: bool = False
    capacity_ah: float = 0.0
    energy_wh: float = 0.0
    output_on: bool = False
    protection: str = ""
    mode: str = ""
    upper_limit_voltage: float = 0.0
    upper_limit_current: float = 0.0

    @classmethod
    def from_all_packet(cls, data: bytes) -> "State":
        if len(data) < STATE_LENGTH:
            raise DPS150Error(
                f"state packet too short: {len(data)} < {STATE_LENGTH} bytes"
            )
        f = lambda o: struct.unpack_from("<f", data, o)[0]
        return cls(
            input_voltage=f(0),
            set_voltage=f(4),
            set_current=f(8),
            output_voltage=f(12),
            output_current=f(16),
            output_power=f(20),
            temperature=f(24),
            groups=[(f(28 + 8 * i), f(32 + 8 * i)) for i in range(6)],
            ovp=f(76),
            ocp=f(80),
            opp=f(84),
            otp=f(88),
            lvp=f(92),
            brightness=data[96],
            volume=data[97],
            metering=data[98] == 1,
            capacity_ah=f(99),
            energy_wh=f(103),
            output_on=data[107] == 1,
            protection=PROTECTION_STATES[data[108]]
            if data[108] < len(PROTECTION_STATES)
            else "",
            mode="CV" if data[109] == 1 else "CC",
            upper_limit_voltage=f(111),
            upper_limit_current=f(115),
        )


class DPS150:
    """Async serial driver for the FNIRSI DPS-150."""

    def __init__(
        self,
        port: Optional[str] = None,
        on_state: Optional[Callable[["DPS150", State], None]] = None,
    ):
        self.port = port
        self.state = State()
        self.info = DeviceInfo()
        self.on_state = on_state
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._buffer = bytearray()
        self._pending: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self, port: Optional[str] = None) -> None:
        """Open the port and run the init handshake."""
        if self._connected:
            return
        resolved = port or self.port or find_port()
        if not resolved:
            raise DPS150ConnectionError("no DPS-150 serial port found")
        self.port = resolved
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=resolved,
                baudrate=BAUD_RATE,
                bytesize=8,
                parity="N",
                stopbits=1,
                rtscts=True,
            )
        except Exception as exc:
            raise DPS150ConnectionError(f"cannot open {resolved}: {exc}") from exc
        self._connected = True
        self._buffer.clear()
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._init()

    async def disconnect(self) -> None:
        """Close the session and the port."""
        if not self._connected:
            return
        try:
            await self._send(CMD_SESSION, 0, bytes([0]))
        except Exception:
            pass
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = None
        self._writer = None

    async def __aenter__(self) -> "DPS150":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.disconnect()

    async def _init(self) -> None:
        await asyncio.sleep(0.1)
        await self._send(CMD_SESSION, 0, bytes([1]))
        await asyncio.sleep(0.15)
        baud_index = BAUD_CHOICES.index(BAUD_RATE) + 1
        await self._send(CMD_BAUD, 0, bytes([baud_index]))
        await asyncio.sleep(0.15)
        await self.get_info()
        await self.refresh()

    async def _send(self, command: int, type_code: int, data: bytes = b"") -> None:
        if not self._writer:
            raise DPS150ConnectionError("not connected")
        packet = encode(command, type_code, data)
        async with self._write_lock:
            self._writer.write(packet)
            await self._writer.drain()
            await asyncio.sleep(0.02)

    async def _read_loop(self) -> None:
        while self._connected and self._reader:
            try:
                chunk = await asyncio.wait_for(self._reader.read(1024), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            except Exception:
                return
            if not chunk:
                return
            self._buffer.extend(chunk)
            self._consume_buffer()

    def _consume_buffer(self) -> None:
        buf = self._buffer
        while True:
            start = buf.find(HEADER_IN)
            if start < 0:
                buf.clear()
                return
            if start > 0:
                del buf[:start]
            if len(buf) < 5:
                return
            if buf[1] != CMD_GET:
                del buf[0]
                continue
            length = buf[3]
            total = 5 + length
            if len(buf) < total:
                return
            type_code = buf[2]
            data = bytes(buf[4 : 4 + length])
            checksum = buf[4 + length]
            del buf[:total]
            if not checksum_ok(type_code, data, checksum):
                continue
            self._handle(type_code, data)

    def _handle(self, type_code: int, data: bytes) -> None:
        try:
            if type_code == ALL:
                self.state = State.from_all_packet(data)
            elif type_code == INPUT_VOLTAGE:
                self.state.input_voltage = struct.unpack_from("<f", data)[0]
            elif type_code == OUTPUT_MEASUREMENTS and len(data) >= 12:
                self.state.output_voltage = struct.unpack_from("<f", data, 0)[0]
                self.state.output_current = struct.unpack_from("<f", data, 4)[0]
                self.state.output_power = struct.unpack_from("<f", data, 8)[0]
            elif type_code == TEMPERATURE:
                self.state.temperature = struct.unpack_from("<f", data)[0]
            elif type_code == OUTPUT_CAPACITY:
                self.state.capacity_ah = struct.unpack_from("<f", data)[0]
            elif type_code == OUTPUT_ENERGY:
                self.state.energy_wh = struct.unpack_from("<f", data)[0]
            elif type_code == OUTPUT_ENABLE:
                self.state.output_on = data[0] == 1
            elif type_code == METERING_ENABLE:
                self.state.metering = data[0] == 1
            elif type_code == PROTECTION_STATE:
                if data[0] < len(PROTECTION_STATES):
                    self.state.protection = PROTECTION_STATES[data[0]]
            elif type_code == MODE:
                self.state.mode = "CV" if data[0] == 1 else "CC"
            elif type_code == MODEL_NAME:
                self.info.model = _text(data)
            elif type_code == HARDWARE_VERSION:
                self.info.hardware = _text(data)
            elif type_code == FIRMWARE_VERSION:
                self.info.firmware = _text(data)
            elif type_code == UPPER_LIMIT_VOLTAGE:
                self.state.upper_limit_voltage = struct.unpack_from("<f", data)[0]
            elif type_code == UPPER_LIMIT_CURRENT:
                self.state.upper_limit_current = struct.unpack_from("<f", data)[0]
        except (struct.error, IndexError):
            return
        pending = self._pending.get(type_code)
        if pending and not pending.done():
            pending.set_result(data)
        if self.on_state:
            try:
                self.on_state(self, self.state)
            except Exception:
                pass

    async def _get(self, type_code: int, timeout: float = 1.0) -> bytes:
        """Send a GET and return the payload of the matching response."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[type_code] = future
        try:
            await self._send(CMD_GET, type_code)
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError as exc:
            raise DPS150TimeoutError(f"no response for type {type_code}") from exc
        finally:
            self._pending.pop(type_code, None)

    async def get_info(self) -> DeviceInfo:
        """Request model, hardware and firmware strings."""
        if not self.info.model:
            await self._get(MODEL_NAME)
        if not self.info.hardware:
            await self._get(HARDWARE_VERSION)
        if not self.info.firmware:
            await self._get(FIRMWARE_VERSION)
        return self.info

    async def refresh(self, timeout: float = 1.0) -> State:
        """Fetch the full 139-byte state snapshot."""
        await self._get(ALL, timeout)
        return self.state

    async def set_voltage(self, volts: float, verify: bool = False) -> State:
        await self._send(CMD_SET, VOLTAGE_SET, struct.pack("<f", volts))
        return await self.refresh() if verify else self.state

    async def set_current(self, amps: float, verify: bool = False) -> State:
        await self._send(CMD_SET, CURRENT_SET, struct.pack("<f", amps))
        return await self.refresh() if verify else self.state

    async def set_output(self, enabled: bool, verify: bool = False) -> State:
        await self._send(CMD_SET, OUTPUT_ENABLE, bytes([1 if enabled else 0]))
        return await self.refresh() if verify else self.state

    async def set_ovp(self, volts: float) -> None:
        await self._send(CMD_SET, OVP, struct.pack("<f", volts))

    async def set_ocp(self, amps: float) -> None:
        await self._send(CMD_SET, OCP, struct.pack("<f", amps))

    async def set_opp(self, watts: float) -> None:
        await self._send(CMD_SET, OPP, struct.pack("<f", watts))

    async def set_otp(self, celsius: float) -> None:
        await self._send(CMD_SET, OTP, struct.pack("<f", celsius))

    async def set_lvp(self, volts: float) -> None:
        await self._send(CMD_SET, LVP, struct.pack("<f", volts))

    async def set_brightness(self, level: int) -> None:
        _check_range(level, 0, 255, "brightness")
        await self._send(CMD_SET, BRIGHTNESS, bytes([level]))

    async def set_volume(self, level: int) -> None:
        _check_range(level, 0, 255, "volume")
        await self._send(CMD_SET, VOLUME, bytes([level]))

    async def set_metering(self, enabled: bool) -> None:
        await self._send(CMD_SET, METERING_ENABLE, bytes([1 if enabled else 0]))

    async def set_group(self, group: int, volts: float, amps: float) -> None:
        _check_range(group, 1, 6, "group")
        await self._send(
            CMD_SET, GROUP_VOLTAGE_SET + (group - 1) * 2, struct.pack("<f", volts)
        )
        await self._send(
            CMD_SET, GROUP_CURRENT_SET + (group - 1) * 2, struct.pack("<f", amps)
        )

    async def load_group(self, group: int, verify: bool = False) -> State:
        _check_range(group, 1, 6, "group")
        await self.refresh()
        volts, amps = self.state.groups[group - 1]
        await self.set_voltage(volts)
        await self.set_current(amps)
        return await self.refresh() if verify else self.state

    async def monitor(self, interval: float = 0.5) -> None:
        """Poll the full state until cancelled (the device also streams telemetry)."""
        while self._connected:
            await self.refresh()
            await asyncio.sleep(interval)


def _text(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def _check_range(value: int, low: int, high: int, name: str) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be {low}-{high}, got {value}")


async def _demo() -> None:
    async with DPS150() as psu:
        info = await psu.get_info()
        print(f"{info.model} hw={info.hardware} fw={info.firmware} port={psu.port}")
        state = await psu.refresh()
        print(
            f"in={state.input_voltage:.2f}V set={state.set_voltage:.2f}V/"
            f"{state.set_current:.2f}A out={state.output_voltage:.3f}V "
            f"{state.output_current:.3f}A {state.output_power:.3f}W "
            f"{state.temperature:.1f}C mode={state.mode} on={state.output_on} "
            f"prot={state.protection or 'OK'}"
        )


if __name__ == "__main__":
    asyncio.run(_demo())
