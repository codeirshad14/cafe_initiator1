"""
A report as a PDF (reportlab): the letterhead on top, the report's name and
period, then each table with a dark header row, striped rows, numbers right
aligned and the totals in bold. A4, turned sideways for wide tables. Every page
ends with its number and when it was made.
"""

from io import BytesIO

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from reports.catalog.common import NUMERIC

from .letterhead import generated_text, letterhead, period_text, shown

INK = colors.HexColor("#1d1a17")
INK_SOFT = colors.HexColor("#5b544d")
LINE = colors.HexColor("#dcd4ca")
STRIPE = colors.HexColor("#f6f3ef")
HEADER = colors.HexColor("#2b2622")
WIDE = 7  # tables with more columns than this go on a sideways page

STYLES = {
    "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=INK),
    "trade": ParagraphStyle("trade", fontName="Helvetica", fontSize=9.5, leading=12, textColor=INK_SOFT),
    "line": ParagraphStyle("line", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK_SOFT),
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=2),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK_SOFT),
    "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=INK, spaceBefore=8),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10, textColor=INK),
    "num": ParagraphStyle("num", fontName="Helvetica", fontSize=8, leading=10, textColor=INK, alignment=TA_RIGHT),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
    "head_num": ParagraphStyle("head_num", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white,
                               alignment=TA_RIGHT),
    "total": ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK),
    "total_num": ParagraphStyle("total_num", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=INK,
                                alignment=TA_RIGHT),
    "empty": ParagraphStyle("empty", fontName="Helvetica-Oblique", fontSize=8.5, leading=11, textColor=INK_SOFT),
}


def escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def column_widths(section, room):
    """Share the page width by how long each column's text runs (a long address gets more)."""
    weights = []
    for index, (label, kind) in enumerate(section["columns"]):
        longest = max([len(label)] + [len(shown(row[index], kind)) for row in section["rows"][:200]])
        weights.append(min(max(longest, 5), 34))
    total = sum(weights)
    return [room * weight / total for weight in weights]


def section_table(section, room):
    kinds = [kind for _, kind in section["columns"]]
    numeric = [kind in NUMERIC for kind in kinds]
    data = [[Paragraph(escape(label), STYLES["head_num" if numeric[i] else "head"])
             for i, (label, _) in enumerate(section["columns"])]]
    for row in section["rows"]:
        data.append([Paragraph(escape(shown(value, kinds[i])), STYLES["num" if numeric[i] else "cell"])
                     for i, value in enumerate(row)])
    if section["totals"]:
        data.append([Paragraph(escape(shown(value, kinds[i]) if value != "" else ""), STYLES["total_num" if numeric[i] else "total"])
                     for i, value in enumerate(section["totals"])])
    table = Table(data, colWidths=column_widths(section, room), repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, len(section["rows"])), [colors.white, STRIPE]),  # the stripes
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
    ]
    if section["totals"]:
        style += [("LINEABOVE", (0, -1), (-1, -1), 1, INK), ("BACKGROUND", (0, -1), (-1, -1), colors.white)]
    table.setStyle(TableStyle(style))
    return table


def pdf_response(slug, title, location, start, end, sections, search=""):
    widest = max((len(section["columns"]) for section in sections), default=0)
    page = landscape(A4) if widest > WIDE else A4
    buffer = BytesIO()
    made = generated_text()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(INK_SOFT)
        canvas.drawString(doc.leftMargin, 10 * mm, f"{title} · {period_text(start, end)} · made {made}")
        canvas.drawRightString(page[0] - doc.rightMargin, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buffer, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=18 * mm, title=title, author=location.restaurant.bill_name)
    room = page[0] - doc.leftMargin - doc.rightMargin

    head = letterhead(location)
    story = [Paragraph(escape(head["name"]), STYLES["name"])]
    if head["trade_name"]:
        story.append(Paragraph(escape(head["trade_name"]), STYLES["trade"]))
    story += [Paragraph(escape(line), STYLES["line"]) for line in head["lines"]]
    story += [Spacer(1, 4), HRFlowable(width="100%", thickness=1.2, color=INK), Spacer(1, 6),
              Paragraph(escape(title), STYLES["title"])]
    meta = [f"Period: {period_text(start, end)}"]
    if head["location"]:
        meta.append(f"Location: {head['location']}")
    if search:
        meta.append(f"Search: {search}")
    meta += ["Amounts in Rs.", f"Generated: {made}"]
    story += [Paragraph(escape("   ·   ".join(meta)), STYLES["meta"]), Spacer(1, 8)]

    for section in sections:
        if section["title"]:
            story.append(Paragraph(escape(section["title"]), STYLES["section"]))
            story.append(Spacer(1, 4))
        if section["rows"]:
            story.append(section_table(section, room))
        else:
            story.append(Paragraph("Nothing in this period.", STYLES["empty"]))
        story.append(Spacer(1, 10))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{slug}_{start}_{end}.pdf"'
    return response
