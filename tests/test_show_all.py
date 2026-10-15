"""Hardware test: connect to the DPS-150 and print everything it reports.

Reads the device info (model / hardware / firmware) and the full state
snapshot, then prints every field. Read-only: the output is never enabled
and no setpoints are changed.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from dps150 import DPS150, find_port
from serial.tools import list_ports


def _serial_number(port: str) -> str:
    if not port:
        return ""
    target = os.path.realpath(port)
    for candidate in list_ports.comports():
        if os.path.realpath(candidate.device) == target:
            return candidate.serial_number or ""
    return ""


def _format_uptime(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


class ShowAllTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        port = getattr(config, "PORT", None) or find_port()
        if not port:
            self.skipTest("no DPS-150 port configured or detected")
        self.psu = DPS150(port=port)
        await self.psu.connect()
        self._connected_at = time.monotonic()

    async def asyncTearDown(self):
        psu = getattr(self, "psu", None)
        if psu is not None and psu.connected:
            await psu.disconnect()

    async def test_show_all(self):
        info = await self.psu.get_info()
        print("\n=== Device info ===")
        print(f"  model     : {info.model}")
        print(f"  hardware  : {info.hardware}")
        print(f"  firmware  : {info.firmware}")
        print(f"  serial    : {_serial_number(self.psu.port)}")
        print(f"  port      : {self.psu.port}")

        state = await self.psu.refresh()
        print("\n=== Measurements ===")
        print(f"  input voltage      : {state.input_voltage:.2f} V")
        print(f"  set voltage        : {state.set_voltage:.2f} V")
        print(f"  set current        : {state.set_current:.3f} A")
        print(f"  output voltage     : {state.output_voltage:.3f} V")
        print(f"  output current     : {state.output_current:.3f} A")
        print(f"  output power       : {state.output_power:.3f} W")
        print(f"  temperature        : {state.temperature:.1f} \u00b0C")
        uptime = _format_uptime(time.monotonic() - self._connected_at)
        print(f"  session uptime     : {uptime}")
        print(f"  mode               : {state.mode}")
        print(f"  output             : {'ON' if state.output_on else 'OFF'}")
        print(f"  protection         : {state.protection or 'OK'}")

        print("\n=== Limits / protections ===")
        print(f"  OVP                : {state.ovp:.2f} V")
        print(f"  OCP                : {state.ocp:.3f} A")
        print(f"  OPP                : {state.opp:.2f} W")
        print(f"  OTP                : {state.otp:.1f} \u00b0C")
        print(f"  LVP                : {state.lvp:.2f} V")
        print(f"  upper limit voltage: {state.upper_limit_voltage:.2f} V")
        print(f"  upper limit current: {state.upper_limit_current:.3f} A")

        print("\n=== Settings ===")
        print(f"  brightness         : {state.brightness}")
        print(f"  volume             : {state.volume}")
        print(f"  metering           : {state.metering}")

        print("\n=== Counters ===")
        print(f"  capacity           : {state.capacity_ah:.3f} Ah")
        print(f"  energy             : {state.energy_wh:.3f} Wh")

        print("\n=== Groups ===")
        for index, (volts, amps) in enumerate(state.groups, start=1):
            print(f"  group {index}            : {volts:.2f} V / {amps:.3f} A")

        self.assertTrue(info.model, "device returned an empty model name")


if __name__ == "__main__":
    unittest.main(verbosity=2)
