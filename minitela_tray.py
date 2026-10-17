#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""
Minitela system-tray controller (GTK3 / Ayatana AppIndicator).

A tray icon plus a small control panel to drive the mini display through the
background daemon (``minitela_daemon.py``).  Works on Wayland (Hyprland/Omarchy)
via the StatusNotifierItem protocol.

Run the daemon first, then:
    python3 minitela_tray.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

from minitela_client import MinitelaClient  # noqa: E402
from minitela import PAGE_NAMES  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_UI = os.path.join(HERE, "web_ui.py")


def _resolve_icon() -> str:
    """Return the tray icon: our own asset, else a stock theme icon name.

    The project ships its own icon (``assets/minitela.png``). If it is missing
    we fall back to a freedesktop icon name so the tray item is never left
    without an icon (the vendor artwork is intentionally not shipped).
    """
    candidate = os.path.join(HERE, "assets", "minitela.png")
    if os.path.exists(candidate):
        return candidate
    return "video-display"


ICON = _resolve_icon()


class TrayApp:
    def __init__(self, client: MinitelaClient):
        self.client = client
        self.window: Gtk.Window | None = None

        self.indicator = AppIndicator.Indicator.new(
            "minitela", ICON, AppIndicator.IndicatorCategory.HARDWARE,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Minitela")
        self.indicator.set_menu(self._build_menu())

        GLib.timeout_add_seconds(10, self._tick)

    # -- menu --------------------------------------------------------------

    def _menu_item(self, label, callback, sensitive=True):
        item = Gtk.MenuItem(label=label)
        item.set_sensitive(sensitive)
        item.connect("activate", callback)
        return item

    def _build_menu(self):
        menu = Gtk.Menu()

        header = Gtk.MenuItem(label="Minitela display")
        header.set_sensitive(False)
        menu.append(header)

        menu.append(self._menu_item("Control panel…", self._open_window))
        menu.append(self._menu_item("Sync status now", lambda *_: self._status(show=True)))

        pages = Gtk.MenuItem(label="Screen page")
        sub = Gtk.Menu()
        for page, name in PAGE_NAMES.items():
            sub.append(self._menu_item(name, lambda _w, p=page: self._page(p)))
        pages.set_submenu(sub)
        menu.append(pages)

        gifs = Gtk.MenuItem(label="GIF animation")
        sub = Gtk.Menu()
        for slot, name in ((1, "Gif1"), (2, "Gif2"), (3, "Gif3")):
            sub.append(self._menu_item(name, lambda _w, s=slot: self._gif(s)))
        gifs.set_submenu(sub)
        menu.append(gifs)

        bright = Gtk.MenuItem(label="Brightness")
        sub = Gtk.Menu()
        for level in (0, 25, 50, 75, 100):
            sub.append(self._menu_item(f"{level}%", lambda _w, v=level: self._brightness(v)))
        sub.append(Gtk.SeparatorMenuItem())
        sub.append(self._menu_item("Custom…", self._open_window))
        bright.set_submenu(sub)
        menu.append(bright)

        menu.append(self._menu_item("Send notification…", self._open_window))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._menu_item("Open web control", self._open_web))
        menu.append(self._menu_item("Quit tray", lambda *_: Gtk.main_quit()))
        menu.show_all()
        return menu

    def _tick(self):
        # keep the header fresh; cheap ping only (no serial traffic)
        ping = self.client.ping()
        if ping.get("ok"):
            status = ping.get("status") or {}
            battery = status.get("battery")
            self.indicator.set_label(f"{battery}%" if battery is not None else "", "")
        else:
            self.indicator.set_label("offline", "")
        return True

    # -- actions -----------------------------------------------------------

    def _run_async(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _status(self, show=False):
        self._run_async(self.client.status, show)

    def _page(self, page):
        self._run_async(self.client.set_page, page)

    def _gif(self, slot):
        self._run_async(self.client.gif, slot)

    def _brightness(self, value):
        self._run_async(self.client.set_brightness, value)

    def _open_web(self, *_):
        try:
            subprocess.Popen([sys.executable, WEB_UI])
        except Exception:
            pass

    # -- control window ----------------------------------------------------

    def _open_window(self, *_):
        if self.window is not None:
            self.window.present()
            return
        self.window = self._build_window()

    def _build_window(self):
        win = Gtk.Window(title="Minitela Control")
        win.set_border_width(16)
        win.set_default_size(420, 520)
        win.connect("destroy", self._on_window_destroy)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        win.add(root)

        title = Gtk.Label()
        title.set_markup("<b>Minitela control panel</b>")
        root.pack_start(title, False, False, 0)

        self.conn_label = Gtk.Label(label="")
        self.conn_label.set_xalign(0)
        root.pack_start(self.conn_label, False, False, 0)

        # Brightness
        root.pack_start(self._section("Brightness"), False, False, 0)
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.bright.set_value(80)
        self.bright.connect("value-changed", self._on_bright)
        root.pack_start(self.bright, False, False, 0)

        # Pages
        root.pack_start(self._section("Screen page"), False, False, 0)
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        for i, (page, name) in enumerate(PAGE_NAMES.items()):
            btn = Gtk.Button(label=name)
            btn.connect("clicked", lambda _b, p=page: self._page(p))
            grid.attach(btn, i % 4, i // 4, 1, 1)
        root.pack_start(grid, False, False, 0)

        # Notification
        root.pack_start(self._section("Notification"), False, False, 0)
        self.title_entry = Gtk.Entry()
        self.title_entry.set_placeholder_text("Sender (e.g. Maria)")
        self.title_entry.set_text("WhatsApp")
        root.pack_start(self.title_entry, False, False, 0)
        self.msg_entry = Gtk.Entry()
        self.msg_entry.set_placeholder_text("Message")
        self.msg_entry.set_text("Meeting at 2:00 PM")
        root.pack_start(self.msg_entry, False, False, 0)
        send = Gtk.Button(label="Push notification")
        send.connect("clicked", self._send_notify)
        root.pack_start(send, False, False, 0)

        # Live status
        root.pack_start(self._section("Live status"), False, False, 0)
        self.status_label = Gtk.Label(label="—")
        self.status_label.set_xalign(0)
        self.status_label.set_line_wrap(True)
        root.pack_start(self.status_label, False, False, 0)

        win.show_all()
        self._refresh_window()
        GLib.timeout_add_seconds(5, self._refresh_window)
        return win

    @staticmethod
    def _section(text):
        label = Gtk.Label()
        label.set_markup(f"<b>{text}</b>")
        label.set_xalign(0)
        return label

    def _on_window_destroy(self, *_):
        self.window = None

    def _on_bright(self, scale):
        self._brightness(int(scale.get_value()))

    def _send_notify(self, *_):
        title = self.title_entry.get_text() or "WhatsApp"
        message = self.msg_entry.get_text()
        self._run_async(self.client.notify, title, message)

    def _refresh_window(self):
        if self.window is None:
            return False
        ping = self.client.ping()
        if not ping.get("ok"):
            self.conn_label.set_markup("<span foreground='red'>Daemon offline</span>")
            self.status_label.set_text("Start minitela_daemon.py, then reopen.")
            return True
        self.conn_label.set_markup("<span foreground='green'>Daemon connected</span>")
        status = ping.get("status") or {}
        if status:
            self.status_label.set_text(
                f"Battery: {status.get('battery')}%   CPU: {status.get('cpu')}%\n"
                f"WiFi: {status.get('wifi_ssid') or '—'}\n"
                f"Bluetooth: {status.get('bt_name') or '—'}"
            )
        return True


def main():
    client = MinitelaClient()
    TrayApp(client)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
