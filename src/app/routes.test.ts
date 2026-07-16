import { describe, expect, it } from 'vitest'
import { appRoutes, navigationSections } from './routes'
import { normalizeBrowserBasename } from './runtimeConfig'

describe('application routes', () => {
  it('keeps all public route paths unique', () => {
    const paths = Object.values(appRoutes)
    expect(new Set(paths).size).toBe(paths.length)
  })

  it('registers the three workspaces as independent routes', () => {
    const workspacePaths = navigationSections
      .find((section) => section.label === '图片工作台')
      ?.items.map((item) => item.path)
    expect(workspacePaths).toEqual([
      '/workspaces/listing',
      '/workspaces/batch-tryon',
      '/workspaces/aplus',
    ])
  })

  it('normalizes browser-router base paths for multiuser deployments', () => {
    expect(normalizeBrowserBasename('./')).toBe('/')
    expect(normalizeBrowserBasename('/amazon-image-studio/')).toBe('/amazon-image-studio')
  })
})
