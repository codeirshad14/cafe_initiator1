/* ==========================================================================
   install.js — the installable app (pwa/views.py). Plain JavaScript.

   1. Starts the service worker (/sw.js): the offline page, fast CSS / JS.
   2. Every <button data-install-app hidden> shows when this device can install:
      - Chrome / Edge (Android, Windows, Mac, Linux): the browser's own
        install prompt (the "beforeinstallprompt" event)
      - iPhone / iPad / Safari on a Mac: no prompt there, so the button opens
        #installHelp (pwa/_install_help.html) with the steps
      Already installed, or opened as the app: the buttons stay hidden.
   ========================================================================== */

(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});  // http:// (not localhost): no app
    });
  }

  const ua = navigator.userAgent;
  const runningAsApp = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const iPhoneOrIPad = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
  const macSafari = !iPhoneOrIPad && /macintosh/i.test(ua) && /safari/i.test(ua) && !/chrome|chromium|crios|edg|firefox|fxios/i.test(ua);
  const help = document.getElementById("installHelp");
  let prompt = null;  // the browser's install prompt, kept until a button is tapped

  function buttons() {
    return document.querySelectorAll("[data-install-app]");
  }

  function showButtons(show) {
    buttons().forEach(function (button) { button.hidden = !show; });
  }

  function openHelp(device) {
    if (!help || typeof help.showModal !== "function") return;
    help.querySelectorAll("[data-install-for]").forEach(function (steps) {
      steps.hidden = steps.dataset.installFor !== device;
    });
    help.showModal();
  }

  if (runningAsApp) return;  // already the app: nothing to install

  // Chrome / Edge: the page can be installed
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();  // our button asks, not the browser's own banner
    prompt = event;
    showButtons(true);
  });

  window.addEventListener("appinstalled", function () {
    prompt = null;
    showButtons(false);
    document.body.dispatchEvent(new CustomEvent("showMessage", {
      detail: { text: "App installed. Open it from your home screen or desktop.", level: "success" },
    }));
  });

  // Safari: no prompt, the steps instead
  if ((iPhoneOrIPad || macSafari) && help) showButtons(true);

  document.addEventListener("click", function (event) {
    const button = event.target.closest("[data-install-app]");
    if (!button) return;
    if (prompt) {
      const asking = prompt;
      prompt = null;
      asking.prompt();
      asking.userChoice.then(function (choice) {
        // a prompt works once: after "Cancel" the button comes back on a later visit
        if (choice.outcome !== "accepted") showButtons(false);
      });
      return;
    }
    openHelp(iPhoneOrIPad ? "ios" : macSafari ? "mac" : "other");
  });
})();
