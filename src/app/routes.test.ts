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
      '/workspaces/listing/legacy',
      '/workspaces/listing/variations',
      '/workspaces/batch-tryon',
      '/workspaces/aplus',
      '/material-extract',
      '/workspaces/print-design',
    ])
  })

  it('keeps quick generation inside the existing Listing workspace hierarchy', () => {
    expect(appRoutes.listingQuick).toBe('/workspaces/listing/quick')
    expect(appRoutes.listingQuickProgress).toBe('/workspaces/listing/quick/:quickSessionId')
    expect(navigationSections.flatMap((section) => section.items).some((item) => item.path === appRoutes.listingQuick)).toBe(false)
  })

  it('keeps smart image variation under the existing Listing image project route', () => {
    expect(appRoutes.smartImageVariationHub).toBe('/workspaces/listing/variations')
    expect(appRoutes.smartImageVariation).toBe('/listing-image-workbench/:sessionId/variations')
    expect(navigationSections.flatMap((section) => section.items).some((item) => item.path === appRoutes.smartImageVariationHub)).toBe(true)
    expect(navigationSections.flatMap((section) => section.items).some((item) => item.path === appRoutes.smartImageVariation)).toBe(false)
  })

  it('keeps region replacement as a dedicated child workspace without a primary navigation item', () => {
    expect(appRoutes.batchTryOnRegionReplace).toBe('/workspaces/batch-tryon/region-replace/:itemId')
    expect(navigationSections.flatMap((section) => section.items).some((item) => item.path === appRoutes.batchTryOnRegionReplace)).toBe(false)
  })

  it('normalizes browser-router base paths for multiuser deployments', () => {
    expect(normalizeBrowserBasename('./')).toBe('/')
    expect(normalizeBrowserBasename('/amazon-image-studio/')).toBe('/amazon-image-studio')
  })

  it('registers projects as a shared multiuser center', () => {
    const projects = navigationSections.flatMap((section) => section.items)
      .find((item) => item.path === appRoutes.projects)
    expect(projects?.multiuserOnly).toBe(true)
  })
})
