# Changelog

## [Unreleased]

### Added
* Linux handler for the 240×240 "mini tela" secondary display (GalaxyCore
  GC9002 over USB CDC-ACM).
* `minitela.py`: protocol library and standalone CLI (frame builders, device
  class, host status/clock helpers).
* `minitela_daemon.py`: background daemon that owns the serial port, syncs
  status and clock, mirrors WhatsApp D-Bus notifications, and serves a control
  socket.
* `minitela_client.py`: client for the daemon control socket.
* `minitela_tray.py`: GTK3 / Ayatana-AppIndicator tray and control panel.
* `web_ui.py`: browser control center with a direct fallback.
* `99-minitela.rules`: udev rule granting the logged-in user access.
* `systemd/`: user units for the daemon and tray.
* Documentation set under `docs/`.

### Fixed
* Device access denied (`EACCES`) — covered by the udev rule.
* **Zero-length string writes** corrupt the device register table; empty strings
  are now sent as a space and only changed values are written.
* Correct string framing (`0xD0 + reg + uint16 len + utf-8`).
* Correct register types (`Battery_Percent` is a string; the clock text is
  register `2006`).
* Raw TTY setup at 115200.
* Reply parsing masks the control flag with `0x7FFF` and drains one
  acknowledgement per write.
* Page numbering is 1-based.
* Battery icon bucket clamped to the four available textures (`0..3`).
* Battery percent text now includes the unit glyph (`"80%"`).

### Known limitations
* Flash write (`REQUEST_DOWNLOAD`/`DOWNLOAD_DATA`/`DOWNLOAD_COMPLETE`) and ACF
  generation are documented but not implemented. Custom GIFs and custom UI
  layouts are therefore not yet possible.

---

Initial public release prepared under the GPL-3.0-or-later.
