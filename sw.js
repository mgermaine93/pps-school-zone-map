const CACHE_NAME = 'pps-schools-v1';

// Activate immediately — don't wait for existing tabs to close
self.addEventListener('install', event => {
  event.waitUntil(self.skipWaiting());
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

// Cache-first strategy for the data file only
self.addEventListener('fetch', event => {
  if (!event.request.url.includes('addresses_slim.json')) return;

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
