const CACHE = 'remarkable-shell-v1';
const SHELL = ['/', '/app.js', '/preferences.js', '/styles.css', '/manifest.webmanifest',
  '/icon.svg', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const path of SHELL) {
      const response = await fetch(path, {cache: 'reload', credentials: 'same-origin', redirect: 'error'});
      if (!response.ok || response.redirected || response.headers.get('X-App-Shell') !== '1') {
        throw new Error('Application shell unavailable');
      }
      await cache.put(path, response);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('remarkable-shell-') && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate' && url.pathname === '/') {
    // Navigation is network-first. Never store a response carrying a shared query URL.
    event.respondWith(fetch(request).catch(async () => {
      const cached = await caches.match('/');
      if (cached) return cached;
      throw new Error('Offline shell unavailable');
    }));
    return;
  }
  if (url.search || !SHELL.includes(url.pathname) || url.pathname === '/') return;
  event.respondWith(caches.match(url.pathname).then(cached => cached || fetch(request)));
});
