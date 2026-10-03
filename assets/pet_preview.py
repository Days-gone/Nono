"""Preview: render a PNG as pixel art in the terminal (half-block truecolor).

Prototype for the pixel-pet idea -- not wired into the app. Run:

    uv run python assets/pet_preview.py [--width 27] [image.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

RESET = "\x1b[0m"


def load_sprite(path: Path, width: int) -> Image.Image:
    """Load a PNG, strip the white background, pixelate to ``width`` cells."""
    image = Image.open(path).convert("RGB")
    # The background is white: flood-fill it from the borders with a marker
    # color, so white pixels enclosed by the body outline survive.
    marker = (255, 0, 255)
    seeds = [(0, 0), (image.width - 1, 0), (0, image.height - 1), (image.width - 1, image.height - 1)]
    for seed in seeds:
        ImageDraw.floodfill(image, seed, marker, thresh=40)
    # Marker pixels become transparent: diff against a solid marker image is
    # zero exactly there.
    diff = ImageChops.difference(image, Image.new("RGB", image.size, marker))
    image = image.convert("RGBA")
    image.putalpha(diff.convert("L").point(lambda v: 255 if v else 0))

    # Crop to the sprite, then nearest-neighbor downscale for crisp pixels.
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.NEAREST)


def render(image: Image.Image) -> str:
    """Map vertical pixel pairs to half-block cells with 24-bit color."""
    lines = []
    pixels = image.load()
    for y in range(0, image.height, 2):
        line = []
        for x in range(image.width):
            top = pixels[x, y]
            bottom = pixels[x, y + 1] if y + 1 < image.height else (0, 0, 0, 0)
            if top[3] and bottom[3]:
                line.append(f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m\x1b[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m▀")
            elif top[3]:
                line.append(f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m▀")
            elif bottom[3]:
                line.append(f"\x1b[38;2;{bottom[0]};{bottom[1]};{bottom[2]}m▄")
            else:
                line.append(" ")
        lines.append("".join(line) + RESET)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=str(Path(__file__).parent / "nono.png"))
    parser.add_argument("--width", type=int, default=27, help="sprite width in terminal cells")
    args = parser.parse_args()
    # Block glyphs and ANSI art need UTF-8 regardless of the console codepage.
    sys.stdout.reconfigure(encoding="utf-8")
    print(render(load_sprite(Path(args.image), args.width)))


if __name__ == "__main__":
    main()
