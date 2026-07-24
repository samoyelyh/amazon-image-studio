import { authenticatedFetch } from './authApi'

export type ListingTransferTargetMode = 'create_project' | 'existing_project'

export interface SendListingOutputInput {
  target_mode: ListingTransferTargetMode
  project_name?: string
  project_description?: string
  target_project_id?: string
  replace_existing_template?: boolean
  idempotency_key: string
}

export interface SendListingOutputResult {
  batch_project_id: string
  batch_project_name: string
  model_asset_id: string
  listing_output_id: string
  listing_project_id: string | null
  redirect_path: string
  template_replaced: boolean
  created_project: boolean
  replayed: boolean
  warnings: string[]
}

export function sendListingOutputToBatchTryOn(outputId: string, input: SendListingOutputInput) {
  return authenticatedFetch<SendListingOutputResult>(`/listing/generated-outputs/${outputId}/send-to-batch-tryon`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
