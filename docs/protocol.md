# Minitela / GC9002 hardware protocol specification

This is the byte-level specification of the serial protocol used by the
240×240 "mini tela" display. It was recovered by reverse-engineering (see
[`reverse-engineering.md`](reverse-engineering.md)) and confirmed against real
hardware; items marked **[live]** were observed on a physical panel.

Everything here is documented as an interface. No vendor code is reproduced.

---

## 1. Physical & transport layer

| Property | Value |
|---|---|
| Display | 240×240 RGB |
| Display controller | GalaxyCore **GC9002** ("AHMI" platform) |
| USB device | CherryUSB `sxw-admin CDC_DEMO` (`idVendor:idProduct = 0324:0324`) |
| OS node | `/dev/ttyACM0` (re-enumerates to `ttyACM1` after a reboot) |
| Line settings | **115200 8N1**, raw, no flow control |
| Permissions | ships with **no** udev rule → node is `crw-rw---- root uucp` |

**[live] The device restarts when the host opens the port** (DTR toggle). For
about a second afterwards it ignores commands, so open with a ~1.2 s settle or
keep the port open in a long-lived process (the daemon does this).

**[live] The device re-enumerates** (`ttyACM0` → `ttyACM1`) after the `REBOOT`
command, so the node path is not stable across resets.

---

## 2. Frame format

Every command and reply is one frame:

```text
41 48 | controlFlag(2 BE) | commandType(2 BE) | content | crc(2) | 4D 49
  AH                                                                 MI
```

| Offset | Field | Notes |
|---|---|---|
| 0..1 | Start flag | constant `41 48` (`"AH"`) |
| 2..3 | Control flag | requests: `len(content) + 2`; replies set bit 15 |
| 4..5 | Command type | big-endian opcode |
| 6..N | Content | variable |
| N+1..N+2 | CRC | **not verified by the device** |
| N+3..N+4 | End flag | constant `4D 49` (`"MI"`) |

* **Length.** For a request, `controlFlag = 2 + len(content)` (the `+2` covers
  the 2-byte command type). For a **reply the device sets bit 15**, so the
  length must be read as `controlFlag & 0x7FFF`. Treating it as a raw
  `uint16` makes every reply look like a ~32 KB frame and the read times out.
* **CRC is ignored.** The general path sends `00 00`; the hardcoded brightness
  command sends the placeholder `E2 CB`, which is *not* any standard CRC-16
  (ccitt / modbus / kermit / xmodem). **[live]** `00 00`, `E2 CB` and arbitrary
  pairs are all accepted.
* **Acknowledge every write.** The device sends exactly one response per write
  and has a small TX buffer. If the host never drains them, the panel
  eventually hangs. Read one ack after each write.

---

## 3. Command types

| Opcode | Reply | Name | Purpose |
|---|---|---|---|
| `0x0080` | `0x00C0` | `HANDSHAKE` | enter upload/download mode (see §6) |
| `0x0085` | `0x00C5` | `GET_DOWNLOAD_STATUS` | download state; answers in both modes |
| `0x0086` | `0x00C6` | `GET_OFFSET` | current flash write offset |
| `0x0081` | `0x00C1` | `REQUEST_DOWNLOAD` | begin a flash write (address + length + id) |
| `0x0082` | `0x00C2` | `DOWNLOAD_DATA` | one chunk of flash data |
| `0x008F` | `0x00CF` | `DOWNLOAD_COMPLETE` | finish a flash write |
| `0x0083` | `0x00C3` | `UPLOAD_DATA` | read data back from the device |
| `0x0071` | `0x00B1` | `SWITCH_STATE` | change device state |
| `0x0070` | `0x00B0` | `REBOOT` | reboot the panel |
| `0x0090` | `0x00D0` | `SET_REGISTER` | read/write registers (the normal path) |

Only `SET_REGISTER` is used in normal operation.

---

## 4. `SET_REGISTER` (`0x0090`)

The content starts with a **header byte** that selects the operation, then the
operands.

| Header | Operation | Content layout |
|---|---|---|
| `0x80 \| (n-1)` | write n numeric registers | `hdr + [reg(2 BE) + value(4 BE)] × n` |
| `0xD0` | write one string register | `hdr + reg(2 BE) + byteLen(2 BE) + utf-8` |
| `0xC0 \| (n-1)` | read n numeric registers | `hdr + reg(2 BE) × n` |
| `0xE0` | read one string register | `hdr + reg(2 BE) + capacity(2 BE)` |

### Numeric write (page register `2` ← `2`)

