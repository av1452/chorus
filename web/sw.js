// Offline cache for the app shell. Bump VERSION when shipping changes.
const VERSION = 'chorus-v5';
const SHELL = ['./', 'index.html', 'styles.css', 'manifest.webmanifest', 'icons/icon.svg',
  'src/app.js', 'src/store.js', 'src/usb.js', 'src/protocol.js', 'src/models.js'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Network first so updates show up, cache as the offline fallback.
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET' || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(fetch(e.request)
    .then((res) => {
      const copy = res.clone();
      caches.open(VERSION).then((c) => c.put(e.request, copy));
      return res;
    })
    .catch(() => caches.match(e.request)));
});
