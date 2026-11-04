Mr Cafe print helper
====================

Prints bills and KOTs straight to your POS printer, without the print window.
Set it up once on each computer that prints (counter, kitchen).

1. Install your POS printer's Windows driver and print a Windows test page.
2. Install Python 3 from https://www.python.org/downloads/ (tick "Add python.exe to PATH").
3. Double-click "Start Mr Cafe print.bat". A black window opens and lists your
   printers. Keep it open (you may minimise it).
4. In Mr Cafe, open Setup > Printers: choose the bill printer and the KOT
   printer (the same one if you have one printer), then press Test.

Start it with Windows (optional): press Win+R, type shell:startup, press Enter,
and put a shortcut to "Start Mr Cafe print.bat" in the folder that opens.

Not working?
- "Print helper is not running" in Mr Cafe: the black window was closed. Start it again.
- The browser asks to "access devices on your local network": click Allow.
- Nothing prints: check the printer name, the paper and that the printer is on.
