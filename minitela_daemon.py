#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""
Minitela background daemon.

Owns the serial port so that only one process talks to the display, and:

  * keeps the status page in sync (battery / CPU / WiFi / Bluetooth / clock),
  * monitors desktop notifications over D-Bus and mirrors WhatsApp messages,
  * (best effort) blanks the panel on screen lock and restores on unlock,
  * serves a small newline-JSON control socket for the tray app / web UI / CLI.

Run:
    python3 minitela_daemon.py                 # foreground
    python3 minitela_daemon.py --socket PATH --interval 5

The socket defaults to $XDG_RUNTIME_DIR/minitela.sock.

Protocol framing is implemented in ``minitela.py`` and matches the shipped
Electron app recovered with REA.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time

from minitela import (
    MinitelaDevice,
    MinitelaError,
    PAGE_SYSTEM_INFO,
    REG_BRIGHTNESS,
)
from minitela_client import default_socket_path

log = logging.getLogger("minitela.daemon")

MONITOR_CMD = ["dbus-monitor", "interface='org.freedesktop.Notifications'"]
NOTIFY_HEADER = re.compile(r"member=Notify\b")
NOTIFY_IFACE = "org.freedesktop.Notifications"
STRING_RE = re.compile(r'^\s+string "(.*)"\s*$')


