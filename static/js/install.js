/* ==========================================================================
   install.js — the installable app (pwa/views.py). Plain JavaScript.
   Served at /app/install.js (pwa/files.py), so it never waits for collectstatic.

   1. Starts the service worker (/sw.js): the offline page, fast CSS / JS.
   2. Every <button data-install-app hidden> always shows in the browser (not
      inside the installed app itself: there it is already the app). A tap:
      - the browser has its install prompt ready (Chrome, Edge): that prompt
      - otherwise #installHelp (pwa/_install_help.html) with the steps for this
        browser, and "already installed" when the browser says so, with how to
        install it fresh over the old one
   ========================================================================== */

(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});  // http:// (not localhost): no app
    });
  }

  const ua = navigator.userAgent;
  const runningAsApp = window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: window-controls-overlay)").matches || navigator.standalone === true;
  const help = document.getElementById("installHelp");
  let prompt = null;  // the browser's install prompt, kept until a button is tapped

  function buttons() {
    return document.querySelectorAll("[data-install-app]");
  }

  // which steps to show: the browser this page is open in
  function browser() {
    const iPhoneOrIPad = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    if (iPhoneOrIPad) return "ios";
    if (/samsungbrowser/i.test(ua)) return "samsung";
    if (/firefox|fxios/i.test(ua)) return "firefox";
    if (/edg\//i.test(ua)) return "edge";
    if (/android/i.test(ua) && /chrome/i.test(ua)) return "android";
    if (/chrome|chromium|crios/i.test(ua)) return "chrome";
    if (/macintosh/i.test(ua) && /safari/i.test(ua)) return "mac";
    return "other";
  }

  // Chrome / Edge can tell whether this app is already installed here (manifest: related_applications)
  function alreadyInstalled() {
    if (!navigator.getInstalledRelatedApps) return Promise.resolve(false);
    return navigator.getInstalledRelatedApps()
      .then(function (apps) { return apps.length > 0; })
      .catch(function () { return false; });
  }

  function openHelp() {
    if (!help || typeof help.showModal !== "function") return;
    const steps = browser();
    help.querySelectorAll("[data-install-for]").forEach(function (box) {
      box.hidden = box.dataset.installFor !== steps;
    });
    alreadyInstalled().then(function (installed) {
      const done = help.querySelector("[data-install-done]");
      if (done) done.hidden = !installed;
      const again = help.querySelector(".install-help-again");
      if (again) again.open = installed;  // installed: the "install it fresh" steps open at once
      if (!help.open) help.showModal();
    });
  }

  if (runningAsApp) return;  // inside the installed app: nothing to install

  buttons().forEach(function (button) { button.hidden = false; });

  // Chrome / Edge: the browser's own install prompt is ready
  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();  // our button asks, not the browser's own banner
    prompt = event;
  });

  window.addEventListener("appinstalled", function () {
    prompt = null;
    document.body.dispatchEvent(new CustomEvent("showMessage", {
      detail: { text: "App installed. Open it from your home screen or desktop.", level: "success" },
    }));
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-install-app]")) return;
    if (prompt) {
      const asking = prompt;
      prompt = null;  // a prompt works once; the next tap shows the steps
      asking.prompt();
      return;
    }
    openHelp();
  });
})();
