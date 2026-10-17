#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Wagner Martins and minitela-re contributors
"""Generate the project's own tray icon.

This produces ``assets/minitela.png`` — a small, original "mini display"
glyph. It is deliberately drawn from scratch so the repository never ships
vendor artwork.

Usage:  python3 tools/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.pardir, "assets", "minitela.png")

SIZE = 64
ACCENT = (0, 180, 216, 255)   # cyan
SCREEN = (18, 22, 28, 255)    # near-black panel
HILIGHT = (120, 220, 255, 255)


def build() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Display body (rounded rectangle) with a bright outline.
    box = (6, 10, SIZE - 6, SIZE - 20)
    d.rounded_rectangle(box, radius=7, fill=SCREEN, outline=ACCENT, width=3)

    # A small "M"-ish content mark so it reads as a screen.
    d.line((20, 34, 26, 24), fill=HILIGHT, width=3)
    d.line((26, 24, 32, 34), fill=HILIGHT, width=3)
    d.line((32, 34, 38, 24), fill=HILIGHT, width=3)
    d.line((38, 24, 44, 34), fill=HILIGHT, width=3)

    # Stand.
    d.line((SIZE // 2, box[3], SIZE // 2, SIZE - 10), fill=ACCENT, width=3)
    d.line((20, SIZE - 9, SIZE - 20, SIZE - 9), fill=ACCENT, width=3)
    return img


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    build().save(OUT)
    print(f"wrote {os.path.normpath(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