class DeviceSession:
    """Thread-safe, self-healing wrapper around MinitelaDevice."""

    def __init__(self, port: str | None):
        self._port = port
        self._dev: MinitelaDevice | None = None
        self._lock = threading.RLock()
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, value: bool) -> None:
        self._paused = value

    def _ensure(self) -> MinitelaDevice:
        if self._dev is None:
            self._dev = MinitelaDevice(self._port)
            self._dev.open()
            log.info("connected to %s", self._dev.port)
        return self._dev

    def _drop(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def call(self, fn, *args, **kwargs):
        with self._lock:
            try:
                dev = self._ensure()
                return fn(dev, *args, **kwargs)
            except (MinitelaError, OSError) as exc:
                log.warning("device error: %s", exc)
                self._drop()
                raise

    def close(self) -> None:
        with self._lock:
            self._drop()


class Daemon:
    def __init__(self, port: str | None, interval: float, socket_path: str,
                 notify_match: str, monitor_notifications: bool):
        self.session = DeviceSession(port)
        self.interval = interval
        self.socket_path = socket_path
        self.notify_match = notify_match.lower()
        self.monitor_notifications = monitor_notifications
        self._stop = threading.Event()
        self._last_status: dict = {}

    # -- status loop -------------------------------------------------------

    def _status_loop(self) -> None:
        while not self._stop.is_set():
            if not self.session.paused:
                try:
                    info = self.session.call(lambda d: d.update_system_status())
                    self.session.call(lambda d: d.set_datetime())
                    self._last_status = info
                    log.debug("status synced: %s", info)
                except Exception:
                    pass
            self._stop.wait(self.interval)

    # -- notification monitor ---------------------------------------------

    def _notification_loop(self) -> None:
        while not self._stop.is_set():
            proc = None
            try:
                proc = subprocess.Popen(
                    MONITOR_CMD, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
                log.info("monitoring notifications via dbus-monitor")
                self._parse_monitor(proc)
            except FileNotFoundError:
                log.error("dbus-monitor not found; notification mirroring disabled")
                return
            except Exception as exc:
                log.warning("notification monitor stopped: %s", exc)
            finally:
                if proc and proc.poll() is None:
                    proc.terminate()
            if self._stop.is_set():
                return
            log.info("restarting notification monitor in 3s")
            self._stop.wait(3)

    def _parse_monitor(self, proc: subprocess.Popen) -> None:
        collecting = False
        strings: list[str] = []
        for raw in proc.stdout:  # type: ignore[union-attr]
            if self._stop.is_set():
                return
            line = raw.rstrip("\n")
            if NOTIFY_HEADER.search(line) and NOTIFY_IFACE in line:
                collecting = True
                strings = []
                continue
            if collecting:
                if line[:1] in (" ", "\t"):
                    m = STRING_RE.match(line)
                    if m:
                        strings.append(_unescape(m.group(1)))
                    continue
                # end of this message
                collecting = False
                self._handle_notification(strings)
        if collecting:
            self._handle_notification(strings)

    def _handle_notification(self, strings: list[str]) -> None:
        # Notify args order: app_name, replaces_id(uint32), app_icon, summary, body, ...
        if len(strings) < 4:
            return
        app_name, app_icon, summary, body = strings[0], strings[1], strings[2], strings[3]
        haystack = f"{app_name} {app_icon} {summary}".lower()
        if self.notify_match and self.notify_match not in haystack:
            return
        log.info("notification from %r: %r", summary, body)
        try:
            self.session.call(lambda d: d.send_whatsapp_notification(summary or app_name, body))
        except Exception as exc:
            log.warning("failed to mirror notification: %s", exc)

    # -- control socket ----------------------------------------------------

    def _serve(self, server: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        with conn:
            try:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    return
                request = json.loads(data.decode("utf-8").splitlines()[0])
                response = self._dispatch(request)
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
            except Exception as exc:
                try:
                    conn.sendall((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
                except OSError:
                    pass

    def _dispatch(self, req: dict) -> dict:
        cmd = req.get("cmd")
        try:
            if cmd == "ping":
                return {"ok": True, "paused": self.session.paused,
                        "status": self._last_status}
            if cmd == "status":
                if self.session.paused:
                    return {"ok": True, "paused": True, "status": self._last_status}
                force = bool(req.get("show"))
                info = self.session.call(lambda d: d.update_system_status(force=force))
                info["datetime"] = self.session.call(lambda d: d.set_datetime(force=force)) or None
                self._last_status = info
                if force:
                    self.session.call(lambda d: d.set_page(PAGE_SYSTEM_INFO))
                return {"ok": True, "status": info}
            if cmd == "set_brightness":
                value = max(0, min(100, int(req["value"])))
                self.session.call(lambda d: d.set_brightness(value))
                return {"ok": True, "brightness": value}
            if cmd == "set_page":
                page = int(req["page"])
                self.session.call(lambda d: d.set_page(page))
                return {"ok": True, "page": page}
            if cmd == "gif":
                slot = int(req["slot"])
                self.session.call(lambda d: d.show_gif(slot))
                return {"ok": True, "gif": slot}
            if cmd == "notify":
                self.session.call(lambda d: d.send_whatsapp_notification(
                    str(req.get("title", "WhatsApp")), str(req.get("message", ""))))
                return {"ok": True}
            if cmd == "datetime":
                self.session.call(lambda d: d.set_datetime())
                return {"ok": True}
            if cmd == "read":
                value = self.session.call(lambda d: d.read_numeric(int(req["reg"])))
                return {"ok": True, "reg": int(req["reg"]), "value": value}
            if cmd == "read_str":
                value = self.session.call(lambda d: d.read_string(int(req["reg"])))
                return {"ok": True, "reg": int(req["reg"]), "value": value}
            if cmd == "pause":
                self.session.set_paused(True)
                return {"ok": True, "paused": True}
            if cmd == "resume":
                self.session.set_paused(False)
                return {"ok": True, "paused": False}
            if cmd == "quit":
                self._stop.set()
                return {"ok": True, "shutting_down": True}
            return {"ok": False, "error": f"unknown command: {cmd}"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> int:
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        server.listen(8)

        threads = [threading.Thread(target=self._status_loop, daemon=True)]
        if self.monitor_notifications:
            threads.append(threading.Thread(target=self._notification_loop, daemon=True))
        for t in threads:
            t.start()
        threading.Thread(target=self._serve, args=(server,), daemon=True).start()

        log.info("listening on %s", self.socket_path)
        try:
            while not self._stop.is_set():
                time.sleep(0.5)
        finally:
            self._stop.set()
            server.close()
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
            self.session.close()
        log.info("daemon stopped")
        return 0


def _unescape(value: str) -> str:
    return (value.replace('\\"', '"').replace("\\n", "\n")
            .replace("\\t", "\t").replace("\\\\", "\\"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Minitela background daemon")
    parser.add_argument("--port", help="Serial port (default: first /dev/ttyACM*)")
    parser.add_argument("--interval", type=float, default=5.0, help="Status sync interval seconds")
    parser.add_argument("--socket", default=default_socket_path(), help="Control socket path")
    parser.add_argument("--notify-match", default=os.environ.get("MINITELA_NOTIFY_MATCH", "whatsapp"),
                        help="Substring to match notifications (empty = all)")
    parser.add_argument("--no-notifications", action="store_true", help="Disable D-Bus notification mirroring")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    daemon = Daemon(args.port, args.interval, args.socket, args.notify_match,
                    not args.no_notifications)

    def _sig(_signum, _frame):
        daemon._stop.set()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
