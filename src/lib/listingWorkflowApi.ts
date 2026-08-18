import { authenticatedFetch } from './authApi'
import type { JobOutput } from './jobsApi'

export interface ProductCategory {
  id: string
  category_code: string
  category_name: string
  description: string | null
  is_active: boolean
  sort_order: number
  default_skill_id: string | null
  default_skill_name: string | null
  default_image_template_id: string | null
  default_image_template_name: string | null
  default_image_types: string[]
  created_at: string
  updated_at: string
}

export interface CategorySkill {
  id: string
  category_id: string
  skill_name: string
  skill_code: string
  is_active: boolean
  version: number
  analysis_prompt: string
  listing_title_prompt: string
  bullet_points_prompt: string
  a_plus_prompt: string
  image_prompt_template: string
  image_types_config: Array<{ code?: string; name?: string; [key: string]: unknown }>
  prompt_rules: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface CategoryImageTemplate {
  id: string
  category_id: string
  template_name: string
  template_code: string
  version: number
  is_active: boolean
  system_prompt: string
  image_type_prompts: Record<string, string>
  default_image_types: string[]
  created_at: string
  updated_at: string
}

export interface CategoryRecommendation {
  job_id: string
  status: string
  category_id: string | null
  category_code: string | null
  category_name: string | null
  confidence: number | null
  reason: string | null
  error_message: string | null
}

export interface ListingPromptSnapshot {
  system_prompt: string
  skill_prompt: string
  analysis_segment: string
  user_prompt: string
  final_prompt: string
  final_prompts: Record<string, string>
}

export interface LocalizedText { en: string; zh: string }
export interface LocalizedTerms { en: string[]; zh: string[] }
export interface BilingualListingContent {
  title: LocalizedText
  bullet_points: Array<LocalizedText & { id: string }>
  description: LocalizedText
  search_terms: LocalizedTerms
  selling_points: LocalizedText
  usage_scenarios: LocalizedText
  customization_notes: LocalizedText
  cautions: LocalizedText
  a_plus_copy?: Record<string, unknown> | string
}

export interface ListingWorkflowSession {
  id: string
  project_id: string | null
  category_id: string
  category_code: string
  category_name: string
  skill_id: string
  skill_name: string
  skill_version_id: string | null
  skill_version_number: number | null
  category_skill_snapshot: Record<string, unknown> | null
  status: string
  listing_version_id: string | null
  listing_version_number: number | null
  confirmed_at: string | null
  confirmed_by: string | null
  planning_job_id: string | null
  planning_job_status: string | null
  image_batch_id: string | null
  image_batch_status: string | null
  source_asset_ids: string[]
  primary_asset_id: string | null
  structured_attributes: Record<string, unknown>
  listing_content: BilingualListingContent
  default_image_types: string[]
  prompt: ListingPromptSnapshot | null
  error_message: string | null
  state_version: number
  current_step: number
  last_saved_at: string | null
  created_at: string
  updated_at: string
}

export interface ListingWorkflowSessionSummary {
  id: string
  category_name: string
  skill_name: string
  skill_version_number: number | null
  status: string
  listing_version_number: number | null
  confirmed_at: string | null
  primary_asset_id: string | null
  source_asset_ids: string[]
  listing_title_en: string
  listing_title_zh: string
  variation_enabled: boolean
  updated_at: string
}

export interface OutputProjectSummary {
  exists: boolean
  project_id: string | null
  status: string | null
  listing_version_number: number | null
  outdated: boolean
}

export interface ListingOutputOptions {
  session_id: string
  listing_confirmed: boolean
  listing_version_id: string | null
  listing_version_number: number | null
  listing_snapshot: BilingualListingContent
  category_name: string
  skill_name: string
  skill_version_number: number | null
  primary_asset_id: string | null
  source_asset_ids: string[]
  confirmed_at: string | null
  listing_image_project: OutputProjectSummary
  a_plus_project: OutputProjectSummary
}

export interface CategoryOutputProject {
  id: string
  session_id: string
  kind: 'listing_image' | 'a_plus'
  status: string
  selected_template: string | null
  prompt_config: Record<string, unknown>
  modules: Array<Record<string, unknown>>
  task_count: number
  generated_asset_ids: string[]
  last_batch_id: string | null
  last_batch_status: string | null
  listing_version_id: string
  listing_version_number: number
  latest_listing_version_number: number
  outdated: boolean
  listing_snapshot: ListingWorkflowSession['listing_content']
  analysis_snapshot: Record<string, unknown>
  category_skill_snapshot: Record<string, unknown>
  source_asset_ids: string[]
  primary_asset_id: string | null
  category_name: string
  skill_name: string
  state_version: number
  last_saved_at: string | null
  created_at: string
  updated_at: string
}

export interface ListingImageModuleAttribute {
  code: string
  label: string
  value: unknown
  weight: 'high' | 'low'
  source: 'product_profile' | 'module_override'
}

export interface ListingImageModule {
  [key: string]: unknown
  code: string
  name: string
  sort_order: number
  objective: string
  recommended_aspect_ratio: string
  available: boolean
  unavailable_reason: string
  used_attributes: ListingImageModuleAttribute[]
  recommendations: string[]
  prompt: string
  reference_role: string
}

export interface BuiltListingPrompts {
  session_id: string
  image_types: string[]
  prompts: Record<string, string>
  system_prompt: string
  skill_prompt: string
  analysis_segment: string
  user_prompt: string
}

export type PromptOptimizationStatus = 'draft' | 'needs_optimization' | 'optimizing' | 'optimized' | 'manually_edited'
export interface ImagePromptItem {
  id: string
  project_type: 'listing_image' | 'a_plus'
  project_id: string
  session_id: string | null
  prompt_item_id: string
  image_type: string
  original_english_prompt: string
  chinese_editing_instruction: string
  optimized_english_prompt: string
  status: PromptOptimizationStatus
  current_version_number: number
  optimizer_job_id: string | null
  optimizer_model: string | null
  optimized_at: string | null
  error_message: string | null
  state_version: number
  last_saved_at: string | null
}

export interface ImagePromptVersion {
  id: string
  version_number: number
  original_english_prompt: string
  chinese_editing_instruction: string
  optimized_english_prompt: string
  optimizer_model: string | null
  optimized_at: string
}

export interface ListingImageTaskAsset {
  asset_id: string
  role: string
  filename: string
  mime_type: string
  width: number
  height: number
  url: string | null
  available: boolean
}

export interface ListingImageTask {
  id: string
  batch_id: string | null
  image_type: string
  prompt_status: string
  status: string
  progress: number
  final_prompt: string
  model_code: string
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  input_assets: ListingImageTaskAsset[]
  outputs: JobOutput[]
  variation_type_code: string | null
  variation_type_name: string | null
  variation_plan_code: string | null
  variation_plan_name: string | null
  variation_version: number | null
  chinese_prompt: string
}

export interface FreeVariationContext {
  project_id: string
  session_id: string
  category_id: string
  asset_ids: string[]
  primary_asset_id: string | null
  chinese_prompt: string
  final_english_prompt: string
  prompt_item_id: string | null
  prompt_status: PromptOptimizationStatus | null
  selected_category_id: string | null
  template_fragments: string[]
}

export interface FreeVariationRecommendation {
  available: boolean
  category_id: string | null
  category_name: string | null
  skill_id: string | null
  skill_name: string | null
  skill_version_id: string | null
  skill_version_number: number | null
  directions: Array<{
    code: string
    name: string
    preserve_elements: string[]
    allowed_changes: string[]
    plans: Array<{ code: string; name: string }>
  }>
  templates: Array<{ id: string; name: string; text: string }>
}

export interface FreeVariationPromptBuild {
  project_id: string
  session_id: string
  category_id: string
  prompt_item_id: string
  item_code: string
  image_type: string
  base_prompt: string
  chinese_prompt: string
  optimized_english_prompt: string
  prompt_status: PromptOptimizationStatus
  recommendation: FreeVariationRecommendation
}

export interface ListingImageTaskGroup {
  id: string
  batch_id: string | null
  listing_image_project_id: string
  session_id: string
  listing_version_id: string
  listing_version_number: number
  category_skill_version_id: string | null
  skill_version_number: number | null
  category_name: string
  skill_name: string
  listing_summary: BilingualListingContent
  workflow_mode: 'standard' | 'smart_image_variation'
  variation_types: string[]
  variation_plan_count: number
  source_task_group_id: string | null
  group_number: number
  group_name: string
  status: string
  selected_image_types: string[]
  input_assets: ListingImageTaskAsset[]
  tasks: ListingImageTask[]
  statistics: { total: number; queued: number; running: number; succeeded: number; failed: number; cancelled: number }
  progress: number
  created_by: string
  created_at: string
  updated_at: string
}

export interface QuickListingOptions {
  category_id: string
  category_name: string
  skill_id: string
  skill_name: string
  skill_version_id: string
  skill_version_number: number
  default_image_types: string[]
  default_variation_plan_count: number
  default_variation_image_count: number
}

export interface QuickListingStatus {
  session_id: string
  stage: string
  status: string
  category_name: string
  skill_name: string
  skill_version_number: number | null
  selected_image_types: string[]
  listing_version_id: string | null
  listing_version_number: number | null
  listing_summary: BilingualListingContent | null
  listing_image_project_id: string | null
  task_group_id: string | null
  task_group_status: string | null
  target_url: string | null
  error_message: string | null
}

export function listProductCategories(includeInactive = false) {
  return authenticatedFetch<ProductCategory[]>(`/categories${includeInactive ? '?include_inactive=true' : ''}`)
}

export function createProductCategory(input: {
  category_code: string
  category_name: string
  description?: string
  is_active?: boolean
  sort_order?: number
}) {
  return authenticatedFetch<ProductCategory>('/categories', { method: 'POST', body: JSON.stringify(input) })
}

export function updateProductCategory(id: string, input: Partial<Pick<ProductCategory,
  'category_name' | 'description' | 'is_active' | 'sort_order' | 'default_skill_id' | 'default_image_template_id'
>>) {
  return authenticatedFetch<ProductCategory>(`/categories/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function listCategorySkills(categoryId?: string, includeInactive = false) {
  const params = new URLSearchParams()
  if (categoryId) params.set('category_id', categoryId)
  if (includeInactive) params.set('include_inactive', 'true')
  return authenticatedFetch<CategorySkill[]>(`/category-skills${params.size ? `?${params}` : ''}`)
}

export function createCategorySkill(input: Omit<CategorySkill, 'id' | 'created_at' | 'updated_at'>) {
  return authenticatedFetch<CategorySkill>('/category-skills', { method: 'POST', body: JSON.stringify(input) })
}

export function updateCategorySkill(id: string, input: Partial<Pick<CategorySkill,
  'skill_name' | 'is_active' | 'analysis_prompt' | 'listing_title_prompt' | 'bullet_points_prompt' |
  'a_plus_prompt' | 'image_prompt_template' | 'image_types_config' | 'prompt_rules'
>>) {
  return authenticatedFetch<CategorySkill>(`/category-skills/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function copyCategorySkill(id: string) {
  return authenticatedFetch<CategorySkill>(`/category-skills/${id}/copy`, { method: 'POST' })
}

export function listCategoryImageTemplates(categoryId?: string, includeInactive = false) {
  const params = new URLSearchParams()
  if (categoryId) params.set('category_id', categoryId)
  if (includeInactive) params.set('include_inactive', 'true')
  return authenticatedFetch<CategoryImageTemplate[]>(`/category-image-templates${params.size ? `?${params}` : ''}`)
}

export function createCategoryImageTemplate(input: Omit<CategoryImageTemplate, 'id' | 'created_at' | 'updated_at'>) {
  return authenticatedFetch<CategoryImageTemplate>('/category-image-templates', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function updateCategoryImageTemplate(id: string, input: Partial<Pick<CategoryImageTemplate,
  'template_name' | 'is_active' | 'system_prompt' | 'image_type_prompts' | 'default_image_types'
>>) {
  return authenticatedFetch<CategoryImageTemplate>(`/category-image-templates/${id}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function startCategoryRecommendation(assetIds: string[], idempotencyKey: string) {
  return authenticatedFetch<{ job_id: string; status: string }>('/listing-workbench/recommend-category', {
    method: 'POST', body: JSON.stringify({ product_image_asset_ids: assetIds, idempotency_key: idempotencyKey }),
  })
}

export function getCategoryRecommendation(jobId: string) {
  return authenticatedFetch<CategoryRecommendation>(`/listing-workbench/recommendations/${jobId}`)
}

export function analyzeCategoryProduct(input: {
  product_image_asset_ids: string[]
  primary_asset_id?: string
  selected_category_id: string
  project_id?: string
  idempotency_key: string
}) {
  return authenticatedFetch<{ session_id: string; project_id: string | null; job_id: string; status: string }>(
    '/listing-workbench/analyze-product', { method: 'POST', body: JSON.stringify(input) },
  )
}

export function getQuickListingOptions(categoryId: string) {
  return authenticatedFetch<QuickListingOptions>(`/listing-workbench/quick-options?category_id=${encodeURIComponent(categoryId)}`)
}

export function startQuickListingGeneration(input: {
  product_image_asset_ids: string[]
  primary_asset_id?: string
  selected_category_id: string
  selected_image_types?: string[]
  idempotency_key: string
  concurrency?: number
  size?: string
  aspect_ratio?: string
  requested_width?: number
  requested_height?: number
  quality?: string
  output_format?: 'png' | 'jpeg' | 'webp'
  include_default_variations?: boolean
}) {
  return authenticatedFetch<{
    session_id: string
    planning_job_id: string
    status: string
    category_name: string
    skill_name: string
    skill_version_number: number
    selected_image_types: string[]
  }>('/listing-workbench/quick-generate', { method: 'POST', body: JSON.stringify(input) })
}

export function getQuickListingStatus(sessionId: string) {
  return authenticatedFetch<QuickListingStatus>(`/listing-workbench/quick-generations/${sessionId}`)
}

export function getListingWorkflowSession(sessionId: string) {
  return authenticatedFetch<ListingWorkflowSession>(`/listing-workbench/sessions/${sessionId}`)
}

export function createFreeVariationProject(input: {
  asset_ids?: string[]
  primary_asset_id?: string
  source_session_id?: string
}) {
  return authenticatedFetch<FreeVariationContext>('/listing-workbench/free-variation-projects', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function getFreeVariationProject(projectId: string) {
  return authenticatedFetch<FreeVariationContext>(`/listing-workbench/free-variation-projects/${projectId}`)
}

export function updateFreeVariationProject(projectId: string, input: {
  asset_ids: string[]
  primary_asset_id: string
}) {
  return authenticatedFetch<FreeVariationContext>(`/listing-workbench/free-variation-projects/${projectId}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
}

export function getFreeVariationRecommendations(categoryId?: string) {
  const suffix = categoryId ? `?category_id=${encodeURIComponent(categoryId)}` : ''
  return authenticatedFetch<FreeVariationRecommendation>(`/listing-workbench/free-variation-recommendations${suffix}`)
}

export function buildFreeVariationPrompt(projectId: string, input: {
  chinese_prompt: string
  selected_category_id?: string
  template_fragments?: string[]
}) {
  return authenticatedFetch<FreeVariationPromptBuild>(`/listing-image-projects/${projectId}/free-variation-prompt`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function generateFreeVariations(projectId: string, input: {
  count: number
  idempotency_key: string
  concurrency?: number
  size?: string
  aspect_ratio?: string
  requested_width?: number
  requested_height?: number
  quality?: string
  output_format?: 'png' | 'jpeg' | 'webp'
}) {
  return authenticatedFetch<{
    project_id: string; batch_id: string; task_group_id: string; group_number: number
    status: string; job_ids: string[]; items: string[]
  }>(`/listing-image-projects/${projectId}/free-variations/generate`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function listListingWorkflowSessions(limit = 50) {
  return authenticatedFetch<ListingWorkflowSessionSummary[]>(`/listing-workbench/sessions?limit=${limit}`)
}

export function updateListingWorkflowSession(sessionId: string, input: {
  structured_attributes?: Record<string, unknown>
  listing_content?: ListingWorkflowSession['listing_content']
  user_prompt?: string
  current_step?: number
  expected_state_version?: number
}) {
  return authenticatedFetch<ListingWorkflowSession>(`/listing-workbench/sessions/${sessionId}`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function optimizeBilingualListing(sessionId: string, input: {
  direction: 'en_to_zh' | 'zh_to_en'
  listing_content: BilingualListingContent
  idempotency_key: string
}) {
  return authenticatedFetch<{ session_id: string; job_id: string; status: string; direction: 'en_to_zh' | 'zh_to_en'; listing_content?: BilingualListingContent; error_message?: string }>(
    `/listing-workbench/sessions/${sessionId}/optimize-listing`, { method: 'POST', body: JSON.stringify(input) },
  )
}

export function getBilingualListingOptimization(sessionId: string, jobId: string) {
  return authenticatedFetch<{ session_id: string; job_id: string; status: string; direction: 'en_to_zh' | 'zh_to_en'; listing_content?: BilingualListingContent; error_message?: string }>(
    `/listing-workbench/sessions/${sessionId}/listing-optimizations/${jobId}`,
  )
}

export function confirmListingWorkflowSession(sessionId: string, input: {
  structured_attributes?: Record<string, unknown>
  listing_content?: ListingWorkflowSession['listing_content']
}) {
  return authenticatedFetch<ListingWorkflowSession>(`/listing-workbench/sessions/${sessionId}/confirm`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function getListingOutputOptions(sessionId: string) {
  return authenticatedFetch<ListingOutputOptions>(`/listing-workbench/sessions/${sessionId}/output-options`)
}

export function createCategoryOutputProject(kind: 'listing-image' | 'a-plus', sessionId: string, adoptLatest = false) {
  return authenticatedFetch<CategoryOutputProject>(`/${kind}-projects`, {
    method: 'POST', body: JSON.stringify({ session_id: sessionId, adopt_latest_listing: adoptLatest }),
  })
}

export function getCategoryOutputProject(kind: 'listing-image' | 'a-plus', projectId: string) {
  return authenticatedFetch<CategoryOutputProject>(`/${kind}-projects/${projectId}`)
}

export function updateCategoryOutputProject(kind: 'listing-image' | 'a-plus', projectId: string, input: {
  selected_template?: string
  prompt_config?: Record<string, unknown>
  modules?: Array<Record<string, unknown>>
  adopt_latest_listing?: boolean
  expected_state_version?: number
}) {
  return authenticatedFetch<CategoryOutputProject>(`/${kind}-projects/${projectId}`, {
    method: 'PATCH', body: JSON.stringify(input),
  })
}

export function buildOutputProjectPrompts(kind: 'listing-image' | 'a-plus', projectId: string, input: {
  selected_items?: string[]
  prompt_overrides?: Record<string, string>
  module_attribute_overrides?: Record<string, Record<string, unknown>>
}) {
  return authenticatedFetch<{ project_id: string; prompts: Record<string, string>; modules: ListingImageModule[] }>(`/${kind}-projects/${projectId}/build-prompts`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function buildAPlusModules(projectId: string, input: { template_code: string; module_codes?: string[] }) {
  return authenticatedFetch<{ project_id: string; modules: Array<Record<string, unknown>> }>(`/a-plus-projects/${projectId}/build-modules`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function generateOutputProject(kind: 'listing-image' | 'a-plus', projectId: string, input: {
  selected_items?: string[]
  prompt_overrides?: Record<string, string>
  idempotency_key: string
  concurrency?: number
  size?: string
  aspect_ratio?: string
  requested_width?: number
  requested_height?: number
  quality?: string
  output_format?: 'png' | 'jpeg' | 'webp'
}) {
  return authenticatedFetch<{ project_id: string; batch_id: string; task_group_id: string | null; group_number: number | null; status: string; job_ids: string[]; items: string[] }>(`/${kind}-projects/${projectId}/generate`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function listListingImageTaskGroups(projectId: string, status?: string) {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return authenticatedFetch<{ items: ListingImageTaskGroup[]; total: number }>(`/listing-image-projects/${projectId}/task-groups${suffix}`)
}

export function getListingImageTaskGroup(groupId: string) {
  return authenticatedFetch<ListingImageTaskGroup>(`/listing-image-task-groups/${groupId}`)
}

export function cancelListingImageTaskGroup(groupId: string) {
  return authenticatedFetch<ListingImageTaskGroup>(`/listing-image-task-groups/${groupId}/cancel`, { method: 'POST' })
}

export function retryFailedListingImageTaskGroup(groupId: string, idempotencyKey: string) {
  return authenticatedFetch<ListingImageTaskGroup>(`/listing-image-task-groups/${groupId}/retry-failed`, {
    method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }),
  })
}

export interface ImageVariationType {
  code: string
  name: string
  enabled?: boolean
  default_count?: number
  recommended_aspect_ratio?: string
  preserve_elements: string[]
  allowed_changes: string[]
  prompt_rule: string
  plans: Array<{
    code: string; name: string; enabled?: boolean; default_selected?: boolean
    prompt_template: string; chinese_instruction_default?: string
  }>
}

export interface ImageVariationOptions {
  project_id: string
  session_id: string
  category_name: string
  skill_name: string
  skill_version_id: string | null
  skill_version_number: number | null
  product_asset_ids: string[]
  primary_asset_id: string | null
  max_total_images: number
  quick_defaults: Array<Record<string, unknown>>
  types: ImageVariationType[]
}

export interface ImageVariationPlanDraft {
  type_code: string
  plan_code: string
  plan_key: string
  name: string
  custom: boolean
  chinese_instruction: string
  count: number
}

export interface BuiltImageVariationPlan extends ImageVariationPlanDraft {
  item_code: string
  type_name: string
  plan_name: string
  recommended_aspect_ratio: string
  preserve_elements: string[]
  allowed_changes: string[]
  base_prompt: string
  prompt_item_id: string
  prompt_status: string
}

export function getImageVariationOptions(projectId: string) {
  return authenticatedFetch<ImageVariationOptions>(`/listing-image-projects/${projectId}/variation-options`)
}

export function buildImageVariationPrompts(projectId: string, plans: ImageVariationPlanDraft[]) {
  return authenticatedFetch<{ project_id: string; plans: BuiltImageVariationPlan[] }>(`/listing-image-projects/${projectId}/variation-prompts`, {
    method: 'POST', body: JSON.stringify({ plans }),
  })
}

export function generateImageVariations(projectId: string, input: {
  plans: Array<{ item_code: string; count: number }>
  idempotency_key: string
  concurrency?: number
  source_asset_id?: string
  source_task_group_id?: string
  size?: string
  aspect_ratio?: string
  requested_width?: number
  requested_height?: number
  quality?: string
  output_format?: 'png' | 'jpeg' | 'webp'
}) {
  return authenticatedFetch<{ project_id: string; batch_id: string; task_group_id: string; group_number: number; status: string; job_ids: string[]; items: string[] }>(`/listing-image-projects/${projectId}/variations/generate`, {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function buildListingImagePrompts(input: {
  session_id: string
  selected_image_types?: string[]
  user_prompt_override?: string
}) {
  return authenticatedFetch<BuiltListingPrompts>('/listing-workbench/build-image-prompts', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function generateCategoryListingImages(input: {
  session_id: string
  selected_image_types?: string[]
  user_prompt_override?: string
  idempotency_key: string
  concurrency?: number
  size?: string
  aspect_ratio?: string
  requested_width?: number
  requested_height?: number
  quality?: string
  output_format?: 'png' | 'jpeg' | 'webp'
  output_compression?: number | null
}) {
  return authenticatedFetch<{ session_id: string; batch_id: string; status: string; job_ids: string[]; image_types: string[] }>(
    '/listing-workbench/generate-images', { method: 'POST', body: JSON.stringify(input) },
  )
}

export interface PromptItemInput {
  project_type: 'listing_image' | 'a_plus'
  project_id: string
  session_id: string
  prompt_item_id: string
  category_id: string
  image_type: string
  original_english_prompt: string
  chinese_editing_instruction: string
  optimized_english_prompt?: string
  manual_edit?: boolean
  expected_state_version?: number
}

export function listImagePromptItems(projectType: 'listing_image' | 'a_plus', projectId: string) {
  return authenticatedFetch<ImagePromptItem[]>(`/prompt-optimizer/projects/${projectType}/${projectId}/items`)
}

export function saveImagePromptItem(input: PromptItemInput) {
  return authenticatedFetch<ImagePromptItem>('/prompt-optimizer/project-items', {
    method: 'PUT', body: JSON.stringify(input),
  })
}

export function optimizeImagePrompt(input: PromptItemInput & { idempotency_key: string }) {
  return authenticatedFetch<ImagePromptItem>('/prompt-optimizer/optimize-image-prompt', {
    method: 'POST', body: JSON.stringify(input),
  })
}

export function getImagePromptItem(itemId: string) {
  return authenticatedFetch<ImagePromptItem>(`/prompt-optimizer/items/${itemId}`)
}

export function listImagePromptVersions(itemId: string) {
  return authenticatedFetch<ImagePromptVersion[]>(`/prompt-optimizer/items/${itemId}/versions`)
}

export function restorePreviousImagePrompt(itemId: string) {
  return authenticatedFetch<ImagePromptItem>(`/prompt-optimizer/items/${itemId}/restore-previous`, { method: 'POST' })
}

export function restoreDefaultImagePrompt(itemId: string) {
  return authenticatedFetch<ImagePromptItem>(`/prompt-optimizer/items/${itemId}/restore-skill-default`, { method: 'POST' })
}

export function optimizeAllImagePrompts(projectType: 'listing_image' | 'a_plus', projectId: string, idempotencyKey: string) {
  return authenticatedFetch<{ project_id: string; items: ImagePromptItem[] }>('/prompt-optimizer/optimize-all', {
    method: 'POST', body: JSON.stringify({ project_type: projectType, project_id: projectId, idempotency_key: idempotencyKey }),
  })
}

export interface AdminCategorySkill {
  id: string; category_id: string; category_name: string; skill_name: string; skill_code: string
  description: string | null; marketplace: string; language: string; status: string; is_active: boolean
  default_published_version_id: string | null; default_version_number: number | null; is_category_default: boolean
  created_at: string; updated_at: string
}

export interface CategorySkillVersionConfig {
  id: string; skill_id: string; version_number: number
  status: 'draft' | 'testing' | 'published' | 'disabled' | 'archived'
  analysis_config: Record<string, unknown>; listing_config: Record<string, unknown>
  translation_config: Record<string, unknown>; image_prompt_config: Record<string, unknown>
  a_plus_config: Record<string, unknown>; full_config_snapshot: Record<string, unknown>
  change_summary: string; source_version_id: string | null; published_by: string | null
  published_at: string | null; created_by: string | null; created_at: string; updated_at: string
}

export interface CategorySkillValidation {
  valid: boolean; errors: string[]; warnings: string[]; referenced_variables: string[]
}

export function listAdminCategorySkills(categoryId?: string) {
  const suffix = categoryId ? `?category_id=${encodeURIComponent(categoryId)}` : ''
  return authenticatedFetch<AdminCategorySkill[]>(`/admin/category-skills${suffix}`)
}

export function createAdminCategorySkill(input: {
  category_id: string; skill_name: string; skill_code: string; description?: string
  marketplace?: string; language?: string; source_skill_id?: string
}) {
  return authenticatedFetch<AdminCategorySkill>('/admin/category-skills', { method: 'POST', body: JSON.stringify(input) })
}

export function updateAdminCategorySkill(skillId: string, input: Partial<Pick<AdminCategorySkill,
  'skill_name' | 'description' | 'marketplace' | 'language' | 'is_active'
>>) {
  return authenticatedFetch<AdminCategorySkill>(`/admin/category-skills/${skillId}`, { method: 'PUT', body: JSON.stringify(input) })
}

export function listAdminCategorySkillVersions(skillId: string) {
  return authenticatedFetch<CategorySkillVersionConfig[]>(`/admin/category-skills/${skillId}/versions`)
}

export function createAdminCategorySkillVersion(skillId: string, sourceVersionId?: string, changeSummary = '') {
  return authenticatedFetch<CategorySkillVersionConfig>(`/admin/category-skills/${skillId}/versions`, {
    method: 'POST', body: JSON.stringify({ source_version_id: sourceVersionId, change_summary: changeSummary }),
  })
}

export function updateAdminCategorySkillVersion(skillId: string, versionId: string, input: {
  analysis_config: Record<string, unknown>; listing_config: Record<string, unknown>
  translation_config: Record<string, unknown>; image_prompt_config: Record<string, unknown>
  a_plus_config: Record<string, unknown>; change_summary?: string
}) {
  return authenticatedFetch<CategorySkillVersionConfig>(`/admin/category-skills/${skillId}/versions/${versionId}`, {
    method: 'PUT', body: JSON.stringify(input),
  })
}

export function validateAdminCategorySkillVersion(skillId: string, versionId: string) {
  return authenticatedFetch<CategorySkillValidation>(`/admin/category-skills/${skillId}/versions/${versionId}/validate`, { method: 'POST' })
}

export function testAdminCategorySkillVersion(skillId: string, versionId: string, input: {
  product_information?: string; sample_analysis?: Record<string, unknown>
}) {
  return authenticatedFetch<{
    validation: CategorySkillValidation; system_prompt: string; user_prompt: string
    structured_analysis_preview: Record<string, unknown>; bilingual_listing_preview: Record<string, unknown>
    image_prompts: Record<string, string>; model: string | null; elapsed_ms: number
  }>(`/admin/category-skills/${skillId}/versions/${versionId}/test`, { method: 'POST', body: JSON.stringify(input) })
}

export function publishAdminCategorySkillVersion(skillId: string, versionId: string) {
  return authenticatedFetch<CategorySkillVersionConfig>(`/admin/category-skills/${skillId}/versions/${versionId}/publish`, { method: 'POST' })
}

export function setDefaultAdminCategorySkillVersion(skillId: string, versionId: string) {
  return authenticatedFetch<AdminCategorySkill>(`/admin/category-skills/${skillId}/versions/${versionId}/set-default`, { method: 'POST' })
}
