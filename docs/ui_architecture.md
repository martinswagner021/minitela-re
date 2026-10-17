# On-screen UI architecture

This describes the structure of the UI that runs **on the display itself** (the
compiled asset in flash), as recovered from the packaged UI definition
(`data.json`). It is background for understanding what the registers control.

See [`registers-and-pages.md`](registers-and-pages.md) for the register map and
[`hardware-and-flash.md`](hardware-and-flash.md) for the flash/ACF side.

---

## Composition model

The UI is built in a fixed layer hierarchy:

```text
Page
 └─ MyLayer      (canvas / group, positioned by x,y,w,h)
     └─ MySubLayer
         └─ widgetList[]   (leaf widgets: text, image, icon, animation, …)
```

Canvas size is 240×240. Each leaf widget binds to a **tag** (a register name
from `tagList`) and has a default appearance/text. At runtime the host only
changes the bound values — it does not restructure the tree.

---

## Pages

| Page | Name | Notable content |
|---|---|---|
| 1 | WhatsApp | header + message canvas (sender + body + timestamp) |
| 2 | Reminder | notes/reminder text |
| 3 | SystemInfo | battery, WiFi, Bluetooth panels |
| 4 | Weather | current conditions + forecast |
| 5–7 | Gif1/Gif2/Gif3 | one animated texture layer each |

---

## SystemInfo page detail

Layers (Grouped canvases):

* **Top** — header/branding strip.
* **Battery** — an icon widget (`BatteryStatus`) bound to `Battery_Type`
  (`1150`) and a text widget (`batteryPercente`, `MyTextInput`) bound to
  `Battery_Percent` (`1082`). The text widget renders the string verbatim, so
  the value must include the unit (`"80%"`). The icon widget has only four
  textures (`BAT_0`..`BAT_3`), so `Battery_Type` must be `0..3`.
* **Wifi** — a signal icon and an SSID text widget bound to `Wifi_SSID`
  (`1083`). There is **no** signal-quality register in this build.
* **Bluetooth** — an icon and a device-name text widget bound to `BT_Name`
  (`1085`).

---

## Widget types seen in the project

The project declares custom widget types including a pie chart, a GIF player, a
video player and a list. These are rendered by the device's engine; the host
does not synthesise them.

---

## Assets

Widgets reference pre-rendered PNG assets (per page/canvas), font atlases
(e.g. Inconsolata at several sizes), and GIF files. All of these are compiled
into the `Texture.acf` UI image on the device.
