"""Ask for a voltage and send it to the DPS-150 (port taken from config.py).

Usage::

    python set_volts.py
"""

from __future__ import annotations

import asyncio
import re

import config
from dps150 import DPS150, find_port

VOLTAGE_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")
MIN_VOLTAGE = 0.0
MAX_VOLTAGE = 30.0


def parse_voltage(text: str) -> float:
    """Return the voltage encoded by text, or raise ValueError if it is invalid."""
    value = text.strip()
    if not VOLTAGE_PATTERN.match(value):
        raise ValueError("digits only, e.g. 12 or 3.5")
    volts = float(value)
    if not MIN_VOLTAGE <= volts <= MAX_VOLTAGE:
        raise ValueError(f"must be {MIN_VOLTAGE:g}-{MAX_VOLTAGE:g} V")
    return volts


def ask_voltage() -> float:
    prompt = f"Voltage to set ({MIN_VOLTAGE:g}-{MAX_VOLTAGE:g} V, e.g. 12 or 3.5): "
    while True:
        try:
            text = input(prompt)
        except EOFError:
            raise SystemExit("\nno input")
        if not text.strip():
            raise SystemExit("cancelled")
        try:
            return parse_voltage(text)
        except ValueError as exc:
            print(f"Invalid input: {exc}")


async def main() -> None:
    volts = ask_voltage()
    port = getattr(config, "PORT", None) or find_port()
    async with DPS150(port=port) as psu:
        state = await psu.set_voltage(volts, verify=True)
        print(
            f"set {state.set_voltage:.2f} V "
            f"(output {'on' if state.output_on else 'off'})"
        )


if __name__ == "__main__":
    asyncio.run(main())
