"""
ESC/POS: the command language of thermal POS printers (Epson, TVS, Rugtek,
Xprinter, ...). A Slip collects the lines of a bill or KOT and turns them into
the bytes such a printer prints as they are ("raw"): fast, sharp, and the paper
is cut at the end. The print helper on the counter computer (print_helper/)
sends these bytes to the printer chosen on the Printers page.

3-inch (80 mm) paper fits 48 characters a line; big text (double width) 24;
pictures (logo, UPI QR code) up to 576 dots wide.
The printer has no rupee sign, so "₹" prints as "Rs.".

    slip = Slip()
    slip.text("Spice Garden", center=True, bold=True)
    slip.row("Subtotal", "250.00")
    slip.cut()
    data = slip.to_bytes()
"""

import textwrap

from PIL import Image, ImageOps

WIDTH = 48  # characters a line on 80 mm paper
DOTS = 576  # dots a line on 80 mm paper (8 dots a mm)
IMAGE_BAND = 128  # picture rows sent at a time (small printers have small memory)

ESC, GS = b"\x1b", b"\x1d"
RESET = ESC + b"@"
LEFT, CENTER = ESC + b"a\x00", ESC + b"a\x01"
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
BIG_ON, BIG_OFF = GS + b"!\x11", GS + b"!\x00"  # double width and height
FEED_AND_CUT = ESC + b"d\x04" + GS + b"V\x01"   # 4 empty lines, then cut


def printable(text):
    """The text as the printer will print it (measure this, not the original)."""
    return str(text).replace("₹", "Rs.")


def wrap(text, width):
    """Lines of at most `width` characters (an empty text is one empty line)."""
    return textwrap.wrap(printable(text), width) or [""]


class Slip:
    def __init__(self, width=WIDTH):
        self.width = width
        self.parts = [RESET]

    def add(self, line, center=False, bold=False, big=False):
        """One line as it is (already fits the width)."""
        self.parts += [CENTER if center else LEFT, BOLD_ON if bold else b"", BIG_ON if big else b""]
        self.parts.append(encode(line) + b"\n")
        self.parts += [BIG_OFF if big else b"", BOLD_OFF if bold else b""]

    def text(self, text, center=False, bold=False, big=False):
        """A text, wrapped onto as many lines as it needs."""
        width = self.width // 2 if big else self.width
        for line in wrap(text, width):
            self.add(line, center=center, bold=bold, big=big)

    def row(self, left, right, bold=False, big=False):
        """`left` at the left edge, `right` at the right edge of the same line."""
        width = self.width // 2 if big else self.width
        left, right = printable(left), printable(right)
        room = width - len(right) - 1
        lines = wrap(left, room) if room > 0 else [left]
        for line in lines[:-1]:
            self.add(line, bold=bold, big=big)
        self.add(lines[-1].ljust(width - len(right)) + right, bold=bold, big=big)

    def columns(self, cells, widths, bold=False):
        """A table row: the first cell (a dish name) wraps, the others are right-aligned numbers."""
        first, rest = cells[0], [printable(cell) for cell in cells[1:]]
        names = wrap(first, widths[0] - 1)
        numbers = "".join(cell.rjust(width) for cell, width in zip(rest, widths[1:]))
        self.add(names[0].ljust(widths[0]) + numbers, bold=bold)
        for name in names[1:]:
            self.add(name, bold=bold)

    def rule(self, char="-"):
        self.add(char * self.width)

    def blank(self):
        self.add("")

    def image(self, picture, width, sharp=False):
        """A picture (the logo, a UPI QR code), black and white, centred, at most
        `width` dots wide. sharp=True for a QR code: pure black / white, no shading
        dots, so phones can scan it. A picture that cannot be read is left out."""
        try:
            with picture.open("rb") as file, Image.open(file) as opened:
                img = ImageOps.exif_transpose(opened).convert("RGBA")
        except (OSError, ValueError):
            return
        white = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(white, img).convert("L")  # a see-through background prints white
        if img.width > width:
            resample = Image.Resampling.NEAREST if sharp else Image.Resampling.LANCZOS
            img = img.resize((width, max(1, round(img.height * width / img.width))), resample)
        # whole bytes a row: pad the right edge with white
        padded = Image.new("L", ((img.width + 7) // 8 * 8, img.height), 255)
        padded.paste(img, (0, 0))
        if sharp:
            bw = padded.point(lambda p: 255 if p > 128 else 0).convert("1", dither=Image.Dither.NONE)
        else:
            bw = padded.convert("1")  # shading becomes a dot pattern
        dots = bytes(byte ^ 0xFF for byte in bw.tobytes())  # the printer's 1 = black
        row_bytes = bw.width // 8
        self.parts.append(CENTER)
        for top in range(0, bw.height, IMAGE_BAND):
            rows = min(IMAGE_BAND, bw.height - top)
            size = bytes([row_bytes % 256, row_bytes // 256, rows % 256, rows // 256])
            self.parts.append(GS + b"v0\x00" + size + dots[top * row_bytes:(top + rows) * row_bytes])
        self.parts.append(LEFT)

    def cut(self):
        self.parts.append(FEED_AND_CUT)

    def to_bytes(self):
        return b"".join(self.parts)


def encode(text):
    """Text in the printer's own characters (code page 437); unknown ones print as "?"."""
    return printable(text).encode("cp437", "replace")
