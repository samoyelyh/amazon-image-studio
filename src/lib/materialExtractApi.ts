import { authenticatedFetch } from './authApi'
import type { ServerJob } from './jobsApi'

export interface MaterialPoint { x: number; y: number }
export interface MaterialStroke {
  tool: 'select' | 'erase'
  size: number
  points: MaterialPoint[]
}
export interface MaterialSelectionBounds { x: number; y: number; width: number; height: number }

export interface MaterialExtractResponse {
  job: ServerJob
  source_asset_id: string
  roi_asset_id: string
  background_color: string
}

export function submitMaterialExtract(input: {
  source_asset_id: string
  target_description: string
  selection_bounds: MaterialSelectionBounds
  brush_strokes: MaterialStroke[]
  idempotency_key: string
}) {
  return authenticatedFetch<MaterialExtractResponse>('/material-extract/jobs', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

