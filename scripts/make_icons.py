#!/usr/bin/env python3
"""Draw HANA's mark and write the application icons.

Kept as code rather than as binaries someone edited once in a graphics program:
the icon has to move with the theme, and a PNG in the repository is a dead end
the next time the palette changes. Running this regenerates every size from the
same description.

No dependencies. PNG is a handful of zlib-compressed scanlines and ICO is a
directory of images, both short enough to write directly — and adding Pillow to
a project that otherwise installs nothing would be a poor trade for two file
formats.

    python scripts/make_icons.py
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "icons"

#: Rendered once at this size, then box-filtered down to each target. Drawing
#: each size separately would give the small ones their own rounding errors.
MASTER = 1024

# -- palette (mirrors styles/theme.css) -------------------------------------
BG_TOP = (0x28, 0x22, 0x48)
BG_BOTTOM = (0x14, 0x12, 0x1F)
RING = (0x3D, 0x34, 0x63)
TURQUOISE = (0x4F, 0xD1, 0xC5)
TURQUOISE_PALE = (0x7E, 0xE8, 0xDD)
VIOLET = (0xA7, 0x8B, 0xFA)


# ---------------------------------------------------------------------------
# canvas


class Canvas:
    """Straight-alpha RGBA canvas with analytic coverage."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.pixels = bytearray(size * size * 4)

    def blend(self, x: int, y: int, colour: tuple[int, int, int], alpha: float) -> None:
        if alpha <= 0:
            return
        alpha = min(1.0, alpha)
        index = (y * self.size + x) * 4
        pixels = self.pixels
        for channel in range(3):
            existing = pixels[index + channel]
            pixels[index + channel] = int(
                existing + (colour[channel] - existing) * alpha + 0.5
            )
        existing_alpha = pixels[index + 3] / 255
        pixels[index + 3] = int((alpha + existing_alpha * (1 - alpha)) * 255 + 0.5)

    def fill(self, bbox, distance, colour, feather: float = 1.0) -> None:
        """Paint where ``distance(x, y) <= 0``, softening across ``feather`` px.

        One function covers every shape here: a rounded rectangle, a disc and a
        capsule differ only in their distance field, and coverage from a signed
        distance antialiases far better than counting subsamples.
        """
        left, top, right, bottom = bbox
        for y in range(max(0, top), min(self.size, bottom)):
            for x in range(max(0, left), min(self.size, right)):
                d = distance(x + 0.5, y + 0.5)
                if d <= -feather:
                    self.blend(x, y, colour, 1.0)
                elif d < feather:
                    self.blend(x, y, colour, (feather - d) / (2 * feather))

    def downsample(self, target: int) -> bytes:
        """Box-filter to ``target`` square. Premultiplies so edges stay clean."""
        factor = self.size // target
        source = self.pixels
        out = bytearray(target * target * 4)

        for y in range(target):
            for x in range(target):
                r = g = b = a = 0
                for dy in range(factor):
                    row = (y * factor + dy) * self.size
                    for dx in range(factor):
                        index = (row + x * factor + dx) * 4
                        pixel_alpha = source[index + 3]
                        r += source[index] * pixel_alpha
                        g += source[index + 1] * pixel_alpha
                        b += source[index + 2] * pixel_alpha
                        a += pixel_alpha
                index = (y * target + x) * 4
                if a:
                    out[index] = r // a
                    out[index + 1] = g // a
                    out[index + 2] = b // a
                out[index + 3] = a // (factor * factor)
        return bytes(out)


# ---------------------------------------------------------------------------
# distance fields


def rounded_rect(size: float, radius: float):
    def distance(x: float, y: float) -> float:
        dx = abs(x - size / 2) - (size / 2 - radius)
        dy = abs(y - size / 2) - (size / 2 - radius)
        outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
        return outside + min(max(dx, dy), 0.0) - radius

    return distance


def disc(cx: float, cy: float, r: float):
    return lambda x, y: math.hypot(x - cx, y - cy) - r


def annulus(cx: float, cy: float, r: float, width: float):
    return lambda x, y: abs(math.hypot(x - cx, y - cy) - r) - width / 2


def capsule(x1: float, y1: float, x2: float, y2: float, width: float):
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy

    def distance(x: float, y: float) -> float:
        t = 0.0
        if length_squared:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_squared))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)) - width / 2

    return distance


# ---------------------------------------------------------------------------
# the mark


