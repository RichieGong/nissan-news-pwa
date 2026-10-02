// Service worker — makes the app installable and works offline.
// Bump CACHE to "nissan-news-v2" etc. when you want to force refresh everything.
const CACHE = "nissan-news-v1";

const ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./script.js",
  "./news.js",
  "./manifest.json",
  "./icon.svg",
  "./icons/icon-48.png",
  "./icons/icon-96.png",
  "./icons/icon-144.png",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = e.request.url;

  // Only handle same-origin GET requests (article links go to Google News,
  // which must always hit the network).
  if (e.request.method !== "GET" || !url.startsWith(self.location.origin)) return;

  // news.js is special: try the network FIRST so fresh data shows up after a
  // redeploy, and only fall back to the cache when offline.
  if (url.includes("/news.js")) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Everything else: cache first, network fallback.
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});