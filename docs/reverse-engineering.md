# Reverse-engineering notes & methodology

This document records **how** the protocol and device model were recovered, so
the work can be checked and reproduced. It contains only analysis and facts —
no vendor code is reproduced anywhere in this repository.

---

## 1. Inputs

The analysis used two complementary inputs:

* **The vendor host utility** — an Electron application ("MiniPanel") shipped
  as an ASAR archive. This defines the *protocol*: how commands are framed and
  what the host sends.
* **The packaged device UI project** — the `data.json` UI definition and its
  resources. This defines the *device model*: which pages and registers exist
  and what each widget binds to.

| Input | What it provided |
|---|---|
| Electron ASAR (JavaScript) | frame format, command opcodes, register write/read shapes, the brightness byte string, the flash region map, the download protocol |
| Packaged `data.json` + resources | `pageList`, `canvasList`/widget tree, `tagList` (register ids, `valueType`, capacity), `customWidgets`, page count |
| Native binary strings | chip model (`GC9002`), USB identity strings, UI label strings |

### Recorded provenance

When the analysis was performed, the tooling recorded the following immutable
identifiers for the primary artifact (an Electron ASAR, **not** included here):

* SHA-256 of the ASAR: `186ca129ca888b37cc95df996fee64f8c04900ae000e4c98c46e83aa9e6a5c30`
* Tooling operation: a JavaScript/ASAR application analysis pass
* Evidence record id: `ev_e7ce569080063a54bca0bb82b68f5f84017768adfdb451df4b36cf08b1e9275d`
* Parent/complete record id: `ev_7b0d177c25e76f83bd037a7167ed58dc541d3f2a22fe948f2074f5d5472bdca4`

These identify the exact artifact revision that was analysed; a different
vendor build may differ.

---

## 2. Method

1. **Unpack the host utility.** The Electron ASAR was extracted and its
   JavaScript modules read. The relevant modules are the serial port manager,
   the command/packet encoder, and the application logic that drives the
   device.
2. **Extract the framing.** From the command encoder: the `AH`…`MI` framing,
   the control-flag length convention, the CRC behaviour, and the
   `SET_REGISTER` header bytes.
3. **Enumerate commands.** Recovered the opcode enum (handshake, download
   family, reboot, switch-state) and the flash region address map.
4. **Read the device model.** The packaged `data.json` gave the page list and
   the `tagList`, whose `valueType`/`stringNum` fields pin down each register's
   wire type and capacity.
5. **Confirm against hardware.** Every fact marked **[live]** was then verified
   on a physical panel: handshake, reads, writes, page switches, brightness,
   notifications, clock, and a long soak test. See [`testing.md`](testing.md).

---

## 3. How to reproduce

You need your own copy of the vendor package (the ASAR and the packaged UI).
Neither is part of this repository.

1. Extract the Electron ASAR and locate the command encoder and the
   port/message manager. From these, confirm:
   * start flag `41 48`, end flag `4D 49`;
   * request length `= 2 + len(content)`; replies set bit 15;
   * the `SET_REGISTER` header bytes `0x80|(n-1)`, `0xD0`, `0xC0|(n-1)`, `0xE0`;
   * the opcode enum (see [`protocol.md`](protocol.md));
   * the flash region address map (see
     [`hardware-and-flash.md`](hardware-and-flash.md)).
2. Extract the packaged `data.json` from the UI project bundle and confirm the
   `pageList` and `tagList` (register ids, `valueType`, capacity).
3. Compare with the specification in [`protocol.md`](protocol.md) and
   [`registers-and-pages.md`](registers-and-pages.md).

The `.gitignore` lists the conventional local paths for these inputs so they
stay out of version control.

---

## 4. What is *not* covered

* The native ACF compiler was not decompiled; the ACF container is only
  partially characterised (see [`hardware-and-flash.md`](hardware-and-flash.md)).
* The flash-write path (`REQUEST_DOWNLOAD`/`DOWNLOAD_DATA`/`DOWNLOAD_COMPLETE`)
  is documented from the host utility but has not been exercised against
  hardware by this project.
* The stripped native GTK/C++ client binary was not decompiled; the JavaScript
  artifact and the packaged UI were sufficient.

---

## 5. Legal / clean-room position

This project is an independent reimplementation for interoperability. It does
not include the vendor's binaries, resources or source. Protocol and data
structures are functional interface facts. Anyone continuing this work should
keep the same boundary: share original code and original documentation only.
