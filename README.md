# minitela-re

An independent, open-source **Linux handler** for the *"mini tela"* — the
secondary 240×240 hardware display shipped on notebooks such as the
**Positivo R15m**.

The display is otherwise only driven by a closed-source Windows/Electron
utility. This project is a clean, self-contained Linux implementation: a
protocol library, a background daemon, a system-tray controller and a browser
control center.

* **Display**: 240×240 RGB
* **Controller**: GalaxyCore **GC9002** ("AHMI" platform)
* **Transport**: USB CDC-ACM serial — CherryUSB `sxw-admin CDC_DEMO`
  (`0324:0324`) at `/dev/ttyACM0`, **115200 8N1**
* **Framing**: `AH` (`41 48`) … `MI` (`4D 49`)

> **License:** GPL-3.0-or-later (see [`LICENSE`](LICENSE)).
> **Clean-room:** this repository contains only original code and original
> documentation — no vendor binaries, resources or source. See
> [Provenance](#provenance).

---

## Table of contents

- [Why this exists](#why-this-exists)
- [What was broken](#what-was-broken)
- [Install](#install)
- [Components](#components)
- [Run](#run)
- [Command-line interface](#command-line-interface)
- [Daemon socket API](#daemon-socket-api)
- [Web control center API](#web-control-center-api)
- [Pages & registers](#pages--registers)
- [Autostart (systemd user services)](#autostart-systemd-user-services)
- [Documentation map](#documentation-map)
- [Provenance](#provenance)
- [License](#license)

---

## Why this exists

The panel is a small secondary display on certain laptops. It is driven over a
USB CDC-ACM serial link using a compact binary protocol. The only first-party
controller is a closed-source Windows/Electron utility, so Linux users have no
supported way to use the panel.

This project replaces that utility on Linux. It was written from scratch after
reverse-engineering the shipped artifact; every protocol fact is documented and
reproducible — see [`docs/`](docs/).

## What was broken

The starting point was a third-party Python controller that "did not work
properly". Nine distinct defects were found and fixed; the interesting ones:

1. **Permission** — the display node is `crw-rw---- root uucp` and the login
   user is not in `uucp`, so every open failed with `EACCES`. Fixed with a udev
   rule (`99-minitela.rules`).
2. **Empty string writes (the main culprit)** — the status loop wrote
   `BT_Name = ""` every 5 s. A **zero-length string** write corrupts the
   panel's register table: it stops answering reads and register `2` turns to
   garbage until a reboot. Empty strings are now sent as a space, and only
   *changed* values are written.
3. **Wrong register types** — `Battery_Percent` (`1082`) is a *string*
   register; numeric writes were ignored.
4. **String framing** — the old code sent `0x81 + reg + text`; the device
   requires `0xD0 + reg + uint16 length + text`.
5. **Reply parsing / acks** — replies set the high bit of the control flag
   (length = `controlFlag & 0x7FFF`), and every write is acknowledged. Not
   draining acknowledgements eventually hangs the panel.
6. **Battery icon** — the widget has only four textures (`BAT_0..BAT_3`) but
   0..5 was computed; the icon vanished at ≥80% (a bug in the original too). Now
   clamped to `0..3`.
7. **Battery percent glyph** — the text widget renders the *raw* string, so the
   unit must be sent with the value: `"80%"`, not `"80"`.

Full list and evidence: [`docs/findings.md`](docs/findings.md).

## Install

Grant the logged-in user access to the display with the bundled udev rule:

```bash
sudo cp 99-minitela.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
# replug the display, then verify the node is writable by you:
ls -l /dev/ttyACM0
```

## Components

| File | Role |
|------|------|
| `minitela.py` | Protocol library + standalone CLI (frame builders, device class, host status/clock helpers) |
| `minitela_daemon.py` | Background service: owns the serial port, syncs status + clock, mirrors WhatsApp D-Bus notifications, serves a control socket |
| `minitela_client.py` | Client for the daemon control socket (used by the tray and web UI) |
| `minitela_tray.py` | GTK3 / Ayatana-AppIndicator tray icon + control panel |
| `web_ui.py` | Browser control center (daemon-aware, with a direct fallback) |
| `99-minitela.rules` | udev rule for the display |
| `systemd/` | User units for the daemon and tray |

Only **one** process may own the serial port. The daemon owns it; everything
else talks to the daemon over a UNIX socket.

The daemon mirrors desktop notifications on `org.freedesktop.Notifications`
that match a configurable list of substrings (default `whatsapp,whatsie`, so
both the WhatsApp PWA and the **Whatsie** client are covered). Adjust it with
`--notify-match` or the `MINITELA_NOTIFY_MATCH` environment variable; pass an
empty value to mirror every notification.

## Run

```bash
# Background daemon (status sync + clock + notifications + control socket)
python3 minitela_daemon.py            # -v for debug, --no-notifications to skip D-Bus

# Tray + control panel (talks to the daemon)
python3 minitela_tray.py

# Web control center (http://localhost:8080)
python3 web_ui.py
```

## Command-line interface

The standalone CLI (`minitela.py`) opens the port **directly** and therefore
only works while the daemon is **stopped**. For everyday use prefer the daemon
API below.

```bash
python3 minitela.py --status                 # sync live status, show the status page
python3 minitela.py --sync                   # sync live status only (no page switch)
python3 minitela.py --brightness 90
python3 minitela.py --page 3                 # 1 WhatsApp, 2 Reminder, 3 Status, 4 Weather, 5-7 GIFs
python3 minitela.py --whatsapp "John" "Hello from Minitela!"
python3 minitela.py --gif 1
python3 minitela.py --datetime
python3 minitela.py --read 2                 # read a numeric register
python3 minitela.py --read-str 1082          # read a string register
python3 minitela.py --handshake              # WARNING: switches the device to upload mode
```

## Daemon socket API

The daemon listens on `$XDG_RUNTIME_DIR/minitela.sock` (newline-delimited
JSON). `minitela_client.py` wraps it:

```bash
python3 minitela_client.py ping
python3 minitela_client.py status [show=true]        # show=true also switches to the status page
python3 minitela_client.py set_brightness value=60
python3 minitela_client.py set_page page=3
python3 minitela_client.py gif slot=1
python3 minitela_client.py notify title=Maria message="Oi"
python3 minitela_client.py datetime
python3 minitela_client.py read reg=2
python3 minitela_client.py read_str reg=1082
python3 minitela_client.py pause | resume | quit
```

| Command | Arguments | Effect |
|---|---|---|
| `ping` | — | liveness + last known status |
| `status` | `show=true/false` | refresh status (and optionally show the status page) |
| `set_brightness` | `value=0..100` | backlight |
| `set_page` | `page=1..7` | switch page (1-based) |
| `gif` | `slot=1..3` | show a preloaded GIF slot |
| `notify` | `title`, `message` | WhatsApp-style notification |
| `datetime` | — | push the clock registers |
| `read` / `read_str` | `reg=<id>` | read one register |
| `pause` / `resume` | — | stop/restart the periodic status sync |
| `quit` | — | shut the daemon down |

## Web control center API

`web_ui.py` serves a page plus a tiny JSON API. It uses the daemon when
available and falls back to opening the port itself.

| Endpoint | Query | Effect |
|---|---|---|
| `GET /` | — | the control page |
| `GET /api/status` | — | CPU + battery + registers |
| `GET /api/page` | `page=1..7` | switch page |
| `GET /api/brightness` | `val=0..100` | backlight |
| `GET /api/gif` | `slot=1..3` | show a GIF slot |
| `GET /api/whatsapp` | `sender`, `msg` | notification |

> The server binds all interfaces (`0.0.0.0:8080`) and has **no
> authentication** — use it on trusted networks only.

## Pages & registers

Pages (register `2`, **1-based**):
`1 WhatsApp · 2 Reminder · 3 SystemInfo · 4 Weather · 5 Gif1 · 6 Gif2 · 7 Gif3`.

Key registers: `1150 Battery icon`, `1082 Battery%` (string, e.g. `"80%"`),
`1083 WiFi SSID`, `1085 BT name`, `2006 clock text` (`"DD/MM HH:MM"`),
`2005 WhatsApp badge`, `1140/1141 notification`, `2025/2026 triggers`,
`7 backlight`, `4/5 date/time`.
`1080/1081/1084/1086/1087` do **not** exist in this firmware.

Full map: [`docs/registers-and-pages.md`](docs/registers-and-pages.md).

## Autostart (systemd user services)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/minitela-daemon.service systemd/minitela-tray.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now minitela-daemon.service minitela-tray.service
```

Optionally keep the daemon running across logins:

```bash
loginctl enable-linger "$USER"
```

## Documentation map

| Document | Contents |
|---|---|
| [`docs/protocol.md`](docs/protocol.md) | Byte-level serial protocol specification |
| [`docs/registers-and-pages.md`](docs/registers-and-pages.md) | Full register/tag map and the device page model |
| [`docs/hardware-and-flash.md`](docs/hardware-and-flash.md) | Flash map, `Texture.acf`, the ACF toolchain, custom UI/GIF upload |
| [`docs/reverse-engineering.md`](docs/reverse-engineering.md) | How the analysis was done, with reproducible evidence |
| [`docs/software-architecture.md`](docs/software-architecture.md) | The Linux stack: daemon, client, tray, web, socket design |
| [`docs/findings.md`](docs/findings.md) | Primary reverse-engineering findings and the bug list |
| [`docs/ui_architecture.md`](docs/ui_architecture.md) | The device's on-screen UI architecture |
| [`docs/testing.md`](docs/testing.md) | Live verification and soak-test logs |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common problems and fixes |
| [`docs/roadmap.md`](docs/roadmap.md) | What is not implemented yet |
| [`CHANGELOG.md`](CHANGELOG.md) | Development log |

## Provenance

This repository contains **only original code and original documentation**. No
vendor binaries, resources or source files are redistributed.

The protocol was recovered by analysing the vendor's shipped artifact (an
Electron ASAR) together with the packaged device UI definition. Those files are
**not** part of this repository and are excluded via `.gitignore`; contributors
who hold their own copy of the vendor package can reproduce the analysis with
the steps in [`docs/reverse-engineering.md`](docs/reverse-engineering.md).

## License

**GNU General Public License v3.0 or later** — see [`LICENSE`](LICENSE).
The project is and will remain free software: anyone distributing a modified
version must do so under the same license.