```text
41 48 00 09 00 90 80 00 02 00 00 00 02 00 00 4D 49
│   │  │  │  │  │  │  │  └──┬──┘ └────┬────┘ │  └── MI
│   │  │  │  │  │  │  │     │         │      └ CRC (00 00)
│   │  │  │  │  │  │  │     │         └ value = 2 (4 BE)
│   │  │  │  │  │  │  │     └ register = 2 (2 BE)
│   │  │  │  │  │  │  └ header 0x80 = write, n=1
│   │  │  │  │  │  └ SET_REGISTER
│   │  │  │  │  └ cmd type
│   │  │  │  └ control flag = 9
│   │  └ start AH
```

### String write (Wifi_SSID `1083` ← `"Casa"`)

```text
41 48 00 0B 00 90 D0 04 3B 00 04 43 61 73 61 00 00 4D 49
                     │  │  └──┬──┘ └────┬────┘
                     │  │     │         └ "Casa"
                     │  │     └ byteLen = 4
                     │  └ reg 1083 (0x043B)
                     └ header 0xD0 = write string
```

The string is capped at the register's capacity (most are 32 bytes; the
notification sender is 36 and the notification body is 96).

> **CRITICAL — never send a zero-length string.** A string write with
> `byteLen = 0` corrupts the device's register table: it stops answering reads
> and register `2` becomes garbage until a reboot. To clear a field, send a
> single space (`" "`) instead. This is enforced in `minitela.py`.

### Numeric read

```text
41 48 00 08 00 90 C0 00 02 00 00 4D 49          # read register 2
```

### String read

```text
41 48 00 09 00 90 E0 04 3B 00 20 00 00 4D 49     # read register 1083, capacity 32
```

### Brightness (hardcoded raw command, register `7`)

The original utility sends brightness as a fixed byte string (it is the only
command that ships a non-zero placeholder CRC):

```text
41 48 80 09 00 90 80 00 07 00 00 00 <VALUE> E2 CB 4D 49
                                          └ 0..100
```

---

## 5. Reply frames (`0x00D0`)

A reply's command type is `0x00D0`. Its first content byte encodes the reply
class in bits 7..4:

| Class | Meaning | Payload after the class byte |
|---|---|---|
| 0 | numeric read reply | `reg(2 BE) + value(4 BE)` |
| 1 | string read reply | `reg(2 BE) + len(2 BE) + bytes` |
| 2 | write acknowledgement | `reg(2 BE) + value(4 BE)` |

Worked examples:

```text
handshake  -> 41 48 00 06 00 C0 00 00 04 00 00 00 4D 49   # max packet length 0x400
write ack  -> 41 48 80 08 00 D0 20 00 00 00 02 00 00 00 4D 49   # class 2, reg 2
num read   -> 41 48 80 09 00 D0 00 00 02 00 00 00 02 00 00 4D 49
str read   -> 41 48 80 0F 00 D0 10 00 02 00 08 <8 bytes> 00 00 4D 49
```

`minitela.py` validates the reply function code (`0xD0`) and drains exactly one
acknowledgement per write.

---

## 6. `HANDSHAKE` is a mode switch

**[live]** Sending `HANDSHAKE 0x0080` puts the device into **upload/download
mode**. In that mode `SET_REGISTER` (reads *and* writes) is silently ignored —
only `HANDSHAKE` and `GET_DOWNLOAD_STATUS` answer — until the next reboot.

The controller therefore **never handshakes spontaneously**. The CLI exposes it
only as an explicit diagnostic (`--handshake`).

---

## 7. Download / upload (flashing) protocol

This sequence is used to write flash regions (see
[`hardware-and-flash.md`](hardware-and-flash.md) for the region map). It is
**documented but not implemented** in this project yet.

1. `HANDSHAKE 0x0080` → device enters download mode.
2. `REQUEST_DOWNLOAD 0x0081` with `(targetAddress, totalLength, fileId)` where
   `fileId` is the MD5 of the payload.
3. `DOWNLOAD_DATA 0x0082` repeatedly, each carrying a chunk at the running
   offset (query `GET_OFFSET 0x0086` if needed).
4. `DOWNLOAD_COMPLETE 0x008F` to finalise.
5. `SWITCH_STATE 0x0071` / `REBOOT 0x0070` to leave download mode / restart.

The device reports progress and state through `GET_DOWNLOAD_STATUS 0x0085`.

> Writing flash can render the panel unbootable. Always back up the regions
> first. See `docs/roadmap.md`.

---

## 8. Register addressing

Register IDs are 16-bit. The set of valid registers is fixed by the device's UI
definition; the *wire type* (numeric vs string) is likewise fixed per register.
Writing an undefined register is harmless but has no effect. See
[`registers-and-pages.md`](registers-and-pages.md).
