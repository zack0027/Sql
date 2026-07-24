#!/usr/bin/env python3
"""Generate the application icons.

Written with the standard library alone (zlib + struct) so building JARVIS never
requires an image toolchain. Run it after changing the mark:

    python scripts/generate_icons.py

The mark is a knowledge-graph motif: a bright central node with three satellites
joined by edges, on the same dark surface the UI uses.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parents[1] / "apps" / "desktop" / "src-tauri" / "icons"

BACKGROUND = (11, 15, 20, 255)     # --surface-base
PANEL = (22, 32, 43, 255)          # --surface-raised
ACCENT = (59, 163, 255, 255)       # --accent
EDGE = (43, 59, 76, 255)           # --border-strong

Pixel = tuple[int, int, int, int]


def blend(base: Pixel, layer: Pixel, alpha: float) -> Pixel:
    alpha = max(0.0, min(1.0, alpha))
    return (
        round(base[0] + (layer[0] - base[0]) * alpha),
        round(base[1] + (layer[1] - base[1]) * alpha),
        round(base[2] + (layer[2] - base[2]) * alpha),
        255,
    )


class Canvas:
    def __init__(self, size: int, fill: Pixel) -> None:
        self.size = size
        self.pixels: list[list[Pixel]] = [[fill] * size for _ in range(size)]

    def disc(self, cx: float, cy: float, radius: float, colour: Pixel) -> None:
        """Draw an anti-aliased filled circle."""
        for y in range(self.size):
            for x in range(self.size):
                distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                coverage = max(0.0, min(1.0, radius + 0.5 - distance))
                if coverage > 0:
                    self.pixels[y][x] = blend(self.pixels[y][x], colour, coverage)

    def ring(self, cx: float, cy: float, radius: float, width: float, colour: Pixel) -> None:
        for y in range(self.size):
            for x in range(self.size):
                distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                coverage = max(0.0, min(1.0, width / 2 + 0.5 - abs(distance - radius)))
                if coverage > 0:
                    self.pixels[y][x] = blend(self.pixels[y][x], colour, coverage)

    def line(self, x0: float, y0: float, x1: float, y1: float, width: float, colour: Pixel) -> None:
        """Anti-aliased segment via distance-to-segment coverage."""
        dx, dy = x1 - x0, y1 - y0
        length_squared = dx * dx + dy * dy
        for y in range(self.size):
            for x in range(self.size):
                px, py = x + 0.5, y + 0.5
                t = 0.0 if length_squared == 0 else ((px - x0) * dx + (py - y0) * dy) / length_squared
                t = max(0.0, min(1.0, t))
                distance = math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))
                coverage = max(0.0, min(1.0, width / 2 + 0.5 - distance))
                if coverage > 0:
                    self.pixels[y][x] = blend(self.pixels[y][x], colour, coverage)

    def to_png(self) -> bytes:
        raw = bytearray()
        for row in self.pixels:
            raw.append(0)  # filter type 0
            for pixel in row:
                raw.extend(pixel)

        def chunk(tag: bytes, payload: bytes) -> bytes:
            body = tag + payload
            return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

        header = struct.pack(">IIBBBBB", self.size, self.size, 8, 6, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


def render(size: int) -> Canvas:
    canvas = Canvas(size, BACKGROUND)
    centre = size / 2
    unit = size / 32.0

    # Rounded plate so the mark reads on light and dark taskbars alike.
    canvas.disc(centre, centre, 15 * unit, PANEL)
    canvas.ring(centre, centre, 14.2 * unit, 1.1 * unit, EDGE)

    satellites = [
        (centre + 8.2 * unit * math.cos(math.radians(angle)),
         centre + 8.2 * unit * math.sin(math.radians(angle)))
        for angle in (-90, 30, 150)
    ]

    for x, y in satellites:
        canvas.line(centre, centre, x, y, 1.3 * unit, EDGE)
    for x, y in satellites:
        canvas.disc(x, y, 2.6 * unit, ACCENT)
    canvas.disc(centre, centre, 3.6 * unit, ACCENT)

    return canvas


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    """Wrap PNG images in an ICO container (PNG-in-ICO, supported since Vista)."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, payload = b"", b""

    for size, data in pngs:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)

    return header + entries + payload


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    sizes = [32, 128, 256]
    rendered = {size: render(size).to_png() for size in sizes}

    for name, size in [
        ("32x32.png", 32),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
        ("icon.png", 256),
    ]:
        (ICON_DIR / name).write_bytes(rendered[size])
        written.append(name)

    (ICON_DIR / "icon.ico").write_bytes(
        build_ico([(32, rendered[32]), (128, rendered[128]), (256, rendered[256])])
    )
    written.append("icon.ico")

    print(f"Escrito en {ICON_DIR}:")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
