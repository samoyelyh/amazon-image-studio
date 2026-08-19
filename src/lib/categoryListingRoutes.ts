import type { ListingWorkflowSession } from './listingWorkflowApi'

export function canEnterCategoryOutput(session: Pick<ListingWorkflowSession, 'status' | 'listing_version_id'>) {
  return session.status === 'confirmed' && Boolean(session.listing_version_id)
}

export const categoryListingPath = (sessionId: string) => `/listing-workbench/${sessionId}`
export const categoryOutputPath = (sessionId: string) => `/listing-workbench/${sessionId}/select-output`
export const listingImagePath = (sessionId: string) => `/listing-image-workbench/${sessionId}`
export const attachmentImageWorkbenchPath = (sessionId: string) => `/attachment-image-workbench/${sessionId}`
export const categoryAPlusPath = (sessionId: string) => `/a-plus-workbench/${sessionId}`
