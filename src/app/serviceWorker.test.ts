// @ts-expect-error Vitest runs this file in Node; the browser build intentionally omits Node typings.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'


const source = readFileSync(new URL('../../public/sw.js', import.meta.url), 'utf8')


describe('production service worker cache policy', () => {
  it('bypasses authenticated and proxied API requests before cache lookup', () => {
    expect(source).toContain("url.pathname.startsWith('/api/v1/')")
    expect(source).toContain("url.pathname.startsWith('/api-proxy/')")

    const privateApiGuard = source.indexOf('if (isPrivateApiRequest(url)) return')
    const cacheLookup = source.indexOf('caches.match(request)')

    expect(privateApiGuard).toBeGreaterThan(-1)
    expect(cacheLookup).toBeGreaterThan(privateApiGuard)
  })

  it('limits cache-first behavior to static application assets', () => {
    expect(source).toContain("new Set(['font', 'image', 'manifest', 'script', 'style'])")
    expect(source).toContain('if (!CACHEABLE_DESTINATIONS.has(request.destination)) return')
  })

  it('bumps the cache version so deployed clients remove unsafe legacy entries', () => {
    expect(source).toContain("const CACHE_NAME = 'amazon-image-studio-v0.1.6'")
    expect(source).toContain('keys.filter((key) => key !== CACHE_NAME)')
  })
})
