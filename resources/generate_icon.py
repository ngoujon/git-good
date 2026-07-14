"""Draws a placeholder app icon (a small commit-graph glyph, echoing the
app's centerpiece feature) and converts it to icon.icns via macOS `iconutil`.

Run manually with: python resources/generate_icon.py
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
MASTER_SIZE = 1024

BG_COLOR = (45, 164, 78)  # matches the app's accent green
LANE_BLUE = (42, 120, 214)
LANE_GREEN = (0, 131, 0)
LANE_VIOLET = (74, 58, 167)
WHITE = (255, 255, 255)

ICONSET_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def _rounded_square(size: int, radius_ratio: float, color) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=color)
    return img


def draw_master_icon() -> Image.Image:
    size = MASTER_SIZE
    img = _rounded_square(size, 0.22, BG_COLOR)
    draw = ImageDraw.Draw(img)

    # A small three-lane commit graph: two lanes fork off the main line and
    # merge back in, echoing the app's commit-graph view.
    cx_main = size * 0.32
    cx_fork = size * 0.60
    top_y = size * 0.22
    mid_y = size * 0.50
    bot_y = size * 0.78
    line_w = int(size * 0.045)
    dot_r = int(size * 0.075)

    def curve(x0, y0, x1, y1, color):
        # Stamp overlapping filled circles along a smoothstep path -- avoids
        # the thin aliasing seams PIL's line `joint="curve"` leaves behind.
        steps = 80
        r = line_w / 2
        for i in range(steps + 1):
            t = i / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * (3 * t * t - 2 * t * t * t)  # smoothstep
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    # Main line, straight through.
    draw.line([(cx_main, top_y), (cx_main, bot_y)], fill=WHITE, width=line_w)

    # Fork out to the second lane and back in.
    curve(cx_main, top_y, cx_fork, mid_y, WHITE)
    curve(cx_fork, mid_y, cx_main, bot_y, WHITE)

    for (x, y), color in (
        ((cx_main, top_y), LANE_BLUE),
        ((cx_fork, mid_y), LANE_VIOLET),
        ((cx_main, mid_y), LANE_GREEN),
        ((cx_main, bot_y), LANE_BLUE),
    ):
        draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=color, outline=WHITE, width=line_w // 2)

    return img


def build_iconset(master: Image.Image) -> Path:
    iconset_dir = HERE / "icon.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir()

    for size in ICONSET_SIZES:
        resized = master.resize((size, size), Image.LANCZOS)
        resized.save(iconset_dir / f"icon_{size}x{size}.png")
        if size <= 512:
            resized2x = master.resize((size * 2, size * 2), Image.LANCZOS)
            resized2x.save(iconset_dir / f"icon_{size}x{size}@2x.png")

    return iconset_dir


def main() -> None:
    master = draw_master_icon()
    master.save(HERE / "icon_preview.png")
    iconset_dir = build_iconset(master)

    icns_path = HERE / "icon.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
    shutil.rmtree(iconset_dir)
    print(f"Wrote {icns_path}")


if __name__ == "__main__":
    main()
