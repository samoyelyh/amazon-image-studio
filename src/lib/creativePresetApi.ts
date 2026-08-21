import { authenticatedFetch } from './authApi'

export interface VisualPreset {
  id: string
  code: string
  name: string
  short_description: string
  category_scope: string[]
  recommended_modules: string[]
  recommended_model_tags: string[]
  tags: string[]
  current_version_id: string
  current_version_number: number
  sort_order: number
  is_active: boolean
  is_default: boolean
  prompt_template: string | null
}

export interface ThemePreset {
  id: string
  code: string
  name: string
  short_description: string
  tags: string[]
  current_version_id: string
  current_version_number: number
  sort_order: number
  is_active: boolean
  prompt_template: string | null
}

export interface AIModelReference {
  id: string
  reference_role: string
  asset_id: string
  source_job_id: string | null
  sort_order: number
}

export interface AIModelIdentity {
  id: string
  version_number: number
  status: string
  identity_prompt_snapshot: string
  identity_asset_id: string | null
  identity_job_id: string | null
  reference_batch_id: string | null
  confirmed_at: string | null
  published_at: string | null
  references: AIModelReference[]
}

export interface AIModelPreset {
  id: string
  code: string
  name: string
  display_name: string
  gender_presentation: string
  age_range: string
  body_type: string
  short_description: string
  recommended_visual_presets: string[]
  recommended_modules: string[]
  tags: string[]
  cover_asset_id: string | null
  current_identity_version_id: string | null
  status: string
  sort_order: number
  is_active: boolean
  is_published: boolean
  source_type: string
  owner_user_id: string | null
  generation_parameters: Record<string, unknown>
  identity_prompt: string | null
  generation_prompt: string | null
  negative_constraints: string | null
  current_identity: AIModelIdentity | null
}

export interface ModelSelection {
  product_slot: number
  source: string
  model: AIModelPreset
  identity_version_id: string
}

export interface AttachmentCreativeContext {
  visual_preset: VisualPreset
  theme_preset: ThemePreset | null
  model_selection_mode: 'recommended' | 'selected' | 'none'
  selected_models: ModelSelection[]
  creative_context_version: number
  planning_stale: boolean
}

export interface AttachmentModuleModelContext {
  module_key: string
  selection_mode: 'inherit' | 'recommended' | 'selected' | 'none'
  effective_selection_mode: string
  inherited: boolean
  selected_identity_version_ids: string[]
}

export const listVisualPresets = () => authenticatedFetch<VisualPreset[]>('/creative-presets/visual')
export const listThemePresets = () => authenticatedFetch<ThemePreset[]>('/creative-presets/themes')
export const listAIModelPresets = () => authenticatedFetch<AIModelPreset[]>('/creative-presets/models')
export const getAIModelPreset = (id: string) => authenticatedFetch<AIModelPreset>(`/creative-presets/models/${id}`)
export function generatePersonalAIModel(input: {
  idempotency_key: string
  quick_type: string
  display_name: string
  gender_presentation: string
  age_range: '18-24' | '25-30' | '30-39' | '40-49' | '50+'
  body_type: 'slim' | 'natural' | 'fit' | 'athletic' | 'strong' | 'tall'
  commercial_style: 'amazon_ecommerce' | 'sports' | 'lifestyle' | 'streetwear' | 'premium_commercial'
  personality: 'natural' | 'sunny' | 'mature' | 'friendly' | 'confident' | 'cool' | 'energetic' | 'premium'
  hair_style: string
  expression: 'neutral' | 'subtle_smile' | 'confident' | 'relaxed'
  recommended_usage: Array<'stadium' | 'gift' | 'casual' | 'sports' | 'family' | 'street'>
}) {
  return authenticatedFetch<AIModelPreset>('/creative-presets/models/generate', { method: 'POST', body: JSON.stringify(input) })
}
export const savePersonalAIModel = (id: string) => authenticatedFetch<AIModelPreset>(`/creative-presets/models/${id}/save-personal`, { method: 'POST' })
export const getAttachmentCreativeContext = (projectId: string) =>
  authenticatedFetch<AttachmentCreativeContext>(`/attachment-workbench/projects/${projectId}/creative-context`)

export function updateAttachmentCreativeContext(projectId: string, input: {
  visual_preset_id: string
  theme_preset_id: string | null
  model_selection_mode: 'recommended' | 'selected' | 'none'
  selected_model_identity_version_ids: string[]
  expected_creative_context_version: number
}) {
  return authenticatedFetch<AttachmentCreativeContext>(`/attachment-workbench/projects/${projectId}/creative-context`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export const getAttachmentModuleModelContext = (projectId: string, moduleKey: string) =>
  authenticatedFetch<AttachmentModuleModelContext>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/model-context`)

export function updateAttachmentModuleModelContext(projectId: string, moduleKey: string, input: {
  selection_mode: AttachmentModuleModelContext['selection_mode']
  selected_model_identity_version_ids: string[]
}) {
  return authenticatedFetch<AttachmentModuleModelContext>(`/attachment-workbench/projects/${projectId}/modules/${moduleKey}/model-context`, {
    method: 'PUT', body: JSON.stringify(input),
  })
}

export const adminListVisualPresets = () => authenticatedFetch<VisualPreset[]>('/admin/creative-presets/visual')
export const adminListThemePresets = () => authenticatedFetch<ThemePreset[]>('/admin/creative-presets/themes')
export const adminListAIModelPresets = () => authenticatedFetch<AIModelPreset[]>('/admin/creative-presets/models')

export function adminCreateVisualPreset(input: {
  code: string; name: string; short_description: string; full_prompt_template: string
  tags: string[]; category_scope: string[]; recommended_modules: string[]
  recommended_model_tags: string[]; sort_order: number; is_default: boolean
}) {
  return authenticatedFetch<VisualPreset>('/admin/creative-presets/visual', { method: 'POST', body: JSON.stringify(input) })
}

export function adminCreateThemePreset(input: {
  code: string; name: string; short_description: string; full_prompt_template: string
  tags: string[]; sort_order: number
}) {
  return authenticatedFetch<ThemePreset>('/admin/creative-presets/themes', { method: 'POST', body: JSON.stringify(input) })
}

export function adminUpdateVisualPreset(id: string, input: Partial<VisualPreset> & { full_prompt_template?: string; change_summary?: string }) {
  return authenticatedFetch<VisualPreset>(`/admin/creative-presets/visual/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function adminUpdateThemePreset(id: string, input: Partial<ThemePreset> & { full_prompt_template?: string; change_summary?: string }) {
  return authenticatedFetch<ThemePreset>(`/admin/creative-presets/themes/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function adminUpdateAIModelPreset(id: string, input: Partial<AIModelPreset>) {
  return authenticatedFetch<AIModelPreset>(`/admin/creative-presets/models/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function adminGenerateAIModelIdentity(id: string, idempotencyKey: string) {
  return authenticatedFetch<AIModelPreset>(`/admin/creative-presets/models/${id}/identities`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export function adminConfirmAIModelIdentity(id: string, identityId: string) {
  return authenticatedFetch<AIModelPreset>(`/admin/creative-presets/models/${id}/identities/${identityId}/confirm`, { method: 'POST' })
}

export function adminGenerateAIModelReferences(id: string, identityId: string, idempotencyKey: string) {
  return authenticatedFetch<AIModelPreset>(`/admin/creative-presets/models/${id}/identities/${identityId}/references`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export function adminPublishAIModelIdentity(id: string, identityId: string) {
  return authenticatedFetch<AIModelPreset>(`/admin/creative-presets/models/${id}/identities/${identityId}/publish`, { method: 'POST' })
}
