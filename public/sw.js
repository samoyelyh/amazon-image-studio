const CACHE_NAME = 'amazon-image-studio-v0.1.6'
const APP_SHELL = ['./', './index.html', './manifest.webmanifest', './pwa-icon.svg']
const CACHEABLE_DESTINATIONS = new Set(['font', 'image', 'manifest', 'script', 'style'])

function isPrivateApiRequest(url) {
  return url.pathname === '/api/v1'
    || url.pathname.startsWith('/api/v1/')
    || url.pathname === '/api-proxy'
    || url.pathname.startsWith('/api-proxy/')
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      ),
      self.clients.claim(),
    ]),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event

  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  // Authenticated API responses must always come from the network. Cache API
  // keys are URL-based and cannot safely isolate users or organizations.
  if (isPrivateApiRequest(url)) return

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put('./index.html', copy))
          return response
        })
        .catch(() => caches.match('./index.html')),
    )
    return
  }

  // Only immutable application assets use cache-first behavior. Other GET
  // requests (health checks, JSON, downloads, etc.) keep normal network rules.
  if (!CACHEABLE_DESTINATIONS.has(request.destination)) return

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached

      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
        }
        return response
      })
    }),
  )
})
