"""
python manage.py make_app_icons

Draws the app's icons into static/img/app/ from the Mr Cafe mark (the same as
static/img/admin-logo.svg: white QR corners on the brand red). Run it again only
when the mark or the red changes; the PNG files are kept in git.

    icon-192.png, icon-512.png   rounded tile (Android, Windows, Mac, Linux)
    maskable-512.png             full red square, the mark in the middle 60 %
                                 (Android cuts it to a circle, squircle, ...)
    apple-touch-icon.png         180 px full square (the iPhone rounds it itself)
    favicon-32.png               the browser tab
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image, ImageDraw

RED = (218, 56, 49, 255)
WHITE = (255, 255, 255, 255)
DRAW_AT = 4  # draw 4x bigger, then shrink: smooth edges


def mark(draw, left, top, size):
    """The mark on a 64-unit grid (admin-logo.svg), drawn into the box at left, top, size."""
    unit = size / 64

    def box(x, y, w, h):
        return [left + x * unit, top + y * unit, left + (x + w) * unit, top + (y + h) * unit]

    # three open squares (the QR corners): an SVG stroke of 5 sits half outside the 14-unit
    # square, so draw the outer edge 2.5 further out with the full width inside it
    for x, y in ((14, 14), (36, 14), (14, 36)):
        draw.rounded_rectangle(box(x - 2.5, y - 2.5, 19, 19), radius=5.5 * unit, outline=WHITE,
                               width=max(1, round(5 * unit)))
    for x, y in ((37, 37), (45, 37), (37, 45), (45, 45)):  # four dots
        draw.rounded_rectangle(box(x, y, 5, 5), radius=1 * unit, fill=WHITE)


def icon(size, rounded=True, mark_share=1.0):
    """A square icon `size` px wide. rounded: the red tile has round corners on a
    see-through background; mark_share: how much of the tile the mark's 64 grid fills."""
    big = size * DRAW_AT
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=big * 16 / 64, fill=RED)
    else:
        draw.rectangle([0, 0, big, big], fill=RED)
    inner = big * mark_share
    mark(draw, (big - inner) / 2, (big - inner) / 2, inner)
    return image.resize((size, size), Image.Resampling.LANCZOS)


class Command(BaseCommand):
    help = "Draw the installable app's icons into static/img/app/."

    def handle(self, *args, **options):
        folder = Path(settings.BASE_DIR) / "static" / "img" / "app"
        folder.mkdir(parents=True, exist_ok=True)
        icons = {
            "icon-192.png": icon(192),
            "icon-512.png": icon(512),
            "maskable-512.png": icon(512, rounded=False, mark_share=0.62),
            "apple-touch-icon.png": icon(180, rounded=False, mark_share=0.86),
            "favicon-32.png": icon(32),
        }
        for name, image in icons.items():
            image.save(folder / name, "PNG", optimize=True)
            self.stdout.write(f"{name}  {image.width} x {image.height}")
        self.stdout.write(self.style.SUCCESS(f"Icons saved in {folder}"))
