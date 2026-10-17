# Minitela reverse-engineering findings

> The paths named below (the Electron ASAR, the packaged UI) are **inputs the
> analyst supplies locally** — they are not part of this repository. See
> [`reverse-engineering.md`](reverse-engineering.md) for how to reproduce the
> analysis and the clean-room position.

All protocol facts below were recovered from the shipped artifact, not guessed.
Primary source:

- Artifact: `extracted/app.asar` (Electron "MiniPanel" 0.1.6)
- SHA-256: `186ca129ca888b37cc95df996fee64f8c04900ae000e4c98c46e83aa9e6a5c30`
- REA operation: `analyze_javascript_application` (format `asar`)
- Evidence: summary view `ev_e7ce569080063a54bca0bb82b68f5f84017768adfdb451df4b36cf08b1e9275d`
  (parent/complete record `ev_7b0d177c25e76f83bd037a7167ed58dc541d3f2a22fe948f2074f5d5472bdca4`)
- Corroborating package data: `minitela-backup/minitela/resources/ACF/file.zip` → `data.json`
  (`GC9002`, project "Minitela1.0", 240x240) and the native binary strings.

Everything below marked **[live]** was confirmed against the real panel
(`/dev/ttyACM0`, `0324:0324`) after installing the udev rule.

## 1. Serial transport

- USB CDC ACM: **CherryUSB `sxw-admin CDC_DEMO`** (`idVendor:idProduct = 0324:0324`),
  appears as `/dev/ttyACM0`, 115200 8N1, raw (no flow control).
- **[live] The device restarts when the host opens the port** (DTR toggle): for
  roughly a second afterwards it ignores commands. Open with a ~1.2 s settle, or
  keep the port open in a long-lived process (the daemon).
- **[live] The device also re-enumerates** (`ttyACM0` → `ttyACM1`) after the
  `REBOOT` command, so the port path is not stable across resets.
- Only the locally logged-in user should own it. The original package ships **no**
  udev rule, so out of the box the node is `crw-rw---- root uucp` and unprivileged
  access fails with `EACCES`.

## 2. Frame format

```
41 48 | controlFlag(2 BE) | commandType(2 BE) | content | crc(2) | 4D 49
```

- Requests: `controlFlag = 2 (commandType) + len(content)`.
- **[live] Responses set bit 15 of `controlFlag`** (`80 08`, `80 09`, ...). The
  length must be read as `controlFlag & 0x7FFF`, otherwise a reply looks like a
  32 KB frame and the read times out.
- CRC is **not verified by the device**. The shipped general path disables it
  (`crc = 00 00`); the hardcoded brightness command sends the placeholder `E2 CB`.
  Confirmed against the `crc` npm library: `E2CB` is *not* crc16/ccitt/modbus/kermit/xmodem.
  **[live]** requests with `00 00`, `E2 CB`, or an arbitrary pair are all accepted.
- **[live] The device sends exactly one response per write** (see function codes
  below). If the host never reads them, its TX buffer overflows and the panel
  hangs. Drain each acknowledgement.

### `SET_REGISTER` `0x0090`
```
numeric write : (0x80 | (n-1))  n=1..16 ; per pair reg(2 BE) + value(4 BE)
string  write :  0xD0 + reg(2 BE) + byteLen(2 BE) + utf-8 bytes
numeric read  : (0xC0 | (n-1)) + reg(2 BE) each
string  read  :  0xE0 + reg(2 BE) + capacity(2 BE)
```
Example reg `2` ← `2`:
`41 48 00 09 00 90 80 00 02 00 00 00 02 00 00 4D 49`
Example reg `1083` ← `"Casa"`:
`41 48 00 0B 00 90 D0 04 3B 00 04 43 61 73 61 00 00 4D 49`

### Replying frames (`0x00D0`)
The first content byte encodes the reply class in bits 7..4:

