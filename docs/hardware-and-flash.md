# Hardware, flash layout and the ACF UI format

This document covers what is stored **on the device**, how the UI is packaged,
and what it would take to deliver custom interfaces or GIFs. It is background
for the flash-write work tracked in [`roadmap.md`](roadmap.md).

---

## 1. What the device stores

The panel is not a dumb framebuffer: it runs its own firmware and renders a
**pre-compiled UI** that lives in its flash. At runtime the Linux handler only
*writes register values into that preloaded UI*; it does not paint pixels.

The flash is divided into regions (recovered from the vendor utility's file
map):

| Address | Size | Region | Contents |
|---|---|---|---|
| `0x08000000` | | `bootloader` | boot loader |
| `0x08040000` | ~600 K | `cpu1` | main firmware (`cpu1.bin`) |
| `0x080F7000` | | `upg_cfg` | update configuration |
| `0x080F8000` | 4 K | `cpu0_config` | config |
| `0x080FB000` | 4 K | `calibration` | calibration data |
| `0x080FC000` | 4 K | `eraseStoreSpace` | store space (erase) |
| `0x080FE000` | 4 K | `hwconfig` | hardware config (`hwconfig.bin`) |
| `0x080FF000` | 4 K | `product` | product info (`product.bin`) |
| `0x08100000` | 3 M / 7 M / 15 M | `texture` | **`Texture.acf` — the entire UI** |
| `0x08500000` | | `texture_gif` | GIF texture region |

The UI asset `Texture.acf` is the thing to replace to change the interface.

---

## 2. The UI project format

The vendor utility compiles a **project bundle** into `Texture.acf`. The bundle
is a ZIP whose main member is a JSON UI definition plus the referenced
resources (PNGs, fonts, GIFs).

Observed project shape (from a packaged project, `GC9002`, 240×240):

| Member | Meaning |
|---|---|
| `data.json` | the whole UI definition (see below) |
| `r-<page>-<...>.png` | per-widget/canvas rendered assets |
| `Inconsolata-*.png` | font atlases |
| `*.gif` | animated GIF assets |

`data.json` top-level fields of interest:

| Field | Meaning |
|---|---|
| `pageList` | array of pages; each has `id`, `type`, `name`, `canvasList` |
| `canvasList` / `subCanvasList` | the layer tree → `widgetList` of leaf widgets |
| `tagList` | the register table: `name`, `indexOfRegister`, `valueType` (0 num / 1 string), `stringNum` (capacity), `arrayNum` |
| `resourceList` | referenced asset files |
| `customWidgets` | widget types used (e.g. pie chart, GIF, video player, list) |
| `size` | canvas size (240×240) |
| `chipMode` | `GC9002` |

Each leaf widget carries its geometry, its bound `tag` (register name), and a
default `text`. Example: the battery percent widget binds `tag:
"Battery_Percent"` with default `text: "100%"` — which is why the unit must be
included when driving register `1082` (see
[`registers-and-pages.md`](registers-and-pages.md)).

The **`tagList` is the authoritative register map**: only names that appear
there exist, and each tag's `valueType` fixes the wire type.

---

## 3. The ACF compiler

`Texture.acf` is produced by a **vendor native tool** (a Windows executable),
invoked roughly as:

```text
AHMISimGenDemo -f <project.zip> -m 2 -c 0 -e <platformCode> -d <dither> -o <outDir>
```

with a GIF-only variant:

```text
AHMISimGenDemo_gif -f <project_gif.zip> -m 2 -c 0 -e -g 1 <platformCode> -d <dither> -o <outDir>
```

`platformCode` maps a chip name to an integer (`GC9002` → 0, `GC9003` → 1,
`GC9005` → 2). The tool writes `Texture.acf` (or `GIF_0.acf`) into the output
directory.

Observed `Texture.acf` files begin with a small header:

```text
00 80 <len:2> <hash:4> a0 00 06 00 <24-byte project id string> ...
```

The 24-character project id is embedded near the start. The exact container
layout beyond this has **not** been fully reverse-engineered.

> The compiler executable is **not** shipped in the Linux package and is not
> redistributed by this project. Reproducing `Texture.acf` generation would
> require either obtaining the vendor tool (running it under Wine) or a
> clean-room reimplementation of the ACF container from input/output examples.

---

## 4. Flashing a region

Regions are written over the same serial link using the download protocol
(see [`protocol.md`](protocol.md) §7):

```
HANDSHAKE → REQUEST_DOWNLOAD(addr, length, md5) → DOWNLOAD_DATA × N
          → DOWNLOAD_COMPLETE → SWITCH_STATE / REBOOT
```

`addr` is one of the region addresses above. Replacing the UI means flashing a
new `Texture.acf` to `0x08100000`; replacing a GIF slot means flashing to
`0x08500000`.

> **Danger.** Overwriting the wrong address, or writing a malformed image, can
> leave the panel unbootable. Dump and back up the regions *before* writing
> anything. The bootloader region is separate, so recovery is plausible, but it
> must be planned.

---

## 5. Two kinds of "GIF"

* **Selecting a preloaded GIF** — the panel already has three animated slots on
  pages 5/6/7. Selecting one is just a page switch. This works today.
* **Uploading a GIF** — requires compiling a GIF project into a `GIF_0.acf`
  with the vendor tool (or a reimplementation) and flashing it to
  `0x08500000`. Not implemented here.

---

## 6. Summary of possibilities

| Goal | Requires | Status |
|---|---|---|
| Write values / switch pages | `SET_REGISTER` | implemented |
| Notifications, clock, brightness | `SET_REGISTER` | implemented |
| Select a preloaded GIF | page switch | implemented |
| Upload a custom GIF | ACF-GIF compiler + flash write | not implemented |
| Deliver a custom UI/layout | ACF compiler + flash write | not implemented |
