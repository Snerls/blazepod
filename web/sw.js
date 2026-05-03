// Network-first for HTML/JS (so updates ship immediately), cache fallback for offline use.
// Bumping CACHE name invalidates every previously-cached file.
const CACHE = 'blazepod-v3';
const ASSETS = [
  './',
  './index.html',
  './styles.css',
  './manifest.json',
  './js/ui.js',
  './js/pod.js',
  './js/manager.js',
  './js/drill.js',
  './js/protocol.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network-first for everything: always try the network, fall back to cache when offline.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (e.request.method !== 'GET') return;
  e.respondWith((async () => {
    try {
      const resp = await fetch(e.request);
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, clone)).catch(() => {});
      }
      return resp;
    } catch {
      const hit = await caches.match(e.request);
      if (hit) return hit;
      const fallback = await caches.match('./index.html');
      if (fallback && e.request.mode === 'navigate') return fallback;
      throw new Error('offline and not cached');
    }
  })());
});
