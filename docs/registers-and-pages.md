# Registers and pages

This document lists the registers the firmware actually exposes, their wire
types, and how they map onto the device's pages. It was derived from the
packaged UI definition (`data.json` → `tagList`) and confirmed live.

> The **wire type** is authoritative: sending a numeric frame to a string
> register (or vice-versa) is silently ignored by the device.

---

## 1. Pages

The device UI has a fixed set of pages. The *current page* is register `2`, and
it is **1-based** (the packaged `pageList` is 0-based; the vendor app sends
`pageId` and treats `pageId - 1` as the list index).

| Register `2` value | Page | Packaged `pageList` index |
|---|---|---|
| `1` | WhatsApp | 0 |
| `2` | Reminder (notes) | 1 |
| `3` | SystemInfo | 2 |
| `4` | Weather | 3 |
| `5` | Gif1 | 4 |
| `6` | Gif2 | 5 |
| `7` | Gif3 | 6 |

The packaged project also defines three empty `New-page` entries (indices 7–9)
that are not reachable from the register.

---

## 2. Register map

Only registers defined in the packaged `tagList` exist. Type strings quote the
`valueType` field (`0` = number, `1` = string).

| Reg | Name | Wire type | Notes |
|----:|------|-----------|-------|
| `2` | Current page | number | 1-based, see §1 |
| `4` | Clock date | number | BCD-ish hex encoding (`YYYYMMDD` as hex) |
| `5` | Clock time | number | BCD-ish hex encoding (`HHMMSS` as hex) |
| `7` | Backlight | number | 0..100 |
| `1082` | `Battery_Percent` | **string** | rendered verbatim → send `"80%"` |
| `1083` | `Wifi_SSID` | string | capacity 32 |
| `1085` | `BT_Name` | string | capacity 32 |
| `1090` | `Reminder1` | string | capacity 100 |
| `1110` | `Weather_1_Type` | number | weather icon selector |
| `1115` | `Weather_2_Type` | number | |
| `1120` | `Weather_3_Type` | number | |
| `1119` | `Weather_Desc` | string | |
| `1124` | `Weather_Desc2` | string | |
| `1140` | `Notification_1_Title` | string | capacity 36 (sender name) |
| `1141` | `Notification_1_Content` | string | capacity 96 (message body) |
| `1150` | `Battery_Type` | number | icon bucket, valid `0..3` only |
| `2005` | `whatsapp_logo` | number | `1` shows the WhatsApp badge |
| `2006` | `dateHour` | **string** | clock text, `"DD/MM HH:MM"` |
| `2025` | `Notification_Trigger_1` | number | set to `1` to fire the pop-up |
| `2026` | `Notification_Trigger_2` | number | set to `1` for the badge |
| `2027` | Weather city | string | |
| `2030`/`2031`/`2032` | Weather min/max temps | string | |

### Not present in this firmware

`1080` (CPU), `1081` (GPU), `1084` (Wifi_Quality), `1086` (BT_Status),
`1087` (Wifi_Status) are **not defined**. Writing them is harmless but has no
effect. Their absence explains why a CPU/GPU/WiFi-signal readout cannot be
driven on this build.

### `Battery_Type` buckets

`Battery_Type` (`1150`) selects one of four icon textures (`BAT_0`..`BAT_3`).
Values above 3 render **no icon**. The mapping used here is:

| Battery % | `Battery_Type` |
|---|---|
| `< 25` | `0` |
| `< 50` | `1` |
| `< 75` | `2` |
| `>= 75` | `3` |

> The vendor utility computes `0..5`, so the icon disappears at ≥80% on a
> stock system. That is a bug in the original, not a limitation.

### `Battery_Percent` is a rendered string

The SystemInfo text widget (`batteryPercente`, a `MyTextInput`) renders exactly
the string it receives; its packaged default text is `"100%"`. Therefore the
percent **and** the unit must be sent together — `"80%"`, not `"80"`.

---

## 3. SystemInfo page bindings

The SystemInfo page is driven by:

| Register | Meaning |
|---|---|
| `1150` | battery icon bucket |
| `1082` | battery percent text (`"80%"`) |
| `1083` | WiFi SSID |
| `1085` | Bluetooth device name |
| `2005` | WhatsApp badge |
| `2006` | clock text (`"DD/MM HH:MM"`) |

There is no CPU/GPU/WiFi-signal binding in this build.

---

## 4. Clock encoding

Two representations exist and both are used:

* **Numeric registers `4`/`5`** take a BCD-ish hex value: the decimal string is
  parsed as hexadecimal, e.g. `2024-07-01` → `int("20240701", 16)`.
* **String register `2006` (`dateHour`)** takes the display string
  `"DD/MM HH:MM"`.

`minitela.py` writes both; the daemon keeps them in sync with the host clock.

---

## 5. Notification flow (WhatsApp)

1. Set `1140` (sender) and `1141` (body).
2. Set `2025` and `2026` to `1` to trigger the pop-up/badge.
3. Switch to page `1` (WhatsApp).

The daemon mirrors desktop notifications whose source matches "whatsapp" (see
[`software-architecture.md`](software-architecture.md)).
