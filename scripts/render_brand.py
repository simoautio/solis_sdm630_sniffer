"""Render the integration's original geometric vector icon using only stdlib."""

import struct
import zlib
from pathlib import Path

SIZE = 256
DESTINATION = Path(__file__).parents[1] / "custom_components/solis_sdm630_sniffer/brand"
POINTS = [(44, 146), (80, 146), (104, 90), (138, 184), (162, 126), (212, 126)]


def segment_distance(x, y, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)))
    return ((x - a[0] - t * dx) ** 2 + (y - a[1] - t * dy) ** 2) ** 0.5


def color(x, y):
    if (x - 128) ** 2 + (y - 128) ** 2 > 120**2:
        return (0, 0, 0, 0)
    if (x - 181) ** 2 + (y - 72) ** 2 <= 15**2:
        return (255, 184, 64, 255)
    if (
        min(
            segment_distance(x, y, a, b)
            for a, b in zip(POINTS, POINTS[1:], strict=False)
        )
        <= 7
    ):
        return (53, 222, 210, 255)
    return (18, 38, 58, 255)


def chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data))
    )


if __name__ == "__main__":
    DESTINATION.mkdir(parents=True, exist_ok=True)
    rows = bytearray()
    for y in range(SIZE):
        rows.append(0)
        for x in range(SIZE):
            samples = [
                color(x + dx, y + dy) for dx in (0.25, 0.75) for dy in (0.25, 0.75)
            ]
            rows.extend(
                round(sum(sample[c] for sample in samples) / 4) for c in range(4)
            )
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    (DESTINATION / "icon.png").write_bytes(png)
    (DESTINATION / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">\n'
        '  <circle cx="128" cy="128" r="120" fill="#12263a"/>\n'
        '  <circle cx="181" cy="72" r="15" fill="#ffb840"/>\n'
        '  <polyline points="44,146 80,146 104,90 138,184 162,126 212,126" '
        'fill="none" stroke="#35ded2" stroke-width="14" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n</svg>\n'
    )
