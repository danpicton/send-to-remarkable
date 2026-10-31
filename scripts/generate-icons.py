"""Rasterize the code-native app icon; uses Pillow supplied by WeasyPrint."""

from pathlib import Path

from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "app/static"
for size, name in [(192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")]:
    image = Image.new("RGB", (1024, 1024), "#304f40")
    draw = ImageDraw.Draw(image)
    ink = "#f6f4ee"
    draw.rounded_rectangle((296, 224, 728, 800), radius=28, outline=ink, width=36)
    for y, end in [(360, 636), (448, 636), (536, 540)]:
        draw.line((388, y, end, y), fill=ink, width=36)
    draw.line([(552, 652), (600, 700), (688, 592)], fill=ink, width=36, joint="curve")
    image.resize((size, size), Image.Resampling.LANCZOS).save(root / name)