| code | meaning            | payload after the class byte |
|-----:|--------------------|------------------------------|
| 0    | numeric read reply | `reg(2 BE) + value(4 BE)`    |
| 1    | string read reply  | `reg(2 BE) + len(2 BE) + bytes` |
| 2    | write acknowledgement | `reg(2 BE) + value(4 BE)` |

`[live]` examples:
- handshake `41 48 00 02 00 80 00 00 4D 49` → `41 48 00 06 00 C0 00 00 04 00 00 00 4D 49`
  (max packet length `0x400` = 1024).
- write ack → `41 48 80 08 00 D0 20 00 00 00 02 00 00 00 4D 49`
  (class 2, reg 2, value 2).
- numeric read reply → `41 48 80 09 00 D0 00 00 02 00 00 00 02 00 00 4D 49`.
- string read reply → `41 48 80 0F 00 D0 10 00 02 00 08 <8 bytes> 00 00 4D 49`.

### Brightness (hardcoded raw command, register 7)
`41 48 80 09 00 90 80 00 07 00 00 00 <value> E2 CB 4D 49`

### HANDSHAKE is a mode switch
**[live] Sending `HANDSHAKE 0x0080` puts the device into upload/download mode.**
In that mode `SET_REGISTER` (read and write) is silently ignored — only
`HANDSHAKE`/`GET_DOWNLOAD_STATUS` answer — until the next reboot. The controller
therefore never handshakes spontaneously; the CLI exposes it only as an explicit
diagnostic.

## 3. Register map (verified against `data.json` tagList)

Only the registers defined in the packaged `tagList` exist. The `valueType`
field (0 = number, 1 = string) is authoritative for the wire type.

| Reg | Name | Wire type |
|----:|------|-----------|
| 2 | Current page | number |
| 4 | Clock date (BCD-ish hex) | number |
| 5 | Clock time (BCD-ish hex) | number |
| 7 | Backlight | number |
| 1082 | Battery_Percent | **string** |
| 1083 | Wifi_SSID | **string** (cap 32) |
| 1085 | BT_Name | **string** (cap 32) |
| 1090 | Reminder1 | string (cap 100) |
| 1110/1115/1120 | Weather_1/2/3 type | number |
| 1119/1124 | Weather temp description | string |
| 1140 | Notification sender | string (cap 36) |
| 1141 | Notification content | string (cap 96) |
| 1150 | Battery_Type | number 0..5 |
| 2005 | whatsapp_logo | number 0/1 |
| 2006 | dateHour | **string**, `"DD/MM HH:MM"` |
| 2025/2026 | MessageBackground1/2 trigger | number |
| 2027/2030/2031/2032 | Weather city/temps | string |

Not present in this build (writing them is harmless but has no effect):
**1080 CPU, 1081 GPU, 1084 Wifi_Quality, 1086 BT_Status, 1087 Wifi_Status.**

`Battery_Type`: `<25→0, <50→1, <75→2, else 3`. The `BatteryStatus` widget is a
slide with only four textures (`BAT_0`..`BAT_3`); values above 3 render no icon.
(The shipped app computes 0..5, so the icon is blank at >=80% — a real bug in
the original.)

### CRITICAL: never write a zero-length string
**[live] A string write with `byteLen = 0` corrupts the device's register
table**: it stops answering reads and register 2 becomes garbage (observed
values `0x3830D004`, `0xE0000000`, with fragments of subsequent strings like
`"7/1"`). The panel only recovers after a reboot. Writing a single space (`" "`)
instead is safe and renders blank.

This was the original "not working properly" bug: the status loop wrote the
Bluetooth name as an empty string every 5 s (no Bluetooth device connected) and
bricked the link until the panel was power-cycled.

## 4. Pages (from `data.json` pageList)

The `pageList` index is 0-based (`0 WhatsApp … 6 Gif3`), but the "current page"
**register is 1-based**: the shipped app's `showPage(pageId)` sends `pageId` and
stores `pageId - 1` (see `extracted/electron.js`). So write:

