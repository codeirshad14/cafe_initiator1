/* The Mr Cafe app's service worker (served at /sw.js by pwa/views.py).

   A restaurant POS must always show what is true right now, so:
   - pages, orders, bills, HTMX updates: always from the server, never stored
     (no old order on screen, no other login's page on a shared device);
     with no internet a page shows /offline/ instead of the browser's error
   - our CSS, JS and icons (/static/, /app/): from the device at once, refreshed
     in the background, so screens open fast
   - forms (POST) and other sites: not touched at all
*/
const CACHE = "mrcafe-{{ version }}";
const OFFLINE_URL = {{ offline_url|safe }};
const FILE_PREFIXES = {{ file_prefixes|safe }};
const PRECACHE = {{ precache|safe }};

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE)
      .then(function (cache) { return cache.addAll(PRECACHE); })
      .then(function () { return self.skipWaiting(); })
  );
});

// a new version: delete the old caches and look after the open pages at once
self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (names) {
        return Promise.all(names.filter(function (name) {
          return name.startsWith("mrcafe-") && name !== CACHE;
        }).map(function (name) { return caches.delete(name); }));
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // a page: the server's, or the offline page when there is no internet
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match(OFFLINE_URL).then(function (page) {
          return page || new Response("You are offline.", { status: 503, headers: { "Content-Type": "text/plain" } });
        });
      })
    );
    return;
  }

  // our CSS / JS / icons: the stored copy now, a fresh one for next time
  if (FILE_PREFIXES.some(function (prefix) { return url.pathname.startsWith(prefix); })) {
    event.respondWith(
      caches.open(CACHE).then(function (cache) {
        return cache.match(request).then(function (stored) {
          const fresh = fetch(request).then(function (response) {
            if (response.ok) cache.put(request, response.clone());
            return response;
          });
          if (stored) {
            fresh.catch(function () {});  // offline: the stored copy is enough
            return stored;
          }
          return fresh;
        });
      })
    );
  }
  // anything else (HTMX parts, live checks, photos): straight to the server
});
