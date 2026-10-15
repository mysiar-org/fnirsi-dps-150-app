"""Hardware test: enable output, sweep 1-12 V, disable output, restore settings.

The sweep is intentionally slow so the change is visible on the device's own
screen. Note: USB setpoints are only honored while the front panel is locked;
the driver's session-open command requests that lock automatically.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from dps150 import DPS150, find_port


class VoltageSweepTest(unittest.IsolatedAsyncioTestCase):
    START_VOLTAGE = 1
    END_VOLTAGE = 12
    SETTLE = 1.5
    SAMPLE_INTERVAL = 0.5

    async def asyncSetUp(self):
        port = getattr(config, "PORT", None) or find_port()
        if not port:
            self.skipTest("no DPS-150 port configured or detected")
        self.psu = DPS150(port=port)
        await self.psu.connect()
        original = await self.psu.refresh()
        self.saved = {
            "voltage": original.set_voltage,
            "current": original.set_current,
            "output_on": original.output_on,
        }
        print(f"\nsaved settings: {self.saved}")

    async def asyncTearDown(self):
        psu = getattr(self, "psu", None)
        if psu is None or not psu.connected:
            return
        try:
            await psu.set_output(False, verify=True)
            await psu.set_voltage(self.saved["voltage"], verify=True)
            await psu.set_current(self.saved["current"], verify=True)
            if self.saved["output_on"]:
                await psu.set_output(True, verify=True)
            state = await psu.refresh()
            print(
                "restored settings: "
                f"voltage={state.set_voltage:.2f} "
                f"current={state.set_current:.2f} "
                f"output_on={state.output_on}"
            )
        finally:
            await psu.disconnect()

    async def test_sweep_voltage_with_output_enabled(self):
        await self.psu.set_current(self.saved["current"])
        state = await self.psu.set_output(True, verify=True)
        self.assertTrue(state.output_on, "output did not turn on")

        previous = None
        for volts in range(self.START_VOLTAGE, self.END_VOLTAGE + 1):
            target = float(volts)
            state = await self.psu.set_voltage(target, verify=True)
            self.assertAlmostEqual(
                state.set_voltage, target, places=2,
                msg=f"setpoint readback after setting {target} V",
            )
            if previous is not None:
                self.assertGreater(
                    state.set_voltage, previous,
                    "setpoint did not increase across the sweep",
                )
            previous = state.set_voltage
            elapsed = 0.0
            while elapsed < self.SETTLE:
                await asyncio.sleep(self.SAMPLE_INTERVAL)
                elapsed += self.SAMPLE_INTERVAL
                live = await self.psu.refresh()
                print(
                    f"  set {target:5.2f}V -> measured {live.output_voltage:6.3f}V "
                    f"{live.output_current:.3f}A {live.output_power:.3f}W {live.mode} "
                    f"(t={elapsed:.1f}s)"
                )

        state = await self.psu.set_output(False, verify=True)
        self.assertFalse(state.output_on, "output did not turn off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
