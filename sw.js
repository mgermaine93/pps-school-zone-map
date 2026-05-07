const CACHE_NAME = 'pps-schools-v4';

const PRECACHE_FILES = [
  'data/addresses.bin',
  'data/schools.json',
];

// Pre-fetch data files during install so second+ loads are served from cache
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_FILES))
      .then(() => self.skipWaiting())
  );
});

// Clean up any previous cache versions on activation
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(k => k.startsWith('pps-schools-') && k !== CACHE_NAME)
          .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// Cache-first strategy for data files
self.addEventListener('fetch', event => {
  if (!PRECACHE_FILES.some(f => event.request.url.includes(f))) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(cache =>
      cache.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          cache.put(event.request, response.clone());
          return response;
        });
      })
    )
  );
});
