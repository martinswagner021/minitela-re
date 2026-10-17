#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""Tiny client for the Minitela daemon control socket.

The daemon (``minitela_daemon.py``) listens on a UNIX socket and speaks
newline-delimited JSON.  This client is used by the tray app and the web UI so
only one process ever owns the serial port.
"""

from __future__ import annotations

import json
import os
import socket


def default_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(runtime, "minitela.sock")


class MinitelaClient:
    def __init__(self, path: str | None = None, timeout: float = 8.0):
        self.path = path or default_socket_path()
        self.timeout = timeout

    def request(self, cmd: str, **kwargs) -> dict:
        payload = {"cmd": cmd, **kwargs}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.path)
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            return json.loads(buf.decode("utf-8").splitlines()[0])
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # Convenience wrappers -------------------------------------------------

    def ping(self):
        return self.request("ping")

    def status(self, show: bool = False):
        return self.request("status", show=show)

    def set_brightness(self, value: int):
        return self.request("set_brightness", value=int(value))

    def set_page(self, page: int):
        return self.request("set_page", page=int(page))

    def gif(self, slot: int):
        return self.request("gif", slot=int(slot))

    def notify(self, title: str, message: str):
        return self.request("notify", title=title, message=message)

    def datetime(self):
        return self.request("datetime")

    def read(self, reg: int):
        return self.request("read", reg=int(reg))

    def read_str(self, reg: int):
        return self.request("read_str", reg=int(reg))

    def pause(self):
        return self.request("pause")

    def resume(self):
        return self.request("resume")

    def quit(self):
        return self.request("quit")


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    client = MinitelaClient()
    if not argv:
        print(json.dumps(client.ping(), indent=2))
    else:
        cmd = argv[0]
        params = {}
        for item in argv[1:]:
            if "=" in item:
                k, v = item.split("=", 1)
                params[k] = v
        print(json.dumps(client.request(cmd, **params), indent=2))
