#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""
Minitela controller library + CLI.

Open-source, reverse-engineered controller for the secondary 240x240 mini
display shipped on the Positivo R15m (GalaxyCore GC9002 / "AHMI" platform).

Protocol ground truth was recovered with REA from the shipped Electron
"MiniPanel" ASAR (``extracted/app.asar``) -- see ``docs/protocol.md`` and
``docs/findings.md``.  In particular the register write framing below matches
``src/utils/messageProcessor.js`` and ``src/utils/command.js`` byte for byte.

Device: USB CDC ACM serial (CherryUSB "sxw-admin CDC DEMO", 0324:0324) at
115200 8N1, normally /dev/ttyACM0.

WARNING: no CRC is verified by the device. The shipped code either disables
CRC (``00 00``) or sends the hardcoded placeholder ``E2 CB``; both are accepted.
"""

from __future__ import annotations

import argparse
import glob
import os
import select
import struct
import subprocess
import sys
import termios
import time

# --------------------------------------------------------------------------
# Protocol constants (verified against app.asar)
# --------------------------------------------------------------------------

START_FLAG = bytes([0x41, 0x48])  # "AH"
END_FLAG = bytes([0x4D, 0x49])    # "MI"

CMD_HANDSHAKE = 0x0080
CMD_HANDSHAKE_RESPONSE = 0x00C0
CMD_SWITCH_STATE = 0x0071
CMD_SWITCH_STATE_RESPONSE = 0x00B1
CMD_SET_REGISTER = 0x0090
CMD_SET_REGISTER_RESPONSE = 0x00D0

BAUD = termios.B115200

# Content-header nibbles for CMD_SET_REGISTER
HDR_WRITE_NUM = 0x80   # 0b1000: write numeric register(s)
HDR_READ_NUM = 0xC0    # 0b1100: read numeric register(s)
HDR_WRITE_STR = 0xD0   # 0b1101: write string register
HDR_READ_STR = 0xE0    # 0b1110: read string register

# --------------------------------------------------------------------------
# System + status registers
# --------------------------------------------------------------------------

REG_CURRENT_PAGE = 2
REG_DATE = 4
REG_TIME = 5
REG_BRIGHTNESS = 7

REG_CPU_USAGE = 1080
REG_GPU_USAGE = 1081
REG_BATTERY_PERCENT = 1082
REG_WIFI_SSID = 1083
REG_WIFI_QUALITY = 1084
REG_BT_NAME = 1085
REG_BT_STATUS = 1086
REG_WIFI_STATUS = 1087
REG_BATTERY_TYPE = 1150
REG_NOTIF_TITLE_1 = 1140
REG_NOTIF_CONTENT_1 = 1141
REG_WHATSAPP_LOGO = 2005
REG_DATE_HOUR = 2006
REG_NOTIF_TRIGGER_1 = 0x7E9  # 2025 MessageBackground1
REG_NOTIF_TRIGGER_2 = 0x7EA  # 2026 MessageBackground2

# The registers this firmware actually defines (data.json tagList). Writing
# registers outside this set is tolerated but has no effect.
KNOWN_REGISTERS = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
    20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 65,
    1082, 1083, 1085, 1090, 1110, 1115, 1119, 1120, 1124,
    1140, 1141, 1150,
    2000, 2001, 2002, 2005, 2006, 2025, 2026, 2027, 2030, 2031, 2032,
}

# String register capacities (from the packaged data.json tagList)
STRING_CAPACITY = {
    REG_NOTIF_TITLE_1: 36,
    REG_NOTIF_CONTENT_1: 96,
    REG_BATTERY_PERCENT: 32,
    REG_WIFI_SSID: 32,
    REG_BT_NAME: 32,
    REG_DATE_HOUR: 32,
}
DEFAULT_STRING_CAPACITY = 32

# Registers whose *wire type* is string (data.json valueType 1). Note in
# particular that Battery_Percent (1082) is a string on this firmware: numeric
# writes to it are silently ignored.
STRING_REGISTERS = {
    0,  # notification2 (string aliases)
    1082,  # Battery_Percent
    1083,  # Wifi_SSID
    1085,  # BT_Name
    1090,  # Reminder1
    1119, 1124,  # Weather descriptions
    1140, 1141,  # Notification sender/content
    2006,  # dateHour "DD/MM HH:MM"
    2027, 2030, 2031, 2032,  # Weather strings
}

# --------------------------------------------------------------------------
# Pages. The panel's "current page" register (2) is 1-based: the shipped app
# calls showPage(pageId) which sends `pageId` and stores `pageId - 1` as the
# 0-based pageList index (see extracted/electron.js). So register value =
# pageList index + 1.
# --------------------------------------------------------------------------

PAGE_WHATSAPP = 1      # pageList index 0
PAGE_REMINDERS = 2     # index 1
PAGE_SYSTEM_INFO = 3   # index 2
PAGE_WEATHER = 4       # index 3
PAGE_GIF_1 = 5         # index 4
PAGE_GIF_2 = 6         # index 5
PAGE_GIF_3 = 7         # index 6

PAGE_NAMES = {
    PAGE_WHATSAPP: "WhatsApp",
    PAGE_REMINDERS: "Reminder",
    PAGE_SYSTEM_INFO: "SystemInfo",
    PAGE_WEATHER: "Weather",
    PAGE_GIF_1: "Gif1",
    PAGE_GIF_2: "Gif2",
    PAGE_GIF_3: "Gif3",
}


# --------------------------------------------------------------------------
# Packet builders
# --------------------------------------------------------------------------

def build_frame(command: int, content: bytes, crc: bytes = b"\x00\x00") -> bytes:
    """Wrap a command + content in the AH..MI frame.

    controlFlag = 2 (command type) + len(content), CRC disabled.  Matches
    ``Command.getCommandBuffer()`` with ``enableCRC=false``.
    """
    control = struct.pack(">H", len(content) + 2)
    return START_FLAG + control + struct.pack(">H", command) + content + crc + END_FLAG


def build_numeric(pairs) -> bytes:
    """CMD_SET_REGISTER write for 1..16 (register, value) pairs.

    content = HDR_WRITE_NUM|(n-1) + for each: reg(2 BE) + value(4 BE)
    """
    pairs = list(pairs)[:16]
    if not pairs:
        raise ValueError("at least one register is required")
    content = bytes([HDR_WRITE_NUM | ((len(pairs) - 1) & 0x0F)])
    for reg, value in pairs:
        content += struct.pack(">H", reg) + struct.pack(">I", int(value) & 0xFFFFFFFF)
    return build_frame(CMD_SET_REGISTER, content)


def build_read_numeric(reg_ids) -> bytes:
    """CMD_SET_REGISTER read for 1..16 numeric registers."""
    reg_ids = list(reg_ids)[:16]
    if not reg_ids:
        raise ValueError("at least one register is required")
    content = bytes([HDR_READ_NUM | ((len(reg_ids) - 1) & 0x0F)])
    for reg in reg_ids:
        content += struct.pack(">H", reg)
    return build_frame(CMD_SET_REGISTER, content)


def build_string(reg: int, text: str, capacity: int | None = None) -> bytes:
    """CMD_SET_REGISTER write for a string register.

    content = HDR_WRITE_STR + reg(2 BE) + byteLen(2 BE) + utf-8 bytes

    A zero-length payload corrupts the device's register table (it then stops
    answering reads and mangles register 2), so empty strings are sent as a
    single space instead.
    """
    cap = capacity or STRING_CAPACITY.get(reg, DEFAULT_STRING_CAPACITY)
    data = text.encode("utf-8")[:cap]
    if not data:
        data = b" "
    content = bytes([HDR_WRITE_STR]) + struct.pack(">H", reg) + struct.pack(">H", len(data)) + data
    return build_frame(CMD_SET_REGISTER, content)


def build_brightness_raw(value: int) -> bytes:
    """Hardcoded brightness command used by the shipped app (register 7)."""
    value = max(0, min(100, int(value)))
    return bytes([
        0x41, 0x48, 0x80, 0x09, 0x00, 0x90, 0x80,
        0x00, 0x07, 0x00, 0x00, 0x00, value,
        0xE2, 0xCB, 0x4D, 0x49,
    ])


# --------------------------------------------------------------------------
# Host status helpers
# --------------------------------------------------------------------------

def _read_first(paths, default=None, cast=int):
    for path in paths:
        try:
            with open(path) as fh:
                return cast(fh.read().strip())
        except Exception:
            continue
    return default


def get_battery_percent() -> int:
    value = _read_first(
        glob.glob("/sys/class/power_supply/BAT*/capacity"),
        default=100,
    )
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return 100


def battery_type(percent: int) -> int:
    """Battery icon bucket.

    The panel's ``BatteryStatus`` widget is a slide with only four textures
    (``BAT_0``..``BAT_3``), so the value must stay in 0..3. (The shipped app
    computes 0..5, but values 4/5 render no icon at all.)
    """
    if percent < 25:
        return 0
    if percent < 50:
        return 1
    if percent < 75:
        return 2
    return 3


def get_cpu_percent(sample: float = 0.05) -> int:
    def snap():
        with open("/proc/stat") as fh:
            fields = [float(x) for x in fh.readline().split()[1:5]]
        idle, total = fields[3], sum(fields)
        return idle, total

    try:
        idle1, total1 = snap()
        time.sleep(sample)
        idle2, total2 = snap()
        dt, di = total2 - total1, idle2 - idle1
        if dt > 0:
            return max(0, min(100, int(100.0 * (dt - di) / dt)))
    except Exception:
        pass
    return 0


def get_wifi_ssid() -> str:
    for cmd in (["iwgetid", "-r"], ["/usr/sbin/iwgetid", "-r"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            ssid = out.stdout.strip()
            if ssid:
                return ssid
        except Exception:
            continue
    # iwgetid is not always installed; fall back to NetworkManager. It can
    # transiently return nothing while talking to D-Bus, so retry a couple of
    # times before giving up.
    for _ in range(3):
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True, text=True, timeout=3,
            )
            for line in out.stdout.splitlines():
                active, _, ssid = line.partition(":")
                if active.strip() == "yes" and ssid:
                    return ssid
        except Exception:
            pass
        time.sleep(0.3)
    return ""


def get_wifi_quality() -> int:
    """Return the display bucket 0..3 from the active link signal (0..100)."""
    signal = None
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi"],
            capture_output=True, text=True, timeout=3,
        )
        for line in out.stdout.splitlines():
            parts = line.split(":")
            if parts and parts[0].strip() == "*" and len(parts) > 1:
                signal = int(parts[1])
                break
    except Exception:
        pass
    if signal is None:
        return 3 if get_wifi_ssid() else 0
    if signal <= 30:
        return 0
    if signal <= 50:
        return 1
    if signal < 70:
        return 2
    return 3


def get_bt_name() -> str:
    try:
        out = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True, text=True, timeout=3,
        )
        for line in out.stdout.splitlines():
            if line.startswith("Device"):
                return " ".join(line.split()[2:])
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------------
# Device
# --------------------------------------------------------------------------

class MinitelaError(Exception):
    pass


class MinitelaDevice:
    def __init__(self, port: str | None = None):
        self.port = port or self.detect_port()
        if not self.port:
            raise MinitelaError("No /dev/ttyACM* device found for the Minitela display.")
        self.fd: int | None = None
        self._rxbuf = b""

    @staticmethod
    def detect_port() -> str | None:
        candidates = sorted(glob.glob("/dev/ttyACM*"))
        return candidates[0] if candidates else None

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if self.fd is not None:
            return
        try:
            self.fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except PermissionError as exc:
            raise MinitelaError(
                f"Cannot open {self.port}: {exc}. Install the udev rule "
                "(99-minitela.rules) or add your user to the 'uucp' group."
            ) from exc
        self._configure_tty()
        # The device resets on port open (DTR toggle) and drops commands while
        # it boots; wait it out. Do NOT send HANDSHAKE here: it switches the
        # device into upload mode, where register commands are ignored until
        # the next reboot.
        time.sleep(1.2)

    def _configure_tty(self) -> None:
        """115200 8N1, raw mode (the shipped app relies on serialport's defaults)."""
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = 0                       # iflag: raw
        attrs[1] = 0                       # oflag: raw
        attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        attrs[3] = 0                       # lflag: non-canonical
        attrs[4] = BAUD                    # ispeed
        attrs[5] = BAUD                    # ospeed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- io ----------------------------------------------------------------

    def write(self, packet: bytes, settle: float = 0.03) -> None:
        if self.fd is None:
            self.open()
        os.write(self.fd, packet)
        if settle:
            time.sleep(settle)

    def _read_frame(self, timeout: float = 0.5) -> bytes | None:
        """Extract one complete AH..MI frame from the input stream.

        Device *responses* set bit 15 of the control flag (CRC-enabled marker),
        so the length is masked with 0x7FFF.
        """
        deadline = time.time() + timeout
        while True:
            start = self._rxbuf.find(START_FLAG)
            if start != -1 and len(self._rxbuf) >= start + 4:
                length = struct.unpack(">H", self._rxbuf[start + 2:start + 4])[0] & 0x7FFF
                total = 4 + length + 2 + 2  # ctrl+hdr+content+crc+end
                if len(self._rxbuf) >= start + total:
                    frame = self._rxbuf[start:start + total]
                    self._rxbuf = self._rxbuf[start + total:]
                    return frame
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(self.fd, 4096)
            if not chunk:
                return None
            self._rxbuf += chunk

    @staticmethod
    def parse_frame(frame: bytes) -> dict:
        command = struct.unpack(">H", frame[4:6])[0]
        content_len = (struct.unpack(">H", frame[2:4])[0] & 0x7FFF) - 2
        content = frame[6:6 + content_len]
        return {"command": command, "content": content}

    def flush_input(self) -> None:
        """Discard stale input (e.g. queued write-acknowledgements)."""
        if self.fd is None:
            return
        try:
            termios.tcflush(self.fd, termios.TCIFLUSH)
        except Exception:
            pass
        self._rxbuf = b""

    def _transact(self, packet: bytes, expect_func: int, timeout: float = 0.5,
                  retries: int = 4) -> dict | None:
        """Send a command and return the matching SET_REGISTER_RESPONSE.

        ``expect_func`` is the response function code (0 = numeric, 1 = string).
        Stale write-acknowledgements (function code 2) and any other stray
        frames are skipped. The device occasionally drops a command after the
        port opens or while it is busy, so a few retries are made.
        """
        for attempt in range(retries):
            self.flush_input()
            self.write(packet, settle=0.05)
            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                frame = self._read_frame(remaining)
                if not frame:
                    break
                parsed = self.parse_frame(frame)
                if parsed["command"] != CMD_SET_REGISTER_RESPONSE or not parsed["content"]:
                    continue
                if ((parsed["content"][0] >> 4) & 0x07) == expect_func:
                    return parsed
            time.sleep(0.1 * (attempt + 1))
        return None

    def handshake(self, timeout: float = 1.0) -> dict | None:
        self.flush_input()
        self.write(build_frame(CMD_HANDSHAKE, b""), settle=0)
        frame = self._read_frame(timeout)
        if not frame:
            return None
        parsed = self.parse_frame(frame)
        if parsed["command"] != CMD_HANDSHAKE_RESPONSE:
            return None
        max_packet = struct.unpack(">I", parsed["content"][:4])[0] if len(parsed["content"]) >= 4 else None
        return {"max_packet_length": max_packet, "frame": frame.hex()}

    def read_numeric(self, reg: int, timeout: float = 0.5):
        """Read a numeric register; returns int or None."""
        parsed = self._transact(build_read_numeric([reg]), expect_func=0, timeout=timeout)
        if not parsed:
            return None
        content = parsed["content"]
        if len(content) < 7:
            return None
        got = struct.unpack(">H", content[1:3])[0]
        if got != reg:
            return None
        return struct.unpack(">I", content[3:7])[0]

    def read_string(self, reg: int, capacity: int = 64, timeout: float = 0.5) -> str | None:
        """Read a string register (functionCode 1). Trailing NULs are stripped."""
        content = bytes([HDR_READ_STR]) + struct.pack(">H", reg) + struct.pack(">H", capacity)
        parsed = self._transact(build_frame(CMD_SET_REGISTER, content), expect_func=1, timeout=timeout)
        if not parsed:
            return None
        data = parsed["content"]
        if len(data) < 5:
            return None
        got = struct.unpack(">H", data[1:3])[0]
        if got != reg:
            return None
        length = struct.unpack(">H", data[3:5])[0]
        raw = data[5:5 + length]
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")

    # -- register writers --------------------------------------------------

    def write_register(self, packet: bytes, timeout: float = 0.3) -> bool:
        """Send a SET_REGISTER frame and drain its acknowledgement.

        The device sends one response per write and has a small TX buffer; if
        the host never reads them the buffer overflows and the firmware hangs.
        Reading every acknowledgement (as the shipped app does) keeps it
        healthy. Returns True if an acknowledgement was seen.
        """
        self.flush_input()
        self.write(packet, settle=0)
        deadline = time.time() + timeout
        seen = False
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            frame = self._read_frame(remaining)
            if not frame:
                break
            parsed = self.parse_frame(frame)
            if parsed["command"] == CMD_SET_REGISTER_RESPONSE:
                seen = True
        # This firmware corrupts its register table if commands arrive
        # back-to-back; enforce a minimum gap between SET_REGISTER frames.
        time.sleep(0.15)
        return seen

    def set_numeric(self, reg: int, value: int) -> None:
        self.write_register(build_numeric([(reg, value)]))

    def set_numeric_many(self, pairs) -> None:
        pairs = list(pairs)
        for i in range(0, len(pairs), 16):
            self.write_register(build_numeric(pairs[i:i + 16]))

    def set_string(self, reg: int, text: str) -> None:
        self.write_register(build_string(reg, text))

    def set_value(self, reg: int, value) -> None:
        """Write a register choosing the correct wire type automatically."""
        if reg in STRING_REGISTERS or isinstance(value, str):
            self.set_string(reg, str(value))
        else:
            self.set_numeric(reg, int(value))

    def set_brightness(self, level: int) -> None:
        self.write_register(build_brightness_raw(level))

    def set_page(self, page: int) -> None:
        self.set_numeric(REG_CURRENT_PAGE, page)

    def show_gif(self, slot: int) -> None:
        self.set_page({1: PAGE_GIF_1, 2: PAGE_GIF_2, 3: PAGE_GIF_3}.get(slot, PAGE_GIF_1))

    def set_datetime(self, when: time.struct_time | None = None, force: bool = False) -> None:
        t = when or time.localtime()
        # The clock widget on the status/weather pages binds to the string
        # register 2006, formatted "DD/MM HH:MM" (its default text). Only push
        # when it changes to keep the serial traffic (and the device) calm.
        stamp = f"{t.tm_mday:02d}/{t.tm_mon:02d} {t.tm_hour:02d}:{t.tm_min:02d}"
        if not force and getattr(self, "_last_datetime", None) == stamp:
            return
        # Shipped app encodes decimal digits then parses as hex (BCD-ish).
        date_val = int(f"{t.tm_year:04d}{t.tm_mon:02d}{t.tm_mday:02d}", 16)
        time_val = int(f"{t.tm_hour:02d}{t.tm_min:02d}{t.tm_sec:02d}", 16)
        self.set_numeric_many([(REG_DATE, date_val), (REG_TIME, time_val)])
        self.set_string(REG_DATE_HOUR, stamp)
        self._last_datetime = stamp

    # -- high level --------------------------------------------------------

    def update_system_status(self, cpu_percent=None, battery_percent=None,
                             wifi_ssid=None, bt_name=None, force: bool = False) -> dict:
        cpu = get_cpu_percent() if cpu_percent is None else cpu_percent
        bat = get_battery_percent() if battery_percent is None else battery_percent
        ssid = get_wifi_ssid() if wifi_ssid is None else wifi_ssid
        bt = get_bt_name() if bt_name is None else bt_name

        # Only registers the firmware actually defines are written. CPU/GPU
        # (1080/1081) and wifi/BT status (1084/1086/1087) do not exist in this
        # build's tagList, so they are intentionally omitted.
        #
        # Each register is written only when its value changes: flooding the
        # device with redundant writes corrupts its register table over time.
        cache = getattr(self, "_status_cache", None)
        if cache is None:
            cache = self._status_cache = {}

        def changed(key, value) -> bool:
            if force or cache.get(key) != value:
                cache[key] = value
                return True
            return False

        bat_type = battery_type(int(bat))
        if changed("battery_type", bat_type):
            self.set_numeric(REG_BATTERY_TYPE, bat_type)
        # These are string registers on the GC9002 firmware.
        # The widget (MyTextInput "batteryPercente") renders the raw string it
        # receives, so the unit glyph must be included here: the shipped
        # default text is "100%". Sending bare "80" shows no percent sign.
        bat_text = f"{int(bat)}%"
        if changed("battery", bat_text):
            self.set_string(REG_BATTERY_PERCENT, bat_text)
        if changed("ssid", ssid):
            self.set_string(REG_WIFI_SSID, ssid)
        if changed("bt", bt):
            self.set_string(REG_BT_NAME, bt)
        return {"cpu": cpu, "battery": bat, "wifi_ssid": ssid, "bt_name": bt}

    def send_whatsapp_notification(self, title: str, message: str) -> None:
        self.set_string(REG_NOTIF_TITLE_1, title)
        self.set_string(REG_NOTIF_CONTENT_1, message)
        self.set_numeric_many([
            (REG_NOTIF_TRIGGER_1, 1),
            (REG_NOTIF_TRIGGER_2, 1),
        ])
        self.set_page(PAGE_WHATSAPP)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Minitela display controller")
    parser.add_argument("--port", help="Serial port (default: first /dev/ttyACM*)")
    parser.add_argument("--brightness", type=int, help="Set backlight brightness (0-100)")
    parser.add_argument("--page", type=int, choices=range(1, 8),
                        help="Switch page: 1 WhatsApp, 2 Reminder, 3 Status, 4 Weather, 5-7 GIFs")
    parser.add_argument("--status", action="store_true", help="Send live status and show the status page")
    parser.add_argument("--sync", action="store_true", help="Send live status only (no page switch)")
    parser.add_argument("--whatsapp", nargs=2, metavar=("SENDER", "MESSAGE"),
                        help="Show a WhatsApp-style notification")
    parser.add_argument("--gif", type=int, choices=[1, 2, 3], help="Show GIF slot 1-3")
    parser.add_argument("--datetime", action="store_true", help="Sync date/time registers")
    parser.add_argument("--handshake", action="store_true",
                        help="Handshake (NOTE: switches the device into upload mode; reboot to exit)")
    parser.add_argument("--read", type=int, metavar="REG", help="Read a numeric register")
    parser.add_argument("--read-str", type=int, metavar="REG", help="Read a string register")
    args = parser.parse_args(argv)

    with MinitelaDevice(args.port) as dev:
        print(f"Minitela on {dev.port}")
        if args.handshake:
            print("handshake:", dev.handshake())
        if args.brightness is not None:
            dev.set_brightness(args.brightness)
            print(f"brightness -> {args.brightness}")
        if args.page is not None:
            dev.set_page(args.page)
            print(f"page -> {args.page} ({PAGE_NAMES.get(args.page, '?')})")
        if args.status:
            info = dev.update_system_status(force=True)
            dev.set_datetime(force=True)
            dev.set_page(PAGE_SYSTEM_INFO)
            print(f"status -> {info}")
        if args.sync:
            print(f"status -> {dev.update_system_status(force=True)}")
        if args.whatsapp:
            dev.send_whatsapp_notification(*args.whatsapp)
            print(f"notification -> {args.whatsapp[0]}")
        if args.gif:
            dev.show_gif(args.gif)
            print(f"gif -> {args.gif}")
        if args.datetime:
            dev.set_datetime(force=True)
            print("datetime synced")
        if args.read is not None:
            print(f"reg {args.read} = {dev.read_numeric(args.read)}")
        if args.read_str is not None:
            print(f"reg {args.read_str} = {dev.read_string(args.read_str)!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
