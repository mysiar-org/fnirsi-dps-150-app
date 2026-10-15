"""Turn the DPS-150 output on (port taken from config.py).

Usage::

    python set_on.py
"""

from __future__ import annotations

import asyncio

import config
from dps150 import DPS150, find_port


async def main() -> None:
    port = getattr(config, "PORT", None) or find_port()
    async with DPS150(port=port) as psu:
        state = await psu.set_output(True, verify=True)
        print(
            f"output {'on' if state.output_on else 'off'} "
            f"({state.set_voltage:.2f} V / {state.set_current:.3f} A)"
        )


if __name__ == "__main__":
    asyncio.run(main())
