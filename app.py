"""Tkinter control panel for the DPS-150 (port taken from config.py).

Usage::

    python app.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import config
from dps150 import DPS150, State, find_port
from serial.tools import list_ports

REFRESH_MS = 250
NUMBER_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
SETTING_KEYS = ("VOLTAGE", "VOLTAGE_STEP", "CURRENT", "CURRENT_STEP")


def load_settings() -> dict[str, object]:
    return {key: getattr(config, key) for key in SETTING_KEYS if hasattr(config, key)}


def _format_setting(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)


def save_settings(mapping: dict[str, object]) -> None:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        lines = []

    remaining = {key: _format_setting(value) for key, value in mapping.items()}
    for index, line in enumerate(lines):
        match = re.match(r"^(\w+)\s*=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            lines[index] = f"{key} = {remaining.pop(key)}"
    for key, text in remaining.items():
        lines.append(f"{key} = {text}")

    text = "\n".join(lines).rstrip("\n") + "\n"
    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        handle.write(text)


def _format_uptime(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


DIGIT_FONT = ("DejaVu Sans Mono", 40, "bold")
UNIT_FONT = ("DejaVu Sans Mono", 18, "bold")
HEADER_FONT = ("TkDefaultFont", 10)
SMALL_FONT = ("TkDefaultFont", 10)
MEASURED_FONT = ("TkDefaultFont", 12, "bold")

LED_ON_COLOR = "#2ecc71"
LED_OFF_COLOR = "#9aa0a6"
ERROR_COLOR = "#c0392b"
MEASURED_COLOR = "#2e7d32"
VOLTAGE_COLOR = "#e0aa00"
CURRENT_COLOR = "#5bc8ff"
POWER_COLOR = "#7ed957"
DISPLAY_BG_COLOR = "#000000"
DOT_DIAMETER = 38

PADX = 8
PADY = 8


class Backend:
    """Runs the async driver on a background thread."""

    def __init__(self, port: str | None):
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="dps150", daemon=True)
        self.psu: DPS150 | None = None
        self.state = State()
        self.connected = False
        self.error: str | None = None
        self._stop: asyncio.Event | None = None

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._session())

    async def _session(self) -> None:
        try:
            self.psu = DPS150(port=self.port, on_state=self._on_state)
            await self.psu.connect()
        except Exception as exc:
            self.error = str(exc)
            self.psu = None
            return
        self.connected = True
        self._stop = asyncio.Event()
        try:
            while not self._stop.is_set():
                try:
                    await self.psu.refresh()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self._stop.wait(), REFRESH_MS / 1000)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.psu.disconnect()
            self.connected = False

    def _on_state(self, psu: DPS150, state: State) -> None:
        self.state = state

    def _submit(self, coro) -> None:
        if self.psu is not None and self.connected:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            coro.close()

    def set_voltage(self, volts: float) -> None:
        self._submit(self.psu.set_voltage(volts, verify=True))

    def set_current(self, amps: float) -> None:
        self._submit(self.psu.set_current(amps, verify=True))

    def set_output(self, enabled: bool) -> None:
        self._submit(self.psu.set_output(enabled, verify=True))

    def close(self) -> None:
        if self._stop is None:
            return

        async def shutdown() -> None:
            try:
                if self.connected and self.psu is not None:
                    await self.psu.set_output(False, verify=True)
            except Exception:
                pass
            finally:
                self._stop.set()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=2)
        except Exception:
            self.loop.call_soon_threadsafe(self._stop.set)


class QuantityRow:
    """One editable quantity: big digits, step selector, +/- and a typed entry.

    Placed into ``parent``'s grid (rows 1+, below a header row) so several
    sections sharing the same grid layout line up column for column.
    """

    def __init__(
        self,
        parent: ttk.Frame,
        unit: str,
        steps: tuple[str, ...],
        limits: tuple[float, float],
        decimals: int,
        format_spec: str,
        on_send,
        color: str | None = None,
    ):
        self.unit = unit
        self.limits = limits
        self.decimals = decimals
        self.format_spec = format_spec
        self.on_send = on_send
        self.value = limits[0]

        self.digits_var = tk.StringVar(value=self._format(self.value))
        self.step_var = tk.StringVar(value=steps[0])
        self.entry_var = tk.StringVar(value=self._format(self.value))
        self.measured_var = tk.StringVar(value="measured  --")
        self.error_var = tk.StringVar(value="")

        ttk.Label(parent, text="Step", font=HEADER_FONT).grid(
            row=0, column=1, padx=PADX, sticky="w"
        )
        ttk.Label(parent, text="Set value", font=HEADER_FONT).grid(
            row=0, column=4, sticky="w"
        )

        if color is not None:
            readout = tk.Frame(parent, background=DISPLAY_BG_COLOR)
            readout.grid(row=1, column=0, sticky="w", padx=(0, PADX), pady=(0, 2))
            digits = tk.Label(
                readout,
                textvariable=self.digits_var,
                font=DIGIT_FONT,
                anchor="e",
                background=DISPLAY_BG_COLOR,
                foreground=color,
            )
            unit_label = tk.Label(
                readout,
                text=unit,
                font=UNIT_FONT,
                anchor="w",
                background=DISPLAY_BG_COLOR,
                foreground=color,
            )
            digits.grid(row=0, column=0, sticky="e", padx=(6, 2))
            unit_label.grid(row=0, column=1, sticky="sw", padx=(0, 6), pady=(0, 6))
        else:
            readout = ttk.Frame(parent)
            readout.grid(row=1, column=0, sticky="w", padx=(0, PADX))
            digits = ttk.Label(
                readout, textvariable=self.digits_var, font=DIGIT_FONT, anchor="e"
            )
            unit_label = ttk.Label(readout, text=unit, font=UNIT_FONT, anchor="w")
            digits.grid(row=0, column=0, sticky="e")
            unit_label.grid(row=0, column=1, sticky="sw", padx=(4, 0), pady=(0, 6))

        self.step_box = ttk.Combobox(
            parent,
            textvariable=self.step_var,
            values=list(steps),
            width=7,
            state="readonly",
        )
        self.step_box.grid(row=1, column=1, padx=PADX, pady=PADY)
        self.step_box.bind("<Return>", self._on_enter)

        ttk.Button(
            parent, text="\u2212", width=3, command=lambda: self._nudge(-1)
        ).grid(row=1, column=2, padx=(0, 4))
        ttk.Button(parent, text="+", width=3, command=lambda: self._nudge(1)).grid(
            row=1, column=3, padx=(0, PADX)
        )

        self.entry = ttk.Entry(
            parent, textvariable=self.entry_var, width=10, justify="right"
        )
        self.entry.grid(row=1, column=4, pady=PADY)
        self.entry.bind("<Return>", self._on_enter)

        ttk.Label(
            parent,
            textvariable=self.measured_var,
            font=MEASURED_FONT,
            foreground=MEASURED_COLOR,
        ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(0, 4))
        self.error_label = ttk.Label(
            parent,
            textvariable=self.error_var,
            font=SMALL_FONT,
            foreground=ERROR_COLOR,
        )
        self.error_label.grid(row=3, column=0, columnspan=5, sticky="w")
        self.error_label.grid_remove()
        self.error_var.trace_add("write", self._toggle_error_label)

    def _toggle_error_label(self, *_):
        if self.error_var.get():
            self.error_label.grid()
        else:
            self.error_label.grid_remove()

    def _format(self, value: float) -> str:
        return format(value, self.format_spec)

    def _parse(self, text: str) -> float:
        text = text.strip()
        if not NUMBER_PATTERN.match(text):
            raise ValueError("digits only, e.g. 12 or 3.5")
        value = float(text)
        low, high = self.limits
        if not low <= value <= high:
            raise ValueError(f"must be {low:g}-{high:g} {self.unit}")
        return value

    def _entry_focused(self) -> bool:
        try:
            return self.entry is self.entry.focus_get()
        except (KeyError, tk.TclError):
            return False

    def _set_value(self, value: float) -> None:
        low, high = self.limits
        value = round(min(max(value, low), high), self.decimals)
        self.value = value
        text = self._format(value)
        self.digits_var.set(text)
        if not self._entry_focused():
            self.entry_var.set(text)

    def _nudge(self, direction: int) -> None:
        try:
            step = float(self.step_var.get())
        except ValueError:
            return
        self.error_var.set("")
        self._set_value(self.value + direction * step)
        self.on_send(self.value)

    def _on_enter(self, _event=None) -> None:
        try:
            value = self._parse(self.entry_var.get())
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.error_var.set("")
        self._set_value(value)
        self.on_send(self.value)

    def update_from_device(self, setpoint: float, measured: float) -> None:
        self._set_value(setpoint)
        self.measured_var.set(
            f"measured  {format(measured, self.format_spec)} {self.unit}"
        )


class App(tk.Tk):
    def __init__(self, backend: Backend):
        super().__init__()
        self.backend = backend
        self.title("DPS-150")
        self.resizable(False, False)
        self._error_shown = False
        self._connected_at: float | None = None

        try:
            ttk.Style(self).theme_use("clam")
        except tk.TclError:
            pass

        self._build_header()
        self._build_controls()
        self._build_output()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(REFRESH_MS, self._poll)

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(16, 12, 16, 0))
        header.pack(fill="x")
        title_row = ttk.Frame(header)
        title_row.pack(fill="x")
        ttk.Label(
            title_row, text="FNIRSI DPS-150", font=("TkDefaultFont", 13, "bold")
        ).pack(side="left")
        serial = self._get_serial_number()
        if serial:
            ttk.Label(title_row, text=serial, font=("TkDefaultFont", 9)).pack(
                side="left", padx=(8, 0)
            )
        self.status_var = tk.StringVar(value="connecting\u2026")
        ttk.Label(header, textvariable=self.status_var, font=SMALL_FONT).pack(
            anchor="w"
        )

    def _get_serial_number(self) -> str:
        if not self.backend.port:
            return ""
        target = os.path.realpath(self.backend.port)
        for port in list_ports.comports():
            if os.path.realpath(port.device) == target:
                return port.serial_number or ""
        return ""

    def _build_controls(self) -> None:
        self.voltage = self._build_section(
            "Voltage",
            "V",
            ("0.01", "0.1", "0.5", "1", "2", "5"),
            (0.0, 30.0),
            2,
            "05.2f",
            self.backend.set_voltage,
            color=VOLTAGE_COLOR,
        )
        self.current = self._build_section(
            "Current",
            "A",
            ("0.001", "0.01", "0.1", "0.5", "1"),
            (0.0, 5.1),
            3,
            "04.3f",
            self.backend.set_current,
            color=CURRENT_COLOR,
        )
        self._pending_push = {}
        settings = load_settings()
        self._restore(
            self.voltage,
            "voltage",
            settings.get("VOLTAGE"),
            settings.get("VOLTAGE_STEP"),
        )
        self._restore(
            self.current,
            "current",
            settings.get("CURRENT"),
            settings.get("CURRENT_STEP"),
        )

    def _restore(self, row: QuantityRow, name: str, value, step) -> None:
        if step is not None:
            try:
                target = float(step)
            except (TypeError, ValueError):
                target = None
            if target is not None:
                for option in row.step_box.cget("values"):
                    if float(option) == target:
                        row.step_var.set(option)
                        break
        if value is None:
            return
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return
        row._set_value(numeric)
        self._pending_push[name] = row.value

    def _build_section(
        self,
        title: str,
        unit: str,
        steps,
        limits,
        decimals,
        format_spec,
        on_send,
        color: str | None = None,
    ) -> QuantityRow:
        outer = ttk.Frame(self, padding=(0, 10, 0, 0))
        outer.pack(fill="x", padx=16)
        border = tk.Frame(
            outer,
            bd=1,
            relief="ridge",
            bg=ttk.Style(outer).lookup("TLabelframe", "background"),
        )
        border.pack(fill="x")
        ttk.Label(border, text=title, font=HEADER_FONT, anchor="w").pack(
            fill="x", padx=PADX, pady=(4, 0)
        )
        inner = ttk.Frame(border, padding=(PADX, 6, PADX, 4))
        inner.pack(fill="x")
        return QuantityRow(
            inner, unit, steps, limits, decimals, format_spec, on_send, color=color
        )

    def _build_output(self) -> None:
        outer = ttk.Frame(self, padding=(0, 10, 0, 16))
        outer.pack(fill="x", padx=16)
        border = tk.Frame(
            outer,
            bd=1,
            relief="ridge",
            bg=ttk.Style(outer).lookup("TLabelframe", "background"),
        )
        border.pack(fill="x")
        ttk.Label(border, text="Output", font=HEADER_FONT, anchor="w").pack(
            fill="x", padx=PADX, pady=(4, 0)
        )
        frame = ttk.Frame(border, padding=(PADX, 6, PADX, 4))
        frame.pack(fill="x")

        self.toggle_button = ttk.Button(
            frame, text="Turn ON", width=12, command=self._toggle_output
        )
        self.toggle_button.grid(row=1, column=0, padx=(0, PADX), pady=PADY, sticky="w")

        self.led = tk.Canvas(
            frame,
            width=DOT_DIAMETER,
            height=DOT_DIAMETER,
            highlightthickness=0,
            bg=ttk.Style(frame).lookup("TLabelframe", "background"),
        )
        self.led_item = self.led.create_oval(
            1,
            1,
            DOT_DIAMETER - 1,
            DOT_DIAMETER - 1,
            fill=LED_OFF_COLOR,
            outline="",
        )
        self.led.grid(row=1, column=1, padx=(0, PADX), pady=PADY, sticky="w")

        self.output_status = tk.StringVar(value="OFF")
        self.output_label = tk.Label(
            frame,
            textvariable=self.output_status,
            font=("DejaVu Sans", 18, "bold"),
            fg=LED_OFF_COLOR,
            width=4,
            anchor="w",
        )
        self.output_label.grid(row=1, column=2, pady=PADY, sticky="w")

        legend = ttk.Frame(frame)
        legend.grid(row=1, column=3, padx=(PADX, 0), pady=PADY, sticky="w")
        tk.Label(legend, text="\u25cf", fg=LED_ON_COLOR).grid(row=0, column=0)
        ttk.Label(legend, text="on", font=SMALL_FONT).grid(row=0, column=1, sticky="w")
        tk.Label(legend, text="\u25cf", fg=LED_OFF_COLOR).grid(row=1, column=0)
        ttk.Label(legend, text="off", font=SMALL_FONT).grid(row=1, column=1, sticky="w")

        readout = tk.Frame(frame, background=DISPLAY_BG_COLOR)
        readout.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.power_var = tk.StringVar(value="00.00")
        digits = tk.Label(
            readout,
            textvariable=self.power_var,
            font=DIGIT_FONT,
            anchor="e",
            background=DISPLAY_BG_COLOR,
            foreground=POWER_COLOR,
        )
        unit_label = tk.Label(
            readout,
            text="W",
            font=UNIT_FONT,
            anchor="w",
            background=DISPLAY_BG_COLOR,
            foreground=POWER_COLOR,
        )
        digits.grid(row=0, column=0, sticky="e", padx=(6, 2))
        unit_label.grid(row=0, column=1, sticky="sw", padx=(0, 6), pady=(0, 6))

    def _toggle_output(self) -> None:
        self.backend.set_output(not self.backend.state.output_on)

    def _set_output_indicator(self, on: bool) -> None:
        color = LED_ON_COLOR if on else LED_OFF_COLOR
        self.led.itemconfigure(self.led_item, fill=color)
        self.output_label.configure(fg=color)
        self.output_status.set("ON" if on else "OFF")
        self.toggle_button.configure(text="Turn OFF" if on else "Turn ON")

    def _poll(self) -> None:
        if not self.backend.connected:
            if self.backend.error and not self._error_shown:
                self._error_shown = True
                self.status_var.set("not connected")
                messagebox.showerror(
                    "DPS-150", f"Cannot connect:\n{self.backend.error}"
                )
                self._on_close()
                return
            self.after(REFRESH_MS, self._poll)
            return
        state = self.backend.state
        if self._pending_push:
            if "voltage" in self._pending_push:
                self.backend.set_voltage(self._pending_push.pop("voltage"))
            if "current" in self._pending_push:
                self.backend.set_current(self._pending_push.pop("current"))
        if self._connected_at is None:
            self._connected_at = time.monotonic()
        uptime = _format_uptime(time.monotonic() - self._connected_at)
        self.status_var.set(
            f"{state.mode}   in {state.input_voltage:.2f} V   "
            f"{state.temperature:.1f} \u00b0C   up {uptime}"
        )
        self.voltage.update_from_device(state.set_voltage, state.output_voltage)
        self.current.update_from_device(state.set_current, state.output_current)
        self.power_var.set(format(state.output_power, "05.2f"))
        self._set_output_indicator(state.output_on)
        self.after(REFRESH_MS, self._poll)

    def _on_close(self) -> None:
        try:
            save_settings(
                {
                    "VOLTAGE": self.voltage.value,
                    "VOLTAGE_STEP": float(self.voltage.step_var.get()),
                    "CURRENT": self.current.value,
                    "CURRENT_STEP": float(self.current.step_var.get()),
                }
            )
        except OSError:
            pass
        self.backend.close()
        self.destroy()


def main() -> None:
    port = getattr(config, "PORT", None) or find_port()
    backend = Backend(port)
    backend.start()
    app = App(backend)
    app.mainloop()


if __name__ == "__main__":
    main()
