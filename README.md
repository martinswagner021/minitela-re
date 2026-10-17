# minitela-re

An independent, open-source **Linux handler** for the *"mini tela"* — the
secondary 240×240 hardware display shipped on notebooks such as the
**Positivo R15m**.

The display is otherwise only driven by a closed-source Windows/Electron
utility. This project provides a clean, self-contained Linux implementation:
a protocol library, a background daemon, a system-tray controller and a
browser control center.

* **Display**: 240×240 RGB, GalaxyCore **GC9002** ("AHMI" platform)
* **Transport**: USB CDC-ACM serial (`/dev/ttyACM0`), 115200 8N1
* **Framing**: `AH` (`41 48`) … `MI` (`4D 49`)

## Status

The implementation is proposed in the **initial pull request**. Once merged,
this README is expanded into the full project documentation under
[`docs/`](docs/).

## License

**GNU General Public License v3.0 or later** (`GPL-3.0-or-later`) — see
[`LICENSE`](LICENSE). The project is and will remain free software: anyone
who distributes a modified version must do so under the same license.

## Provenance & clean-room note

This repository contains **only original code and original documentation**.
No vendor binaries, resources or source files are redistributed. The
closed-source artifacts were used solely as analysis input; see the
documentation for how to reproduce the findings from your own copy.
