"""Tiles PNGs into one labelled sheet:  python3 tools/make_collage.py out.png cols width name=file.png [name=file.png ...]"""
import sys

from PIL import Image, ImageDraw, ImageFont

out, cols, width = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
items = [a.split("=", 1) for a in sys.argv[4:]]
tiles = []
for label, path in items:
    im = Image.open(path).convert("RGB")
    h = int(im.height * width / im.width)
    tiles.append((label, im.resize((width, h), Image.LANCZOS)))
rows = (len(tiles) + cols - 1) // cols
th = tiles[0][1].height
sheet = Image.new("RGB", (cols * width, rows * th), (30, 30, 30))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
except OSError:
    font = ImageFont.load_default()
draw = ImageDraw.Draw(sheet)
for i, (label, im) in enumerate(tiles):
    x, y = (i % cols) * width, (i // cols) * th
    sheet.paste(im, (x, y))
    draw.rectangle((x + 8, y + 8, x + 16 + 14 * len(label), y + 44), fill=(0, 0, 0))
    draw.text((x + 14, y + 10), label, fill=(255, 255, 255), font=font)
sheet.save(out, optimize=True)