`1 WhatsApp, 2 Reminder, 3 SystemInfo, 4 Weather, 5 Gif1, 6 Gif2, 7 Gif3`.

The SystemInfo page binds only to: `1150` (Battery_Type), `1082`
(Battery_Percent), `1083` (Wifi_SSID), `1085` (BT_Name), `2005`
(whatsapp_logo) and `2006` (dateHour).

## 5. What was broken in the previous Python controller

1. **Device permission** — `/dev/ttyACM0` unreadable by the user (`EACCES`).
   Fixed by `99-minitela.rules`.
2. **Empty string writes** — the status updater wrote `BT_Name = ""` every cycle,
   which corrupts the firmware (see §3). Fixed by substituting a space and by
   only writing changed values.
3. **String framing** — old code used `0x81 + reg + text` with no length field and
   a 32-byte cut. The device expects `0xD0 + reg + uint16 length + text`.
4. **Wrong register types** — `Battery_Percent` (1082) is a *string*; numeric
   writes to it are ignored. `dateHour` is register `2006`, not 4/5.
5. **No raw TTY setup** — `os.open` left the port in canonical mode at the default
   speed. Now set to raw 115200 (termios) before use.
6. **Reply parsing** — length was not masked with `0x7FFF`, so every framed reply
   was mis-sized; acknowledgements were never drained, eventually hanging the panel.
7. **Page numbering** — register `2` is 1-based; the old controller sent the
   0-based pageList index, so requests landed one page short.
8. **Battery icon** — the widget has four textures (`BAT_0..BAT_3`) but the
   original maps battery to `0..5`; the icon is blank at ≥80%. Clamped to `0..3`.
9. **Battery percent glyph** — the SystemInfo text widget (`2.1.0.1`, name
   `batteryPercente`, subType `MyTextInput`) renders the *raw* string written to
   `1082`; its shipped default text is `"100%"`. Writing bare `"80"` shows no
   percent sign. Send the unit with the value: `f"{pct}%"` (`"80%"`).

## 6. Runtime behaviour observed in the shipped app

- Status tag loop every 5 s (`sendTagDataTask`).
- Status sources: `/sys/class/power_supply/BAT0/capacity`, `/proc/stat`,
  `iwgetid -r`, battery/BT from the platform.
- Notifications via `dbus-monitor "interface='org.freedesktop.Notifications'"`,
  filtered for WhatsApp, mapped to regs 1140/1141 + triggers 2025/2026 + page 0.
- Screen lock/suspend blanks the panel (`brightness 0`) and restores on resume.
- GIF/image upload protocol: `REQUEST_DOWNLOAD 0x0081`, `DOWNLOAD_DATA 0x0082`,
  `DOWNLOAD_COMPLETE 0x008F`, plus `HANDSHAKE 0x0080`, `GET_DOWNLOAD_STATUS 0x0085`,
  `SWITCH_STATE 0x0071`, `REBOOT 0x0070`.

## Live verification performed

After the udev rule was installed, on `/dev/ttyACM0`:

- handshake, numeric read (`reg 2`), string read (`1082`, `1083`, `2006`),
  write ack, page switch, brightness, notification (write + read-back), GIF page,
  date/time — all exercised through both the library/CLI and the daemon socket.
- A 20-cycle forced status+datetime soak kept `reg 2 = 1` and read
  `battery = "80%"`, `dateHour = "17/10 01:34"` throughout (no corruption).

## Unknowns / not yet verified

- GIF/image upload over `0x0081/0x0082/0x008F` and on-device texture generation
  (`AHMISimGenDemo`) were not implemented or exercised.
- The native GTK/C++ `minitela` binary is stripped and no native engine
  (Ghidra/Hopper) is installed, so it was not decompiled; JS + packaged data +
  strings were sufficient.
