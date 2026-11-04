"""
Printers: print bills and KOTs straight to the POS printer (no print window).

  printers               Cafe profile > Printers: this computer's bill and KOT printer   ADMIN MANAGER
  printer_test_slip      a short test slip (printer bytes)                                same
  print_helper_download  the print helper for this computer (a .zip)                      same

The choice is kept in the browser of each computer (localStorage, see
static/js/printing.js), because each computer has its own printers: the admin
logs in once on each counter / kitchen computer and chooses there; it then
works for everyone on that computer. The print helper
(print_helper/mrcafe_print.py) runs on that computer and does the printing.
"""

import io
import zipfile

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from . import roles
from .decorators import role_required
from .escpos import Slip
from .utils import get_user_restaurant

PRINT_ROLES = roles.COMPANY
HELPER_DIR = settings.BASE_DIR / "print_helper"
WHAT_PRINTS = {"bill": "bills", "kot": "KOTs (kitchen order tickets)"}


@role_required(*PRINT_ROLES)
def printers(request):
    return render(request, "core/printers.html", {"restaurant": get_user_restaurant(request)})


@role_required(*PRINT_ROLES)
def printer_test_slip(request):
    """?for=bill|kot&printer=NAME: a short slip that shows the printer works and its paper width."""
    what = WHAT_PRINTS.get(request.GET.get("for"), "bills and KOTs")
    slip = Slip()
    slip.text(get_user_restaurant(request).name, center=True, bold=True, big=True)
    slip.text("PRINTER TEST", center=True, bold=True)
    slip.rule()
    slip.text(f"This printer prints the {what}.")
    slip.row("Printer", request.GET.get("printer", "")[:30])
    slip.row("Time", f"{timezone.localtime():%d-%m-%Y %I:%M %p}")
    slip.rule()
    slip.text("The line below should fill the paper width:")
    slip.add("1234567890" * 4 + "12345678")
    slip.rule("=")
    slip.text("Ready to print.", center=True, bold=True)
    slip.cut()
    return HttpResponse(slip.to_bytes(), content_type="application/octet-stream")


START_BAT = """@echo off
title Mr Cafe print helper
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py mrcafe_print.py --site {site}
) else (
    python mrcafe_print.py --site {site}
)
echo.
echo The print helper stopped. Is Python installed? See README.txt.
pause
"""


@role_required(*PRINT_ROLES)
def print_helper_download(request):
    """A .zip with the helper, its README and a start file already set to this website's address."""
    site = f"{request.scheme}://{request.get_host()}"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.write(HELPER_DIR / "mrcafe_print.py", "mrcafe_print.py")
        zipped.write(HELPER_DIR / "README.txt", "README.txt")
        zipped.writestr("Start Mr Cafe print.bat", START_BAT.format(site=site).replace("\n", "\r\n"))
    response = HttpResponse(archive.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = 'attachment; filename="mrcafe-print-helper.zip"'
    return response
