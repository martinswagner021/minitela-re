# Troubleshooting

## Permission denied opening `/dev/ttyACM0`

The node is `crw-rw---- root uucp` out of the box and the login user is not in
`uucp`. Install the bundled udev rule and replug the device:

```bash
sudo cp 99-minitela.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
ls -l /dev/ttyACM0        # should now show rw for your user
```

## Nothing the tray/web UI does has any effect (brightness, pages, …)

Almost always: **the daemon is not running.** The tray and web UI do *not* own
the serial port — they send every action to the daemon over a UNIX socket. If
the daemon is down, `minitela_client` fails with `FileNotFoundError` on the
socket and all controls silently do nothing (the panel keeps showing its last
frame, so it looks "connected").

The daemon was only ever run by hand in this project, so it dies when
started manually and never survives a logout. Install it as a user service:

```bash
systemctl --user status minitela-daemon.service   # is it active?
systemctl --user enable --now minitela-daemon.service
systemctl --user status minitela-tray.service     # and the tray
systemctl --user enable --now minitela-tray.service
```

Verify the daemon really owns the port and answers:

```bash
ls -l "$XDG_RUNTIME_DIR/minitela.sock"            # should exist
python3 minitela_client.py ping                   # {"ok": true, ...}
```

Brightness is register `7` (`背光` / Backlight, `0..100`); confirm a write is
accepted by reading it back: `python3 minitela_client.py read reg=7`.

## "The port is busy" / CLI does nothing while the daemon runs

Only one process can own the serial port. If the daemon is running, use the
tray, the web UI, or `minitela_client.py` — not the standalone `minitela.py`
CLI (which opens the port directly). Stop the daemon first if you need the
direct CLI:

```bash
systemctl --user stop minitela-daemon.service      # if installed
# or, if started by hand:
ps -eo pid,comm,args | awk '$2=="python3" && /minitela_daemon\.py/ {print $1}'
```

> Do **not** use `pkill -f minitela_daemon` — the pattern can match your own
> shell and kill it.

## The panel "stops working" / reads return garbage

Most likely a **zero-length string write** corrupted the register table. This
happens if any tool writes `""` to a string register. Symptoms: register `2`
reads as a nonsense value, reads stop answering. **The device only recovers
after a reboot** (power-cycle or `REBOOT 0x0070`).

This project never sends empty strings (it sends a space instead) and only
writes changed values. If you have another tool driving the panel, check it.

## The display is unresponsive until I unplug it

* The device **resets when the port is opened**; give it ~1.2 s before the first
  command (the library does this).
* If acknowledgements are never drained, the device's TX buffer fills and it
  hangs. Always read one reply per write.
* After `REBOOT` the node **re-enumerates** (`ttyACM0` → `ttyACM1`); reopen the
  new path.

## The panel ignores everything after a handshake

`HANDSHAKE 0x0080` puts the device into upload/download mode, where
`SET_REGISTER` is ignored until the next reboot. Don't handshake during normal
operation. Reboot to leave the mode.

## Battery percent shows a number but no `%`

The percent is a **string** register (`1082`) rendered verbatim. Send the unit
with the value: `"80%"`, not `"80"`.

## Battery icon missing at high charge

`Battery_Type` (`1150`) has only four textures; values above 3 render nothing.
Clamp to `0..3`.

## WiFi SSID looks cut off on the panel

The widget has a fixed width (~120 px); the full string is stored and returned
by `read_str 1083`. This is cosmetic.

## Tray does not appear

The tray needs a StatusNotifier host (most desktops have one). It prints a
libayatana deprecation warning, which is harmless.

On **Omarchy** (Quickshell), the tray is present but **only pinned items are
shown directly**; other items sit in the tray drawer behind the chevron. Pin
the item so it stays visible:

* Right-click the tray chevron and pin **Minitela**, or
* add `"pinned": ["minitela"]` to the `omarchy.tray` entry in
  `~/.config/omarchy/shell.json` (see the README). It hot-reloads.

Also make sure the tray process is actually running (`python3
minitela_tray.py`, or the `minitela-tray.service` user unit).

## WhatsApp / Whatsie messages are not mirrored

Mirroring relies on desktop notifications. Check, in order:

1. **The source is recognised.** The daemon matches a comma-separated list
   (`--notify-match`, default `whatsapp,whatsie`) against the notification's
   app name, icon and summary. A different client may use another name — set
   `MINITELA_NOTIFY_MATCH` (e.g. `whatsapp,whatsie,signal`) and restart the
   daemon. To mirror *everything*, pass `--notify-match ""`.
2. **Notifications are actually emitted.** Many clients only post for messages
   while the window is in the background. Confirm something arrives with
   `dbus-monitor "interface='org.freedesktop.Notifications'"` while a test
   message is sent.
3. **The daemon sees it.** Run the daemon with `-v`; a matched notification is
   logged as `notification from '<summary>' ('<app>'): '<body>'`.
