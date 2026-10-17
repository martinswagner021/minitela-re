# Software architecture (the Linux stack)

This document describes the Python stack that drives the display on Linux.

---

## 1. Process model

The serial port is a **single-owner resource**: only one process may hold it
open. The design therefore centralises ownership in one **daemon**, and every
other component talks to the daemon over a local **UNIX socket**:

```text
                    +------------------+
   tray (GTK)  ---->|                  |
   web UI     ----> |  minitela_daemon |  <---- owns ----> /dev/ttyACM0
   CLI client ----> |  (UNIX socket)   |
                    +------------------+
                              |
                     status sync loop  +  D-Bus notification monitor
```

Components and responsibilities:

| Component | Responsibility |
|---|---|
| `minitela.py` | protocol library (frame builders, `MinitelaDevice`, host helpers) |
| `minitela_daemon.py` | owns the port; periodic status/clock sync; WhatsApp D-Bus mirroring; control socket |
| `minitela_client.py` | thin client for the control socket |
| `minitela_tray.py` | tray icon + control panel |
| `web_ui.py` | browser control center (daemon-aware, direct fallback) |

The udev rule (`99-minitela.rules`) grants the logged-in user access to the
device node so the daemon can open it without root.

---

## 2. Protocol library (`minitela.py`)

* **Frame builders**: numeric write/read, string write/read, brightness.
* **`MinitelaDevice`**: context manager that opens the port raw at 115200,
  waits for the device's reset-on-open settle, performs reads/writes with
  acknowledgement draining, validates reply function codes, and retries.
* **Host helpers**: battery percent (`/sys/class/power_supply`), CPU percent
  (`/proc/stat`), WiFi SSID (`nmcli`), Bluetooth name, and the clock.
* **High-level operations**: `update_system_status` (change-detected,
  type-correct writes), `set_datetime`, `send_whatsapp_notification`,
  `set_page`, `show_gif`, `set_brightness`.
* **Safety**: empty strings are coerced to a single space; only defined
  registers are written.

A minimum gap is kept between `SET_REGISTER` frames so the device's small TX
buffer is not overrun.

---

## 3. Daemon (`minitela_daemon.py`)

Threads:

| Thread | Job |
|---|---|
| status sync loop | every `--interval` (default 5 s) reads host state and writes only **changed** registers; also pushes the clock |
| notification loop | runs `dbus-monitor` for `org.freedesktop.Notifications` and mirrors matching notifications |
| socket server | accepts newline-delimited JSON requests, one thread per connection |

Key options:

| Option | Default | Meaning |
|---|---|---|
| `--port` | first `/dev/ttyACM*` | serial port |
| `--interval` | `5.0` | status sync period (seconds) |
| `--socket` | `$XDG_RUNTIME_DIR/minitela.sock` | control socket path |
| `--notify-match` | env `MINITELA_NOTIFY_MATCH` or `whatsapp` | substring filter for mirrored notifications |
| `--no-notifications` | off | disable D-Bus mirroring |
| `-v` / `--verbose` | off | debug logging |

`pause`/`resume` stop and restart the periodic sync without releasing the port
(useful when another tool needs a quiet link, or to freeze the display).

### Control socket protocol

`$XDG_RUNTIME_DIR/minitela.sock`, newline-delimited JSON.

Request: `{"cmd": "<name>", ...kwargs}`. Response: `{"ok": true, ...}` or
`{"ok": false, "error": "..."}`.

| `cmd` | kwargs | Effect |
|---|---|---|
| `ping` | — | liveness, paused flag, last status |
| `status` | `show` (bool) | refresh status; `show` also switches to the status page |
| `set_brightness` | `value` (0..100) | backlight |
| `set_page` | `page` (1..7) | switch page |
| `gif` | `slot` (1..3) | show a preloaded GIF slot |
| `notify` | `title`, `message` | WhatsApp-style notification |
| `datetime` | — | push clock registers |
| `read` / `read_str` | `reg` | read a numeric / string register |
| `pause` / `resume` | — | control the sync loop |
| `quit` | — | shut the daemon down |

---

## 4. Client (`minitela_client.py`)

`MinitelaClient` opens the socket, sends one JSON request, reads one JSON
response. Convenience methods exist for every command. Run as a script:
`python3 minitela_client.py <cmd> [key=value ...]`.

---

## 5. Tray (`minitela_tray.py`)

GTK3 + Ayatana-AppIndicator. Menu: control panel, sync status, screen page,
GIF animation, brightness, send notification, open web control, quit. The
indicator label shows the live battery percentage.

---

## 6. Web control center (`web_ui.py`)

A small `http.server` on port 8080 serving an HTML control page and a JSON API.
On each request it pings the daemon; if the daemon is up it proxies through it,
otherwise it opens the device directly (`_direct` fallback). See the README for
the endpoint list.

> No authentication; binds all interfaces. Trusted networks only.

---

## 7. udev rule

`99-minitela.rules` matches the device's USB IDs and sets `MODE="0666"` plus
`TAG+="uaccess"`, so the active user can open the node without root and without
adding the user to a group.

---

## 8. systemd user services

`systemd/minitela-daemon.service` and `systemd/minitela-tray.service` run the
daemon and the tray in the user session. The tray unit is ordered after the
daemon and tied to `graphical-session.target`. Enable with `systemctl --user`.
