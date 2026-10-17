# Testing & live verification

Verification was done on a real panel (`/dev/ttyACM0`, USB `0324:0324`) after
installing the udev rule. Facts confirmed on hardware are marked **[live]**.

---

## 1. Transport & handshake

* Port opens raw at 115200 8N1; the device resets on open and ignores commands
  for ~1 s — confirmed by adding a settle delay. **[live]**
* `HANDSHAKE 0x0080` returns the max packet length (`0x400`). **[live]**
* `REBOOT 0x0070` re-enumerates the node (`ttyACM0` → `ttyACM1`). **[live]**

## 2. Registers

* Numeric read of register `2` returns the current page. **[live]**
* String reads (`1082`, `1083`, `2006`) return length-prefixed payloads padded
  to the requested capacity. **[live]**
* Writing an undefined register is accepted but has no effect. **[live]**
* **Zero-length string write corrupts the register table** (register `2`
  becomes garbage such as `0x3830D004` / `0xE0000000`; reads stop) until a
  reboot. Reproduced and then avoided by coercing empty strings to a space.
  **[live]**

## 3. Functional checks

Exercised through both the library/CLI and the daemon socket:

| Feature | Result |
|---|---|
| handshake | ok |
| page switch (WhatsApp/Reminder/SystemInfo/Weather/GIFs) | ok |
| backlight brightness | ok |
| numeric read (`reg 2`) | ok |
| string read (`1082`, `1083`, `2006`) | ok |
| write acknowledgement drained | ok |
| notification (write + read-back) | ok |
| GIF page (slots 1–3) | ok |
| date/time (regs `4`,`5`,`2006`) | ok |

## 4. Soak test

A 20-cycle forced status + datetime loop kept the link healthy:

* `reg 2` stayed `1` throughout;
* `1082` read back as the battery text (now `"80%"`);
* `2006` read back as `"DD/MM HH:MM"`;
* no register-table corruption.

## 5. Visual confirmation

On the panel itself:

* SystemInfo page shows **battery 80% with the correct icon bucket**;
* WiFi SSID displayed;
* Bluetooth field blank (no device connected);
* clock correct.

Earlier, the battery **icon** appeared only after the `Battery_Type` bucket was
clamped to `0..3`, and the **percent sign** appeared only after the unit glyph
was included in the `1082` string.

## 6. Software checks

All Python modules compile clean (`python3 -m py_compile`). The tray runs
(a single libayatana deprecation warning) and the daemon runs without errors.

## 7. Not yet verified on hardware

* The flash download/upload path (`REQUEST_DOWNLOAD`/`DOWNLOAD_DATA`/
  `DOWNLOAD_COMPLETE`) — documented, not exercised.
* ACF/GIF generation and upload.
