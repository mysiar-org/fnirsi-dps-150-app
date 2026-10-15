"""Ask for a current and send it to the DPS-150 (port taken from config.py).

Usage::

    python set_amps.py
"""

from __future__ import annotations

import asyncio
import re

import config
from dps150 import DPS150, find_port

CURRENT_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")
MIN_CURRENT = 0.0
MAX_CURRENT = 5.1


def parse_current(text: str) -> float:
    """Return the current encoded by text, or raise ValueError if it is invalid."""
    value = text.strip()
    if not CURRENT_PATTERN.match(value):
        raise ValueError("digits only, e.g. 1 or 0.5")
    amps = float(value)
    if not MIN_CURRENT <= amps <= MAX_CURRENT:
        raise ValueError(f"must be {MIN_CURRENT:g}-{MAX_CURRENT:g} A")
    return amps


def ask_current() -> float:
    prompt = f"Current to set ({MIN_CURRENT:g}-{MAX_CURRENT:g} A, e.g. 1 or 0.5): "
    while True:
        try:
            text = input(prompt)
        except EOFError:
            raise SystemExit("\nno input")
        if not text.strip():
            raise SystemExit("cancelled")
        try:
            return parse_current(text)
        except ValueError as exc:
            print(f"Invalid input: {exc}")


async def main() -> None:
    amps = ask_current()
    port = getattr(config, "PORT", None) or find_port()
    async with DPS150(port=port) as psu:
        state = await psu.set_current(amps, verify=True)
        print(
            f"set {state.set_current:.3f} A "
            f"(output {'on' if state.output_on else 'off'})"
        )


if __name__ == "__main__":
    asyncio.run(main())
