const CACHE_NAME = 'rms-static-v1';
const STATIC_ASSETS = [
  '/',
  '/static/sales/css/lead_detail.css',
  '/static/sales/css/data_explorer.css',
  'https://cdn.tailwindcss.com',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Cache-first for static assets
  if (STATIC_ASSETS.includes(url.pathname) || url.hostname === 'cdn.tailwindcss.com') {
    event.respondWith(
      caches.match(event.request).then(response => {
        return response || fetch(event.request);
      })
    );
    return;
  }

  // Network-first with fallback to cache for others
  event.respondWith(
    fetch(event.request)
      .then(response => {
        const clonedResponse = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, clonedResponse);
        });
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
