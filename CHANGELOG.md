# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-04

[1.1.0]: https://github.com/mysiar-org/fnirsi-dps-150-app/releases/tag/1.1.0

### Added

- Input lock button in the GUI. While locked, voltage and current setpoints,
  step controls, typed entries, and the output on/off button are disabled, and
  the backend rejects any change commands. Closing the window unlocks first,
  then turns the output off.
- `Makefile` targets for creating the virtualenv (`venv`), detecting the
  device (`config`), and launching the GUI (`app`).
- `run-dps150.sh` launcher: starts the app with the project virtualenv, changes
  to the project directory, validates the virtualenv, and logs output to
  `${XDG_STATE_HOME:-$HOME/.local/state}/dps150-app.log`.
- `dps150.desktop` entry for launching the application from the Linux desktop
  application menu with the project icon.

### Changed

- README documents serial-port permissions (`dialout`/`tty` groups), the GUI
  lock button, the desktop launcher and its installation, and the new files.

## [1.0.0] - 2026-10-15

[1.0.0]: https://github.com/mysiar-org/fnirsi-dps-150-app/releases/tag/1.0.0

### Added

- Async serial driver for the FNIRSI DPS-150 (`dps150.py`), including the
  connection handshake, full state snapshots, telemetry, setpoint/output
  control, protections, saved groups, metering, device information, and the
  `on_state` callback.
- Tkinter control panel (`app.py`) with live voltage/current/power readouts,
  selectable step sizes, `+`/`-` adjustments, typed setpoint entry, output
  on/off control, and status information (mode, input voltage, temperature,
  uptime).
- Remembered voltage/current setpoints and step sizes, restored from
  `config.py` on startup and saved on exit.
- Command-line tools: `set_volts.py` and `set_amps.py` for setpoints, plus
  `set_on.py` and `set_off.py` for output control.
- Device scanner (`scan4device.py`) with a stable `/dev/ttyDSP-150` udev
  symlink workflow.
- Hardware tests for dumping the full device state and sweeping output
  voltage.
