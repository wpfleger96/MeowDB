const CACHE_NAME = 'meowdb-v3';

const APP_SHELL = [
  '/',
  '/static/css/base.css',
  '/static/css/layout.css',
  '/static/css/components.css',
  '/static/css/views.css',
  '/static/css/desktop.css',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/audio.js',
  '/static/js/waveform.js',
  '/static/js/views/play.js',
  '/static/js/views/library.js',
  '/static/js/views/ingest.js',
  '/static/js/views/stats.js',
  '/static/js/views/photos.js',
  '/static/vendor/alpine.min.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Audio endpoints: network-first so previously-played meows replay offline
  if (
    url.pathname.startsWith('/api/audio/') ||
    url.pathname.match(/^\/api\/ingest\/[^/]+\/audio\//)
  ) {
    event.respondWith(networkFirstWithCache(request));
    return;
  }

  // All other API calls: network-only (always want fresh data)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets: network-first so deploys take effect immediately
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(networkFirstWithCache(request));
    return;
  }

  // SPA shell and all other HTML routes: network-first
  event.respondWith(networkFirstWithCache(request));
});

async function networkFirstWithCache(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw new Error('Network unavailable and no cached audio');
  }
}

async function cacheFirstWithNetwork(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const cache = await caches.open(CACHE_NAME);
  const response = await fetch(request);
  if (response.ok) {
    cache.put(request, response.clone());
  }
  return response;
}
