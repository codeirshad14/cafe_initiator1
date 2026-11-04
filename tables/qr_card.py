"""
The printable QR card ("QR + label" on Tables & QR): a small standee card like the
QR cards at shop counters, about A6 / postcard size (620 x 880 px), ready to print.

    ┌──────────────────────┐
    │  SPICE GARDEN        │  red band: the cafe's name and what the card is for
    │  Our menu            │
    ├──────────────────────┤
    │   ┌─ ┌──────────┐ ─┐ │  the QR code in a white frame with red corners
    │      │  ▄▄  ▄▄  │     │
    │   └─ └──────────┘ ─┘ │
    │   Scan me for Menu   │  the line guests read (MENU_QRS / TABLE_CARD "label")
    │  Point your camera…  │
    │      [ Table T1 ]    │  a table's name ("No app needed" on the menu cards)
    │  Powered by Mr Cafe  │
    └──────────────────────┘
"""

from io import BytesIO

import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 620, 880
RED, RED_SOFT = (218, 56, 49), (253, 238, 237)
INK, INK_2, INK_3 = (29, 26, 23), (91, 84, 77), (138, 130, 121)
LINE, PAGE = (235, 230, 223), (247, 245, 242)

# a dining table's card (the menu QR codes' words are in qr.MENU_QRS)
TABLE_CARD = {"band": "Dine-in menu", "label": "Scan me to Order", "help": "Order from your table, no waiting"}

# a bold font on Linux (the server) and Windows; Pillow's own font when neither is there
FONTS = {
    True: ["DejaVuSans-Bold.ttf", "arialbd.ttf", "segoeuib.ttf"],
    False: ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"],
}


def font(size, bold=False):
    for name in FONTS[bold]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def fitting_font(draw, text, size, max_width, bold=False):
    """The font at `size`, made smaller until `text` fits in max_width (a long cafe name)."""
    while size > 14:
        chosen = font(size, bold)
        if draw.textlength(text, font=chosen) <= max_width:
            return chosen
        size -= 2
    return font(size, bold)


def centred(draw, y, text, chosen, fill):
    width = draw.textlength(text, font=chosen)
    draw.text(((WIDTH - width) / 2, y), text, font=chosen, fill=fill)


def qr_image(text, size):
    """The QR code at whole-pixel modules, as close to `size` as they allow (sharp when printed)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    qr.add_data(text)
    qr.make(fit=True)
    qr.box_size = max(1, size // qr.modules_count)
    return qr.make_image(fill_color="black", back_color="white").get_image().convert("RGB")


def corner_marks(draw, box, length=34, width=7):
    """Red L-shaped marks at the frame's four corners."""
    left, top, right, bottom = box
    for x, y, dx, dy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
        draw.line([(x, y + dy * length), (x, y), (x + dx * length, y)], fill=RED, width=width, joint="curve")


def qr_card_png(text, cafe_name, band, label, help_text, table_name=""):
    """The printable card for the QR code of `text`, as PNG bytes."""
    card = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(card)

    # 1. the red band: the cafe's name, and what the card is for
    draw.rectangle([0, 0, WIDTH, 150], fill=RED)
    centred(draw, 38, cafe_name.upper(), fitting_font(draw, cafe_name.upper(), 40, WIDTH - 80, bold=True), "white")
    centred(draw, 96, band, font(24), (255, 228, 226))

    # 2. the QR code in its frame, with red corner marks
    frame = (130, 190, 490, 550)
    draw.rounded_rectangle(frame, radius=22, fill="white", outline=LINE, width=3)
    code = qr_image(text, 300)
    card.paste(code, ((WIDTH - code.width) // 2, 370 - code.height // 2))
    corner_marks(draw, (frame[0] - 14, frame[1] - 14, frame[2] + 14, frame[3] + 14))

    # 3. the words guests read
    centred(draw, 600, label, fitting_font(draw, label, 46, WIDTH - 60, bold=True), INK)
    centred(draw, 666, help_text, fitting_font(draw, help_text, 22, WIDTH - 60), INK_2)

    # 4. a table's name in a soft red pill; on the menu cards a quiet "No app needed"
    if table_name:
        words, chip, colours = f"Table {table_name}", font(26, bold=True), (RED_SOFT, RED)
    else:
        words, chip, colours = "No app needed", font(22), (PAGE, INK_2)
    chip_width = draw.textlength(words, font=chip) + 48
    left = (WIDTH - chip_width) / 2
    draw.rounded_rectangle([left, 714, left + chip_width, 764], radius=25, fill=colours[0])
    centred(draw, 739 - chip.size * 0.55, words, chip, colours[1])

    # 5. the foot
    draw.rectangle([0, HEIGHT - 64, WIDTH, HEIGHT], fill=PAGE)
    centred(draw, HEIGHT - 44, f"Powered by {settings.BRAND_NAME}", font(18), INK_3)

    buffer = BytesIO()
    card.save(buffer, "PNG", dpi=(150, 150))  # 620 x 880 px at 150 dpi: about 10.5 x 15 cm
    return buffer.getvalue()