def draw_mark() -> Canvas:
    """A hub with three satellites: a knowledge graph, at its smallest.

    The same shape the app has always used, repainted. It survives 16 pixels,
    which is the only real constraint on an application icon — anything with a
    letter in it becomes a smudge in the taskbar.
    """
    size = MASTER
    canvas = Canvas(size)

    # Background: a rounded square with a vertical gradient, painted as bands.
    # Enough of them that the steps are invisible after downsampling.
    shape = rounded_rect(size, size * 0.19)
    bands = 64
    for band in range(bands):
        t = band / (bands - 1)
        colour = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
        top = int(size * band / bands)
        bottom = int(size * (band + 1) / bands) + 1
        canvas.fill((0, top, size, bottom), shape, colour, feather=1.0)

    centre = size / 2
    orbit = size * 0.26
    hub_radius = size * 0.105
    satellite_radius = size * 0.078

    canvas.fill(
        (0, 0, size, size),
        annulus(centre, centre, size * 0.365, size * 0.018),
        RING,
        feather=1.2,
    )

    # Satellites at the top, lower-left and lower-right: the arrangement reads
    # as a hub even when the whole icon is sixteen pixels across.
    satellites = []
    for index, degrees in enumerate((-90, 150, 30)):
        radians = math.radians(degrees)
        satellites.append(
            (
                centre + orbit * math.cos(radians),
                centre + orbit * math.sin(radians),
                (TURQUOISE_PALE, VIOLET, TURQUOISE)[index],
            )
        )

    for x, y, _ in satellites:
        canvas.fill(
            (0, 0, size, size),
            capsule(centre, centre, x, y, size * 0.036),
            TURQUOISE,
            feather=1.2,
        )

    canvas.fill((0, 0, size, size), disc(centre, centre, hub_radius), TURQUOISE, 1.2)
    for x, y, colour in satellites:
        canvas.fill((0, 0, size, size), disc(x, y, satellite_radius), colour, 1.2)

    return canvas


# ---------------------------------------------------------------------------
# file formats


def write_png(path: Path, rgba: bytes, size: int) -> None:
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter type 0: none
        raw.extend(rgba[y * size * 4 : (y + 1) * size * 4])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def bmp_entry(rgba: bytes, size: int) -> bytes:
    """A DIB for the ICO container: BGRA, bottom-up, with an AND mask.

    Windows reads PNG entries too, but only reliably at 256 — below that some
    shell surfaces still expect a DIB, and an icon that vanishes from the
    taskbar is a strange bug to chase later.
    """
    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0
    )
    body = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            index = (y * size + x) * 4
            body += bytes(
                (rgba[index + 2], rgba[index + 1], rgba[index], rgba[index + 3])
            )
    # Fully transparent AND mask; the alpha channel above does the real work.
    mask_stride = ((size + 31) // 32) * 4
    return header + bytes(body) + bytes(mask_stride * size)


def write_ico(path: Path, images: dict[int, bytes]) -> None:
    entries, payloads, offset = [], [], 6 + 16 * len(images)

    for size in sorted(images):
        rgba = images[size]
        data = write_png_bytes(rgba, size) if size >= 128 else bmp_entry(rgba, size)
        entries.append(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payloads.append(data)
        offset += len(data)

    path.write_bytes(
        struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(payloads)
    )


def write_png_bytes(rgba: bytes, size: int) -> bytes:
    scratch = ICON_DIR / ".tmp.png"
    write_png(scratch, rgba, size)
    data = scratch.read_bytes()
    scratch.unlink()
    return data


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    print("==> Dibujando la marca")
    canvas = draw_mark()

    sizes = (16, 32, 48, 64, 128, 256)
    rendered = {}
    for size in sizes:
        print(f"    {size}x{size}")
        rendered[size] = canvas.downsample(size)

    write_png(ICON_DIR / "32x32.png", rendered[32], 32)
    write_png(ICON_DIR / "128x128.png", rendered[128], 128)
    write_png(ICON_DIR / "128x128@2x.png", rendered[256], 256)
    write_png(ICON_DIR / "icon.png", rendered[256], 256)
    write_ico(ICON_DIR / "icon.ico", rendered)

    for name in ("32x32.png", "128x128.png", "128x128@2x.png", "icon.png", "icon.ico"):
        size_kb = (ICON_DIR / name).stat().st_size / 1024
        print(f"    {name:<18} {size_kb:6.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
