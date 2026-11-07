/* ==========================================================================
   printing.js — print bills and KOTs straight to the POS printer, with no
   print window. Loaded on every staff page.

   1. Print links    <a href="(print page)" data-print="bill" data-print-slip="(slip url)" data-print-name="Bill #12">
                     If this computer has a bill printer chosen (Printers page),
                     the click sends the slip to it. If not, the link opens the
                     print page as before (the browser's print window).
   2. Printers page  #printerSettings: choose the bill and KOT printer, test them.
   3. Same screen    on a phone or tablet, and in the installed app, print pages and
                     [data-same-window] pages (QR sheet, UPI customer screen) open in
                     the same screen, not a new window: their Back comes back here,
                     and nothing can close the app (partials/_go_back.html).

   The printing itself is done by the print helper on this computer
   (print_helper/mrcafe_print.py, at 127.0.0.1:17180); the server makes the
   slip (the printer's ESC/POS bytes). The chosen printers are kept in this
   browser, because each computer has its own printers.
   ========================================================================== */

(function () {
  const HELPER = "http://127.0.0.1:17180";
  const SAVED = "mrcafe-printers";  // localStorage: {"bill": "TVS RP 3160", "kot": "..."}

  function chosenPrinters() {
    try {
      return JSON.parse(localStorage.getItem(SAVED)) || {};
    } catch (e) {
      return {};
    }
  }

  function choosePrinter(kind, name) {
    const printers = chosenPrinters();
    printers[kind] = name;
    try {
      localStorage.setItem(SAVED, JSON.stringify(printers));
      return true;
    } catch (e) {
      return false;
    }
  }

  function tell(text, level) {
    document.body.dispatchEvent(new CustomEvent("showMessage", { detail: { text: text, level: level } }));
  }

  // a request to the helper that gives up after a few seconds (the helper is not running)
  function askHelper(path, options) {
    return fetch(HELPER + path, Object.assign({ signal: AbortSignal.timeout(4000) }, options)).then(
      function (response) {
        return response.json().then(function (answer) {
          if (!response.ok) throw new Error(answer.error || "The print helper said no.");
          return answer;
        });
      },
      function () {
        throw new Error("The print helper is not running on this computer.");
      }
    );
  }

  // fetch the slip from the server, hand it to the helper for that printer
  function printSlip(slipUrl, printer) {
    return fetch(slipUrl, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("Could not make the slip (error " + response.status + ").");
        return response.arrayBuffer();
      })
      .then(function (slip) {
        return askHelper("/print?printer=" + encodeURIComponent(printer), {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: slip,
        });
      });
  }

  /* ---------------------------------------------------- 1. print links */
  document.addEventListener("click", function (event) {
    const link = event.target.closest("[data-print-slip]");
    if (!link) return;
    const printer = chosenPrinters()[link.dataset.print];
    if (!printer) return;  // no printer chosen here: the print page opens as before
    event.preventDefault();
    if (link.classList.contains("is-printing")) return;  // one tap = one slip
    link.classList.add("is-printing");
    const name = link.dataset.printName || "Slip";
    printSlip(link.dataset.printSlip, printer).then(
      function () { tell(name + " sent to " + printer + ".", "success"); },
      function (error) {
        tell(error.message + " Opening the print window instead.", "warning");
        window.open(link.href, "_blank", "noopener");
      }
    ).finally(function () {
      link.classList.remove("is-printing");
    });
  });

  /* ------------------------------------- 3. same screen on phones / the app */
  const asApp = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const touchScreen = window.matchMedia("(pointer: coarse)").matches && window.matchMedia("(max-width: 1199.98px)").matches;
  if (asApp || touchScreen) {
    document.addEventListener("click", function (event) {
      const link = event.target.closest("a[data-print], a[data-same-window]");
      if (link && link.target) link.target = "_self";  // (a slip sent to the printer above opens nothing)
    });
  }

  /* --------------------------------------------------- 2. printers page */
  const settings = document.getElementById("printerSettings");
  if (!settings) return;

  const status = document.getElementById("helperStatus");
  const helperOff = document.getElementById("helperOff");
  const selects = Array.from(settings.querySelectorAll("[data-printer-for]"));

  function showStatus(text, level) {
    status.textContent = text;
    status.className = "status-badge status-" + level;
  }

  // the "Print window" option, the helper's printers, and the saved one even if it is gone
  function fillSelect(select, names, defaultName) {
    const saved = chosenPrinters()[select.dataset.printerFor] || "";
    select.length = 1;
    const all = names.slice();
    if (saved && all.indexOf(saved) === -1) all.push(saved);
    all.forEach(function (name) {
      const missing = names.indexOf(name) === -1;
      const label = name + (name === defaultName ? " (default)" : "") + (missing ? " (not found)" : "");
      select.add(new Option(label, name, false, name === saved));
    });
  }

  function checkHelper() {
    showStatus("Checking…", "muted");
    askHelper("/printers").then(
      function (answer) {
        showStatus("Print helper running", "success");
        helperOff.hidden = true;
        selects.forEach(function (select) { fillSelect(select, answer.printers, answer.default); });
      },
      function () {
        showStatus("Print helper not running", "warning");
        helperOff.hidden = false;
        selects.forEach(function (select) { fillSelect(select, [], ""); });
      }
    );
  }

  selects.forEach(function (select) {
    select.addEventListener("change", function () {
      const what = select.dataset.printerFor === "kot" ? "KOTs" : "Bills";
      if (!choosePrinter(select.dataset.printerFor, select.value)) {
        tell("This browser cannot save the choice (private window?).", "error");
      } else if (select.value) {
        tell(what + " now print on " + select.value + ".", "success");
      } else {
        tell(what + " now open the print window.", "info");
      }
    });
  });

  settings.addEventListener("click", function (event) {
    if (event.target.closest("[data-helper-check]")) checkHelper();
    const button = event.target.closest("[data-printer-test]");
    if (!button) return;
    const kind = button.dataset.printerTest;
    const printer = settings.querySelector('[data-printer-for="' + kind + '"]').value;
    if (!printer) {
      tell("Choose a printer first.", "warning");
      return;
    }
    const url = settings.dataset.testSlip + "?for=" + kind + "&printer=" + encodeURIComponent(printer);
    button.disabled = true;
    printSlip(url, printer).then(
      function () { tell("Test slip sent to " + printer + ".", "success"); },
      function (error) { tell(error.message, "error"); }
    ).finally(function () {
      button.disabled = false;
    });
  });

  checkHelper();
})();
