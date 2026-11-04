"""
Mr Cafe print helper: prints bills and KOTs straight to the POS printer,
without the browser's print window. Runs on the counter / kitchen computer
(Windows) and needs only Python 3.9+, nothing to install with pip.

    python mrcafe_print.py --site https://your-mr-cafe-address

The web app (static/js/printing.js) talks to it on this computer only:
    GET  http://127.0.0.1:17180/printers           -> {"printers": [...], "default": "..."}
    POST http://127.0.0.1:17180/print?printer=NAME  body: the slip bytes (ESC/POS)

Only pages of the --site address(es) may use it, so other websites cannot
print on your printer. Without --site, the app on this computer
(http://127.0.0.1:8000, http://localhost:8000) is allowed.
"""

import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 17180
LOCAL_SITES = ["http://127.0.0.1:8000", "http://localhost:8000"]
MAX_SLIP_SIZE = 1024 * 1024  # a bill is a few KB; anything bigger is a mistake


# ------------------------------------------------------- Windows printers
# winspool.drv is the Windows print spooler. "RAW" sends the slip bytes to the
# printer unchanged: the POS printer itself reads the ESC/POS commands in them.

class PRINTER_INFO_4(ctypes.Structure):
    _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR),
                ("Attributes", wintypes.DWORD)]


class DOC_INFO_1(ctypes.Structure):
    _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR)]


PRINTER_ENUM_LOCAL, PRINTER_ENUM_CONNECTIONS = 2, 4


def spooler():
    if sys.platform != "win32":
        raise OSError("Direct printing works on Windows only.")
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    DWORDS = ctypes.POINTER(wintypes.DWORD)
    winspool.EnumPrintersW.argtypes = [wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, DWORDS, DWORDS]
    winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, DWORDS]
    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
    winspool.StartPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD, DWORDS]
    winspool.EndPagePrinter.argtypes = [wintypes.HANDLE]
    winspool.EndDocPrinter.argtypes = [wintypes.HANDLE]
    winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    return winspool


def windows_error():
    return ctypes.WinError(ctypes.get_last_error())


def printer_names():
    """Every printer of this computer (its own and shared ones it is connected to)."""
    winspool = spooler()
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    winspool.EnumPrintersW(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        return []
    buffer = ctypes.create_string_buffer(needed.value)
    if not winspool.EnumPrintersW(flags, None, 4, buffer, needed, ctypes.byref(needed), ctypes.byref(count)):
        raise windows_error()
    infos = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_4))
    return sorted(infos[i].pPrinterName for i in range(count.value))


def default_printer():
    winspool = spooler()
    size = wintypes.DWORD()
    winspool.GetDefaultPrinterW(None, ctypes.byref(size))
    if not size.value:
        return ""
    name = ctypes.create_unicode_buffer(size.value)
    winspool.GetDefaultPrinterW(name, ctypes.byref(size))
    return name.value


def print_raw(printer, data):
    """Send the slip bytes to the printer as they are."""
    winspool = spooler()
    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(printer, ctypes.byref(handle), None):
        raise OSError(f'Printer "{printer}" was not found on this computer.')
    try:
        doc = DOC_INFO_1("Mr Cafe slip", None, "RAW")
        if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
            raise windows_error()
        try:
            winspool.StartPagePrinter(handle)
            written = wintypes.DWORD()
            if not winspool.WritePrinter(handle, data, len(data), ctypes.byref(written)):
                raise windows_error()
            winspool.EndPagePrinter(handle)
        finally:
            winspool.EndDocPrinter(handle)
    finally:
        winspool.ClosePrinter(handle)


# ------------------------------------------------------------ web server

class Handler(BaseHTTPRequestHandler):
    allowed_sites = LOCAL_SITES

    def origin_allowed(self):
        origin = self.headers.get("Origin")
        return origin is None or origin in self.allowed_sites  # no Origin: a program on this computer

    def send_json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin and self.origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """The browser asks first whether the page may send to us."""
        if not self.origin_allowed():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")  # a website calling this computer
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if not self.origin_allowed():
            return self.send_json(403, {"error": "This website may not use the printers."})
        path = urlparse(self.path).path
        if path == "/":
            return self.send_json(200, {"app": "Mr Cafe print helper", "port": PORT})
        if path == "/printers":
            try:
                return self.send_json(200, {"printers": printer_names(), "default": default_printer()})
            except OSError as error:
                return self.send_json(500, {"error": str(error)})
        self.send_json(404, {"error": "Not found."})

    def do_POST(self):
        if not self.origin_allowed():
            return self.send_json(403, {"error": "This website may not use the printers."})
        url = urlparse(self.path)
        if url.path != "/print":
            return self.send_json(404, {"error": "Not found."})
        printer = parse_qs(url.query).get("printer", [""])[0]
        size = int(self.headers.get("Content-Length") or 0)
        if not printer:
            return self.send_json(400, {"error": "Which printer? (printer=...)"})
        if not 0 < size <= MAX_SLIP_SIZE:
            return self.send_json(400, {"error": "Nothing to print."})
        data = self.rfile.read(size)
        try:
            print_raw(printer, data)
        except OSError as error:
            print(f"  could not print on {printer}: {error}")
            return self.send_json(500, {"error": str(error)})
        print(f"  printed {size} bytes on {printer}")
        self.send_json(200, {"ok": True, "printer": printer})

    def log_message(self, format, *args):
        pass  # one line per print (above) is enough


def main():
    parser = argparse.ArgumentParser(description="Mr Cafe print helper")
    parser.add_argument("--site", action="append", default=[],
                        help="address of your Mr Cafe, e.g. https://app.example.com (can be given more than once)")
    args = parser.parse_args()
    Handler.allowed_sites = [site.rstrip("/") for site in args.site] or LOCAL_SITES

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Mr Cafe print helper is running. Keep this window open (you may minimise it).")
    print("Allowed:", ", ".join(Handler.allowed_sites))
    try:
        for name in printer_names():
            print("  printer:", name)
    except OSError as error:
        print("  ", error)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
