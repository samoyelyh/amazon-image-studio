import { describe, expect, it } from 'vitest'
import { attachmentImageWorkbenchPath, canEnterCategoryOutput, categoryAPlusPath, categoryListingPath, categoryOutputPath, listingImagePath } from './categoryListingRoutes'

describe('category listing route guard', () => {
  it('blocks unconfirmed sessions and requires a saved listing version', () => {
    expect(canEnterCategoryOutput({ status: 'generated', listing_version_id: null })).toBe(false)
    expect(canEnterCategoryOutput({ status: 'confirmed', listing_version_id: null })).toBe(false)
    expect(canEnterCategoryOutput({ status: 'confirmed', listing_version_id: 'version-1' })).toBe(true)
  })

  it('keeps each business stage on an independent route', () => {
    expect(categoryListingPath('s1')).toBe('/listing-workbench/s1')
    expect(categoryOutputPath('s1')).toBe('/listing-workbench/s1/select-output')
    expect(listingImagePath('s1')).toBe('/listing-image-workbench/s1')
    expect(attachmentImageWorkbenchPath('s1')).toBe('/attachment-image-workbench/s1')
    expect(categoryAPlusPath('s1')).toBe('/a-plus-workbench/s1')
  })
})
