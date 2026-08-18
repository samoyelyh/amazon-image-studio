import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type {
  BatchTryOnAspectRatio, BatchTryOnBatch, BatchTryOnGarment, BatchTryOnItem,
  BatchTryOnTemplate, TaskParams, BatchTryOnGarmentReference, BatchTryOnTemplateGarmentView,
} from '../types'
import { getImage, storeImage } from '../lib/db'
import { buildBatchTryOnPrompt } from '../lib/batchTryOnPrompt'
import { BatchTryOnQueueController, getFailedBatchTryOnItemIds } from '../lib/batchTryOnQueue'
import { createBatchTryOnFileNames, downloadBatchTryOnZip } from '../lib/batchTryOnFiles'
import { downloadImageIds } from '../lib/downloadImages'
import {
  downloadAuthenticatedFile,
  downloadBatchTryOnResultsZip,
  downloadSelectedBatchTryOnTemplateZip,
} from '../lib/serverDownloads'
import { runtimeConfig } from '../app/runtimeConfig'
import { uploadDataUrlAsset, uploadGarmentReferenceDataUrl, importServerAsset } from '../lib/serverImageAssets'
import { getServerBatch, pauseServerBatch, resumeServerBatch } from '../lib/jobsApi'
import type { ServerJobBatchDiagnostics } from '../lib/jobsApi'
import { randomUuid } from '../lib/randomUuid'
import {
  createInputImageFromFile,
  cacheImageDataUrl,
  deleteImageIfUnreferenced,
  ensureImageCached,
  getBatchTryOnProfileError,
  runBatchTryOnTask,
  useStore,
} from '../store'
import BatchTryOnTemplateManager from './BatchTryOnTemplateManager'
import BatchTryOnGarmentList from './BatchTryOnGarmentList'
import BatchTryOnGarmentPreprocessDialog, { type GarmentReferencePreview } from './BatchTryOnGarmentPreprocessDialog'
import BatchTryOnQueue from './BatchTryOnQueue'
import SizePickerModal from './SizePickerModal'
import BatchTryOnReviewDialog from './BatchTryOnReviewDialog'
import BatchTryOnBulkRegenerateDialog from './BatchTryOnBulkRegenerateDialog'
import BatchTryOnBulkLunaDialog from './BatchTryOnBulkLunaDialog'
import BatchTryOnBatchHistory from './BatchTryOnBatchHistory'
import BatchTryOnStyleAnalysisPanel from './BatchTryOnStyleAnalysisPanel'
import BatchTryOnPromptTemplatePanel, { type TemplatePromptDraftConfig } from './BatchTryOnPromptTemplatePanel'
import BatchTryOnSystemPresetManager from './BatchTryOnSystemPresetManager'
import BatchTryOnWorkspaceTabs from './BatchTryOnWorkspaceTabs'
import { BatchTryOnImage } from './BatchTryOnImage'
import { useAuth } from '../app/AuthContext'
import {
  approveBatchTryOnVersion,
  batchAnalyzeAndRegenerateBatchTryOnVersions,
  batchRegenerateBatchTryOnVersions,
  type BatchTryOnBatchRegenerateResponse,
  type BatchTryOnReviewDetail,
} from '../lib/batchTryOnReviewApi'
import {
  toSelectedBatchTryOnReviewItem,
  type SelectedBatchTryOnReviewItem,
} from '../lib/batchTryOnBulkActions'
import { findNextPendingReviewItem } from '../lib/batchTryOnReviewQueue'
import {
  createProject, getProject, linkProjectAsset, linkProjectAssetCompact, saveProjectVersion, unlinkProjectAsset, updateProjectAsset,
  type Project,
} from '../lib/contentApi'
import BatchTryOnPresetPanel from './BatchTryOnPresetPanel'
import {
  summarizeBatchTryOnPresets,
} from '../lib/batchTryOnPresets'
import {
  buildBatchTryOnTemplateMatrix,
  buildUnsubmittedBatchTryOnMatrix,
  getBatchTryOnCombinationError,
  getBatchTryOnCombinationPairs,
  getUnsubmittedBatchTryOnCombinationPairs,
} from '../lib/batchTryOnMatrix'
import { getBatchTryOnConcurrencyOptions } from '../lib/batchTryOnConcurrency'
import {
  appendBatchTryOnSubmissionItems,
  appendTrackedServerBatchId,
  clearBatchTryOnQueueState,
  createEmptyBatch,
  isBatchTryOnConfigurationLocked,
  normalizeBatchTryOnBatch,
  resetItemForNewRun,
  resolveOutputAspectRatio,
  resolveOutputAspectRatioForTemplate,
  resolveOutputSize,
  resolveOutputSizeForTemplate,
  shouldRestoreBatchTryOnWorkflow,
  summarizeItems,
  syncLegacyTemplateFields,
  withTemplateFilenameInfo,
} from '../lib/batchTryOnWorkspaceState'
import {
  applySubmittedBatchTryOnJobs,
} from '../lib/batchTryOnSubmission'
import { useBatchTryOnServerPolling } from '../hooks/useBatchTryOnServerPolling'
import {
  confirmBatchTryOnTemplatePrompt,
  createBatchTryOnPromptPreset,
  createBatchTryOnWorkflow,
  getBatchTryOnWorkflow,
  getLatestBatchTryOnWorkflow,
  listBatchTryOnPromptPresets,
  reanalyzeBatchTryOnTemplatePrompt,
  submitConfirmedBatchTryOnWorkflow,
  resolveValidationWorkflowTemplateId,
  type BatchTryOnPromptMode,
  type BatchTryOnPromptPreset,
  type BatchTryOnTemplatePrompt,
  type BatchTryOnWorkflowResponse,
} from '../lib/batchTryOnWorkflowApi'
import { useBatchTryOnWorkflowPolling } from '../hooks/useBatchTryOnWorkflowPolling'
import { restoreWorkflowStyleProfile } from '../lib/batchTryOnStyleProfile'
import { resolveBatchTryOnAssetId } from '../lib/batchTryOnAssetCache'
import { batchTryOnFontReferenceKey } from '../lib/batchTryOnFontReferences'
import { matchFontReferencesByIdentifier } from '../lib/batchTryOnFontReferenceMatching'
import { compactGarmentTransform, garmentTransformMetadata } from '../lib/batchTryOnGarmentPreprocess'
import { resolveBatchTryOnValidationPromptValues } from '../lib/batchTryOnValidationPrompt'
import {
  createBatchTryOnWorkspace, deleteBatchTryOnWorkspace, hardDeleteBatchTryOnWorkspace,
  listBatchTryOnWorkspaces, updateBatchTryOnWorkspace, type BatchTryOnWorkspaceTab,
} from '../lib/batchTryOnWorkspaceApi'

export const MAX_BATCH_TRY_ON_ITEMS = 50
export const MAX_BATCH_TRY_ON_TEMPLATES = 10
export const MAX_BATCH_TRY_ON_MATRIX_ITEMS = 500
const MAX_BATCH_TRY_ON_FILE_BYTES = 50 * 1024 * 1024
const MAX_MULTIUSER_FILE_BYTES = 20 * 1024 * 1024
const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const MAX_VALIDATION_PROMPT_LENGTH = 10_000

function mergeWorkspaceTabs(
  current: BatchTryOnWorkspaceTab[],
  incoming: BatchTryOnWorkspaceTab[],
  suppressedIds: ReadonlySet<string>,
) {
  const merged = new Map<string, BatchTryOnWorkspaceTab>()
  const incomingProjectIds = new Set(incoming.map((tab) => tab.project_id).filter(Boolean))
  for (const tab of incoming) {
    if (!suppressedIds.has(tab.id)) merged.set(tab.id, tab)
  }
  // A list request can finish after a new workspace was created. Preserve
  // locally known tabs so that this older response cannot make either tab vanish.
  for (const tab of current) {
    if (incomingProjectIds.size && (!tab.project_id || !incomingProjectIds.has(tab.project_id))) continue
    if (!suppressedIds.has(tab.id) && !merged.has(tab.id)) merged.set(tab.id, tab)
  }
  return [...merged.values()]
}

interface ValidationPromptEditorState {
  templateId: string
  templateName: string
  outputImageId?: string
  validationStatus: NonNullable<BatchTryOnTemplate['validationStatus']>
  promptStrategy: NonNullable<BatchTryOnTemplate['promptStrategy']>
  analysisPrompt: string
  originalAnalysisPrompt: string
  sampleFinalPrompt: string
  sampleFinalPromptLabel: string
  loading: boolean
}

function withWorkflowTemplateNames(
  profiles: Record<string, Record<string, unknown>>,
  templates: Array<{ template_id: string; asset_id: string; name: string }>,
) {
  return Object.fromEntries(Object.entries(profiles || {}).map(([templateId, profile]) => {
    const template = templates.find((item) => item.template_id === templateId)
    return [templateId, {
      ...profile,
      template_name: template?.name || templateId,
      template_asset_id: template?.asset_id,
    }]
  }))
}

function readTemplateGarmentViews(draft: Record<string, unknown>): Record<string, BatchTryOnTemplateGarmentView> {
  const value = draft.template_garment_views
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  const allowed = new Set<BatchTryOnTemplateGarmentView>(['auto', 'front', 'back', 'front_back', 'detail'])
  return Object.fromEntries(Object.entries(value).filter(
    (entry): entry is [string, BatchTryOnTemplateGarmentView] => allowed.has(entry[1] as BatchTryOnTemplateGarmentView),
  ))
}

function restoreWorkflowPromptDrafts(
  records: BatchTryOnTemplatePrompt[], templates: BatchTryOnTemplate[],
): Record<string, TemplatePromptDraftConfig> {
  return Object.fromEntries(records.map((item) => {
    const template = templates.find((candidate) => (
      candidate.id === item.template_id || candidate.serverAssetId === item.template_asset_id
    ))
    return [template?.id || item.template_id, {
      templateType: item.template_type,
      presetId: item.preset_id || '',
      analysisPrompt: item.analysis_prompt_used,
    }]
  }))
}

async function persistBatchTryOnTemplates(
  project: Project,
  templates: BatchTryOnTemplate[],
  sortOffset = 0,
): Promise<BatchTryOnTemplate[]> {
  const linksByAssetId = new Map(
    project.assets
      .filter((link) => link.role === 'model_template')
      .map((link) => [link.asset.id, link]),
  )
  const persisted: BatchTryOnTemplate[] = []
  for (const [index, template] of templates.entries()) {
    let assetId = template.serverAssetId
    if (!assetId) {
      const dataUrl = await ensureImageCached(template.imageId)
      if (!dataUrl) throw new Error(`${template.displayName || template.fileName}图片读取失败，请重新上传。`)
      assetId = (await uploadDataUrlAsset(
        dataUrl,
        'model_template',
        template.fileName || template.displayName,
      )).id
    }
    let link = linksByAssetId.get(assetId)
    if (!link) {
      const created = await linkProjectAssetCompact(
        project.id,
        assetId,
        'model_template',
        sortOffset + index,
        template.displayName,
        template.isDefault,
      )
      link = {
        id: created.id,
        role: created.role,
        sort_order: created.sort_order,
        display_name: created.display_name,
        is_default: created.is_default,
        asset: { id: assetId } as Project['assets'][number]['asset'],
        created_at: created.created_at,
      }
      linksByAssetId.set(assetId, link)
    }
    persisted.push({
      ...template,
      serverAssetId: assetId,
      projectAssetLinkId: link.id,
    })
  }
  return persisted
}

export default function BatchTryOnWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const auth = useAuth()
  const isPlatformAdmin = Boolean(auth.identity?.role_codes.includes('platform_admin'))
  const batch = useStore((state) => state.batchTryOnBatch)
  const setBatch = useStore((state) => state.setBatchTryOnBatch)
  const settings = useStore((state) => state.settings)
  const globalParams = useStore((state) => state.params)
  const tasks = useStore((state) => state.tasks)
  const showToast = useStore((state) => state.showToast)
  const setLightboxImageId = useStore((state) => state.setLightboxImageId)
  const setShowSettings = useStore((state) => state.setShowSettings)
  const setConfirmDialog = useStore((state) => state.setConfirmDialog)
  const runnerRef = useRef<BatchTryOnQueueController<string> | null>(null)
  const workflowItemIdsRef = useRef(new Map<string, Set<string>>())
  const [showSizePicker, setShowSizePicker] = useState(false)
  const [reviewItemId, setReviewItemId] = useState<string | null>(null)
  const [selectedReviewItems, setSelectedReviewItems] = useState<Map<string, SelectedBatchTryOnReviewItem>>(new Map())
  const [showBulkRegenerate, setShowBulkRegenerate] = useState(false)
  const [showBulkLuna, setShowBulkLuna] = useState(false)
  const [batchDiagnostics, setBatchDiagnostics] = useState<ServerJobBatchDiagnostics | null>(null)
  const [styleAnalysisStatus, setStyleAnalysisStatus] = useState<string | null>(null)
  const [templateAnalysisProfiles, setTemplateAnalysisProfiles] = useState<Record<string, Record<string, unknown>>>({})
  const [promptPresets, setPromptPresets] = useState<BatchTryOnPromptPreset[]>([])
  const [promptMode, setPromptMode] = useState<BatchTryOnPromptMode>('direct')
  const [templatePromptDrafts, setTemplatePromptDrafts] = useState<Record<string, TemplatePromptDraftConfig>>({})
  const templatePromptDraftsRef = useRef<Record<string, TemplatePromptDraftConfig>>({})
  const [templatePromptRecords, setTemplatePromptRecords] = useState<BatchTryOnTemplatePrompt[]>([])
  const [promptWorkflowStatus, setPromptWorkflowStatus] = useState<BatchTryOnWorkflowResponse['status'] | null>(null)
  const [promptActionBusy, setPromptActionBusy] = useState(false)
  const [showSystemPresetManager, setShowSystemPresetManager] = useState(false)
  const [matrixSubmitting, setMatrixSubmitting] = useState(false)
  const [preprocessOpen, setPreprocessOpen] = useState(false)
  const [preprocessGarmentId, setPreprocessGarmentId] = useState<string | undefined>()
  const [preprocessSaving, setPreprocessSaving] = useState(false)
  const [workspaceTabs, setWorkspaceTabs] = useState<BatchTryOnWorkspaceTab[]>([])
  const [workspaceTabsBusy, setWorkspaceTabsBusy] = useState(false)
  const workspaceSaveTimerRef = useRef<number | null>(null)
  const workspaceSaveChainRef = useRef<Promise<void>>(Promise.resolve())
  const workspaceSaveRevisionRef = useRef(new Map<string, number>())
  const suppressedWorkspaceIdsRef = useRef(new Set<string>())
  const workspaceHydratedRef = useRef<string | null>(null)
  const switchingWorkspaceRef = useRef(false)
  const validationWorkflowTemplateRef = useRef(new Map<string, string>())
  const validationWorkflowSubmittingRef = useRef(new Set<string>())
  const validationWorkflowPollTimersRef = useRef(new Map<string, number>())
  const validationWorkflowPollingRef = useRef(new Set<string>())
  const [validationSubmittingTemplateIds, setValidationSubmittingTemplateIds] = useState<Set<string>>(new Set())
  const [validationPromptEditor, setValidationPromptEditor] = useState<ValidationPromptEditorState | null>(null)
  const [validationPromptRegenerating, setValidationPromptRegenerating] = useState(false)
  const [showGenerateConfirmation, setShowGenerateConfirmation] = useState(false)
  const loadedProjectRef = useRef<string | null>(null)
  const projectDraftSaveRef = useRef<Promise<void>>(Promise.resolve())
  const persistWorkspaceBatch = useCallback((workspaceId: string, snapshot?: BatchTryOnBatch) => {
    if (workspaceHydratedRef.current !== workspaceId) return Promise.resolve()
    const batchToSave = snapshot || useStore.getState().batchTryOnBatch
    if (!batchToSave || batchToSave.serverWorkspaceId !== workspaceId) return Promise.resolve()
    const revision = (workspaceSaveRevisionRef.current.get(workspaceId) || 0) + 1
    workspaceSaveRevisionRef.current.set(workspaceId, revision)
    workspaceSaveChainRef.current = workspaceSaveChainRef.current
      .catch(() => undefined)
      .then(async () => {
        if (workspaceSaveRevisionRef.current.get(workspaceId) !== revision) return
        const configBatch = { ...batchToSave, serverWorkspaceId: undefined }
        const saved = await updateBatchTryOnWorkspace(workspaceId, {
          config: { batch: configBatch, concurrency: batchToSave.concurrency },
        })
        setWorkspaceTabs((items) => items.map((item) => item.id === saved.id ? saved : item))
      })
      .catch((error) => showToast(`批次草稿保存失败：${friendlyError(error)}`, 'error'))
    return workspaceSaveChainRef.current
  }, [showToast])
  const projectId = searchParams.get('project_id') || batch?.serverProjectId || null
  const templateUpdated = searchParams.get('template_updated') === 'true'
  const {
    pollServerBatch,
    pollRegeneratedJobs,
    stopServerPolling,
  } = useBatchTryOnServerPolling({
    enabled: !runtimeConfig.isStandalone,
    batchId: batch?.id,
    serverBatchId: batch?.serverBatchId,
    serverBatchIds: batch?.serverBatchIds,
    canReadAudit: auth.hasPermission('audit.read'),
    onDiagnostics: setBatchDiagnostics,
    onError: (message) => showToast(message, 'error'),
    formatError: friendlyError,
  })
  const { pollBatchTryOnWorkflow, stopBatchTryOnWorkflowPolling } = useBatchTryOnWorkflowPolling({
    enabled: !runtimeConfig.isStandalone,
    workflowJobId: batch?.serverWorkflowId,
    onStatus: setStyleAnalysisStatus,
    onAnalysis: (workflow) => {
      workflowItemIdsRef.current.set(
        workflow.workflow_job_id,
        new Set(workflow.combinations.map((item) => item.client_item_id)),
      )
      const validationTemplateId = resolveValidationWorkflowTemplateId(workflow)
      if (validationTemplateId) {
        validationWorkflowTemplateRef.current.set(workflow.workflow_job_id, validationTemplateId)
      }
      setPromptWorkflowStatus(workflow.status)
      setTemplatePromptRecords(workflow.template_prompts || [])
      const workflowPrompt = workflow.template_prompts?.[0]
      if (workflowPrompt) setTemplatePromptDrafts(restoreWorkflowPromptDrafts(
        workflow.template_prompts, useStore.getState().batchTryOnBatch?.templates || [],
      ))
      setTemplateAnalysisProfiles(withWorkflowTemplateNames(workflow.template_profiles, workflow.templates))
      if (!workflow.garment_profile) return
      setBatch((current) => current?.serverWorkflowId === workflow.workflow_job_id ? {
        ...current,
        styleProfiles: [restoreWorkflowStyleProfile(workflow.garment_profile!, current.garments)],
        updatedAt: Date.now(),
      } : current)
    },
    onBatchReady: async (serverBatchId, workflowJobId) => {
      const submitted = await getServerBatch(serverBatchId)
      if (useStore.getState().batchTryOnBatch?.serverWorkflowId !== workflowJobId) return
      setBatch((current) => current?.serverWorkflowId === workflowJobId ? {
        ...current,
        serverBatchId,
        serverBatchIds: appendTrackedServerBatchId(current.serverBatchIds, serverBatchId),
        queuePaused: false,
        items: applySubmittedBatchTryOnJobs(
          current.items,
          submitted.jobs.map((job) => job.client_item_id).filter((id): id is string => Boolean(id)),
          submitted.jobs,
        ),
        updatedAt: Date.now(),
      } : current)
      showToast(`服务端批次已创建，共 ${submitted.total_jobs} 个任务。`, 'success')
      void pollServerBatch(serverBatchId)
    },
    onFailed: (message, workflowJobId) => {
      const failedItemIds = workflowItemIdsRef.current.get(workflowJobId) || new Set<string>()
      setBatch((current) => current ? {
        ...current,
        queuePaused: current.items.every((item) => !['queued', 'retry_waiting', 'running'].includes(item.status) || failedItemIds.has(item.id)),
        items: current.items.map((item) => failedItemIds.has(item.id) && (item.status === 'queued' || item.status === 'running')
          ? { ...item, status: 'error', error: message, finishedAt: Date.now() }
          : item),
        updatedAt: Date.now(),
      } : current)
      showToast(message, 'error')
    },
  })

  const stopValidationWorkflowPolling = useCallback((workflowJobId?: string) => {
    if (workflowJobId) {
      const timer = validationWorkflowPollTimersRef.current.get(workflowJobId)
      if (timer) window.clearTimeout(timer)
      validationWorkflowPollTimersRef.current.delete(workflowJobId)
      return
    }
    for (const timer of validationWorkflowPollTimersRef.current.values()) window.clearTimeout(timer)
    validationWorkflowPollTimersRef.current.clear()
  }, [])

  const pollValidationWorkflow = useCallback(async (
    workflowJobId: string,
    itemIds: string[],
  ) => {
    if (validationWorkflowPollingRef.current.has(workflowJobId)) return
    validationWorkflowPollingRef.current.add(workflowJobId)
    stopValidationWorkflowPolling(workflowJobId)
    try {
      const workflow = await getBatchTryOnWorkflow(workflowJobId)
      const validationTemplateId = resolveValidationWorkflowTemplateId(workflow)
      if (validationTemplateId) validationWorkflowTemplateRef.current.set(workflowJobId, validationTemplateId)
      if (workflow.status === 'failed' || workflow.status === 'cancelled') {
        const message = workflow.error_message || '样图工作流失败，请重新生成。'
        setBatch((current) => current ? {
          ...current,
          items: current.items.map((item) => itemIds.includes(item.id)
            ? { ...item, status: 'error', error: message, finishedAt: Date.now() }
            : item),
          updatedAt: Date.now(),
        } : current)
        return
      }
      if (workflow.batch_id) {
        const submitted = await getServerBatch(workflow.batch_id)
        setBatch((current) => current ? {
          ...current,
          serverBatchIds: appendTrackedServerBatchId(current.serverBatchIds, workflow.batch_id || undefined),
          queuePaused: false,
          items: applySubmittedBatchTryOnJobs(
            current.items,
            submitted.jobs.map((job) => job.client_item_id).filter((id): id is string => Boolean(id)),
            submitted.jobs,
          ),
          updatedAt: Date.now(),
        } : current)
        void pollServerBatch(workflow.batch_id)
        return
      }
      validationWorkflowPollTimersRef.current.set(
        workflowJobId,
        window.setTimeout(() => { void pollValidationWorkflow(workflowJobId, itemIds) }, 2_000),
      )
    } catch {
      validationWorkflowPollTimersRef.current.set(
        workflowJobId,
        window.setTimeout(() => { void pollValidationWorkflow(workflowJobId, itemIds) }, 5_000),
      )
    } finally {
      validationWorkflowPollingRef.current.delete(workflowJobId)
    }
  }, [pollServerBatch, setBatch, stopValidationWorkflowPolling])

  useEffect(() => () => stopValidationWorkflowPolling(), [stopValidationWorkflowPolling])

  const pendingValidationWorkflowKey = useMemo(() => (batch?.items || [])
    .filter((item) => item.id.startsWith('validation:') && item.serverWorkflowId && !item.serverBatchId
      && ['pending', 'queued', 'retry_waiting', 'running'].includes(item.status))
    .map((item) => `${item.serverWorkflowId}:${item.id}`)
    .sort()
    .join('|'), [batch?.items])

  useEffect(() => {
    if (!pendingValidationWorkflowKey) return
    const workflows = new Map<string, string[]>()
    for (const item of useStore.getState().batchTryOnBatch?.items || []) {
      if (!item.id.startsWith('validation:') || !item.serverWorkflowId || item.serverBatchId) continue
      if (!['pending', 'queued', 'retry_waiting', 'running'].includes(item.status)) continue
      workflows.set(item.serverWorkflowId, [...(workflows.get(item.serverWorkflowId) || []), item.id])
    }
    for (const [workflowJobId, itemIds] of workflows) {
      if (!validationWorkflowPollTimersRef.current.has(workflowJobId)) {
        void pollValidationWorkflow(workflowJobId, itemIds)
      }
    }
  }, [pendingValidationWorkflowKey, pollValidationWorkflow])

  useEffect(() => {
    if (runtimeConfig.isStandalone) return
    let cancelled = false
    void listBatchTryOnPromptPresets().then((presets) => {
      if (cancelled) return
      const enabled = presets.filter((preset) => preset.enabled)
      setPromptPresets(enabled)
    }).catch((error) => {
      if (!cancelled) showToast(friendlyError(error), 'error')
    })
    return () => { cancelled = true }
  }, [showToast])

  useEffect(() => {
    const restored = (batch?.templatePromptConfigs || {}) as Record<string, TemplatePromptDraftConfig>
    templatePromptDraftsRef.current = restored
    setTemplatePromptDrafts(restored)
  }, [batch?.serverProjectId, batch?.serverWorkspaceId, batch?.templatePromptConfigs])

  useEffect(() => {
    if (runtimeConfig.isStandalone || !batch?.serverProjectId) return
    let cancelled = false
    const load = async () => {
      try {
        setWorkspaceTabsBusy(true)
        const page = await listBatchTryOnWorkspaces(batch.serverProjectId!)
        if (cancelled) return
        if (page.items.length) {
          setWorkspaceTabs((currentTabs) => mergeWorkspaceTabs(
            currentTabs,
            page.items,
            suppressedWorkspaceIdsRef.current,
          ))
          const current = useStore.getState().batchTryOnBatch
          const tab = page.items.find((item) => item.id === current?.serverWorkspaceId) || page.items[0]
          if (workspaceHydratedRef.current !== tab.id) {
            workspaceHydratedRef.current = tab.id
            const saved = tab.config.batch as BatchTryOnBatch | undefined
            switchingWorkspaceRef.current = true
            setBatch(saved ? normalizeBatchTryOnBatch({
              ...saved,
              serverWorkspaceId: tab.id,
              serverProjectId: batch.serverProjectId,
              serverProjectName: current?.serverProjectName || batch.serverProjectName,
            }) : {
              ...(current || batch),
              serverWorkspaceId: tab.id,
              serverWorkflowId: undefined,
              serverBatchId: undefined,
              serverBatchIds: [],
            })
            setTemplatePromptRecords([])
            setPromptWorkflowStatus(null)
            void getLatestBatchTryOnWorkflow(batch.serverProjectId!, tab.id).then((workflow) => {
              if (cancelled) return
              const currentBatch = useStore.getState().batchTryOnBatch
              if (!shouldRestoreBatchTryOnWorkflow(workflow.created_at, currentBatch?.queueClearedAt)) return
              const validationTemplateId = resolveValidationWorkflowTemplateId(workflow)
              if (validationTemplateId) validationWorkflowTemplateRef.current.set(workflow.workflow_job_id, validationTemplateId)
              workflowItemIdsRef.current.set(
                workflow.workflow_job_id,
                new Set(workflow.combinations.map((item) => item.client_item_id)),
              )
              setTemplatePromptRecords(workflow.template_prompts || [])
              setPromptWorkflowStatus(workflow.status)
              setBatch((latest) => latest?.serverWorkspaceId === tab.id ? {
                ...latest,
                serverWorkflowId: workflow.workflow_job_id,
                serverBatchId: workflow.batch_id || latest.serverBatchId,
                serverBatchIds: appendTrackedServerBatchId(latest.serverBatchIds, workflow.batch_id || undefined),
                queuePaused: !workflow.batch_id,
                updatedAt: Date.now(),
              } : latest)
              if (workflow.batch_id) void pollServerBatch(workflow.batch_id)
              else void pollBatchTryOnWorkflow(workflow.workflow_job_id)
            }).catch(() => undefined)
            queueMicrotask(() => { switchingWorkspaceRef.current = false })
          }
        } else {
          const created = await createBatchTryOnWorkspace(batch.serverProjectId!, undefined, { batch: { ...batch, serverWorkspaceId: undefined } })
          if (cancelled) return
          setWorkspaceTabs([created])
          switchingWorkspaceRef.current = true
          workspaceHydratedRef.current = created.id
          setBatch((current) => current ? { ...current, serverWorkspaceId: created.id } : current)
          queueMicrotask(() => { switchingWorkspaceRef.current = false })
        }
      } catch (error) {
        if (!cancelled) showToast(friendlyError(error), 'error')
      } finally {
        if (!cancelled) setWorkspaceTabsBusy(false)
      }
    }
    void load()
    const timer = window.setInterval(() => {
      void listBatchTryOnWorkspaces(batch.serverProjectId!).then((page) => {
        if (!cancelled) setWorkspaceTabs((currentTabs) => mergeWorkspaceTabs(
          currentTabs,
          page.items,
          suppressedWorkspaceIdsRef.current,
        ))
      }).catch(() => undefined)
    }, 8_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [batch?.serverProjectId, pollBatchTryOnWorkflow, pollServerBatch, showToast, setBatch])

  useEffect(() => {
    if (runtimeConfig.isStandalone || !batch?.serverWorkspaceId || switchingWorkspaceRef.current) return
    if (workspaceHydratedRef.current !== batch.serverWorkspaceId) return
    if (workspaceSaveTimerRef.current) window.clearTimeout(workspaceSaveTimerRef.current)
    workspaceSaveTimerRef.current = window.setTimeout(() => {
      const workspaceId = batch.serverWorkspaceId!
      workspaceSaveTimerRef.current = null
      persistWorkspaceBatch(workspaceId, batch)
    }, 700)
    return () => { if (workspaceSaveTimerRef.current) window.clearTimeout(workspaceSaveTimerRef.current) }
  }, [batch, persistWorkspaceBatch])

  useEffect(() => {
    setSelectedReviewItems(new Map())
    setShowBulkRegenerate(false)
    setTemplateAnalysisProfiles({})
  }, [batch?.id])

  useEffect(() => {
    if (batch?.serverWorkflowId) return
    setTemplatePromptRecords([])
    setPromptWorkflowStatus(null)
  }, [batch?.serverWorkflowId])

  useEffect(() => {
    if (runtimeConfig.isStandalone || !projectId || loadedProjectRef.current === projectId) return
    let cancelled = false
    let completed = false
    loadedProjectRef.current = projectId
    void getProject(projectId).then(async (project) => {
      if (project.project_type !== 'batch_tryon') throw new Error('目标项目不是批量套图项目。')
      const current = useStore.getState().batchTryOnBatch
      const currentTemplates = current?.serverProjectId === project.id ? current.templates || [] : []
      const currentGarments = current?.serverProjectId === project.id ? current.garments || [] : []
      const draft = project.latest_version.draft_json
      const savedTemplateGarmentViews = readTemplateGarmentViews(draft)
      const seenTemplateHashes = new Set<string>()
      const templateLinks = project.assets.filter((link) => {
        if (link.role !== 'model_template') return false
        const contentKey = link.asset.sha256 || link.asset.id
        if (seenTemplateHashes.has(contentKey)) return false
        seenTemplateHashes.add(contentKey)
        return true
      })
      const templates: BatchTryOnTemplate[] = []
      for (const [index, link] of templateLinks.entries()) {
        const cached = currentTemplates.find((item) => item.serverAssetId === link.asset.id)
        let imageId = cached?.imageId
        if (!imageId || !await ensureImageCached(imageId)) imageId = await importServerAsset(link.asset)
        templates.push({
          id: cached?.id || createId(),
          imageId,
          serverAssetId: link.asset.id,
          projectAssetLinkId: link.id,
          fileName: link.asset.filename,
          displayName: cached?.displayName || link.display_name || stripExtension(link.asset.filename),
          width: link.asset.width,
          height: link.asset.height,
          selected: cached?.selected ?? true,
          isDefault: cached?.isDefault ?? link.is_default ?? index === 0,
          sourceType: cached?.sourceType || (project.latest_version.draft_json.template_source_type === 'listing_generated_output' ? 'listing_generated_output' : 'upload'),
          sourceId: cached?.sourceId,
          garmentView: cached?.garmentView || savedTemplateGarmentViews[link.asset.id] || 'auto',
        })
      }
      const linkedTemplateAssetIds = new Set(templateLinks.map((link) => link.asset.id))
      const pendingLocalTemplates: BatchTryOnTemplate[] = []
      for (const template of currentTemplates) {
        if (template.serverAssetId && linkedTemplateAssetIds.has(template.serverAssetId)) continue
        if (await ensureImageCached(template.imageId)) pendingLocalTemplates.push(template)
      }
      if (pendingLocalTemplates.length) {
        templates.push(...await persistBatchTryOnTemplates(project, pendingLocalTemplates))
      }
      const seenGarmentHashes = new Set<string>()
      const garmentLinks = project.assets.filter((link) => {
        if (link.role !== 'garment') return false
        const contentKey = link.asset.sha256 || link.asset.id
        if (seenGarmentHashes.has(contentKey)) return false
        seenGarmentHashes.add(contentKey)
        return true
      })
      const garments: BatchTryOnGarment[] = []
      for (const [index, link] of garmentLinks.entries()) {
        const cached = currentGarments.find((item) => item.serverAssetId === link.asset.id)
        let imageId = cached?.garmentImageId
        if (!imageId || !await ensureImageCached(imageId)) imageId = await importServerAsset(link.asset)
        garments.push({
          id: cached?.id || createId(),
          batchId: project.id,
          garmentImageId: imageId,
          serverAssetId: link.asset.id,
          projectAssetLinkId: link.id,
          garmentFileName: link.asset.filename,
          index,
          selected: cached?.selected ?? true,
          createdAt: cached?.createdAt ?? new Date(link.created_at).getTime(),
          references: cached?.references,
        })
      }
      const derivedLinks = project.assets.filter((link) => link.role.startsWith('garment_reference.'))
      for (const link of derivedLinks) {
        const sourceAssetId = link.asset.source_asset_id || String(link.asset.metadata_json?.source_asset_id || '')
        const garmentView = String(link.asset.metadata_json?.garment_view || link.role.split('.')[1] || '')
        if (!sourceAssetId || !['front', 'back', 'detail'].includes(garmentView)) continue
        const garment = garments.find((item) => item.serverAssetId === sourceAssetId)
        if (!garment) continue
        const cached = garment.references?.[garmentView as 'front' | 'back' | 'detail']
        let imageId = cached?.imageId
        if (!imageId || !await ensureImageCached(imageId)) imageId = await importServerAsset(link.asset)
        garment.references = {
          ...garment.references,
          [garmentView]: {
            imageId,
            serverAssetId: link.asset.id,
            projectAssetLinkId: link.id,
            sourceAssetId,
            fileName: link.asset.filename,
            garmentView,
            transform: (link.asset.metadata_json || {}).transform as BatchTryOnGarmentReference['transform'] || cached?.transform || {
              mode: 'crop', crop: { x: 0, y: 0, width: 1, height: 1 }, eraseStrokes: [],
            },
          },
        }
      }
      if (cancelled) return
      const defaultTemplate = templates.find((item) => item.isDefault) || templates[0]
      const latestWorkflowCandidate = await getLatestBatchTryOnWorkflow(project.id).catch(() => null)
      const latestWorkflow = latestWorkflowCandidate && shouldRestoreBatchTryOnWorkflow(
        latestWorkflowCandidate.created_at,
        current?.serverProjectId === project.id ? current.queueClearedAt : undefined,
      ) ? latestWorkflowCandidate : null
      if (latestWorkflow) {
        for (const workflowTemplate of latestWorkflow.templates) {
          const template = templates.find((item) => item.serverAssetId === workflowTemplate.asset_id)
          if (template && !savedTemplateGarmentViews[workflowTemplate.asset_id]) {
            template.garmentView = workflowTemplate.garment_view || 'auto'
          }
        }
      }
      const latestWorkflowLooksOneToOne = Boolean(
        latestWorkflow
        && latestWorkflow.templates.length > 1
        && latestWorkflow.templates.length === latestWorkflow.garments.length
        && latestWorkflow.combinations.length === latestWorkflow.templates.length
        && new Set(latestWorkflow.combinations.map((item) => item.template_id)).size === latestWorkflow.templates.length
        && new Set(latestWorkflow.combinations.map((item) => item.garment_id)).size === latestWorkflow.garments.length,
      )
      const fontReferenceLinks = new Map(project.assets.filter((link) => link.role === 'font_reference').map((link) => [link.asset.id, link]))
      const fontReferenceImageIds = new Map<string, string>()
      const restoreFontReference = async (assetId: string) => {
        const link = fontReferenceLinks.get(assetId)
        if (!link) return undefined
        let imageId = fontReferenceImageIds.get(assetId)
        if (!imageId) {
          imageId = await importServerAsset(link.asset)
          fontReferenceImageIds.set(assetId, imageId)
        }
        return { imageId, serverAssetId: assetId, fileName: link.asset.filename }
      }
      if (latestWorkflow) {
        for (const workflowGarment of latestWorkflow.garments) {
          if (!workflowGarment.font_reference_asset_id) continue
          const garment = garments.find((item) => item.serverAssetId === workflowGarment.asset_id)
          const reference = await restoreFontReference(workflowGarment.font_reference_asset_id)
          if (garment && reference) garment.fontReference = reference
        }
      }
      const recoveredFontReferenceOverrides: NonNullable<BatchTryOnBatch['fontReferenceOverrides']> = {}
      if (latestWorkflow) {
        for (const combination of latestWorkflow.combinations) {
          if (!combination.font_reference_asset_id) continue
          const template = templates.find((item) => item.serverAssetId === latestWorkflow.templates.find((entry) => entry.template_id === combination.template_id)?.asset_id)
          const garment = garments.find((item) => item.serverAssetId === latestWorkflow.garments.find((entry) => entry.garment_id === combination.garment_id)?.asset_id)
          const reference = await restoreFontReference(combination.font_reference_asset_id)
          if (template && garment && reference) recoveredFontReferenceOverrides[batchTryOnFontReferenceKey(template.id, garment.id)] = reference
        }
      }
      setPromptMode(latestWorkflow?.prompt_mode || 'direct')
      setTemplateAnalysisProfiles(latestWorkflow
        ? withWorkflowTemplateNames(latestWorkflow.template_profiles, latestWorkflow.templates)
        : {})
      setTemplatePromptRecords(latestWorkflow?.template_prompts || [])
      setPromptWorkflowStatus(latestWorkflow?.status || null)
      const latestPrompt = latestWorkflow?.template_prompts?.[0]
      if (latestPrompt) {
        const workflowDrafts = restoreWorkflowPromptDrafts(latestWorkflow!.template_prompts, templates)
        const mergedDrafts = { ...workflowDrafts, ...templatePromptDraftsRef.current }
        templatePromptDraftsRef.current = mergedDrafts
        setTemplatePromptDrafts(mergedDrafts)
      }
      const recoveredItems: BatchTryOnItem[] = latestWorkflow?.combinations.map((combination, index) => {
        const workflowTemplate = latestWorkflow.templates.find((item) => item.template_id === combination.template_id)
        const workflowGarment = latestWorkflow.garments.find((item) => item.garment_id === combination.garment_id)
        const template = templates.find((item) => item.serverAssetId === workflowTemplate?.asset_id)
        const garment = garments.find((item) => item.serverAssetId === workflowGarment?.asset_id)
        return {
          id: combination.client_item_id,
          batchId: project.id,
          templateId: template?.id || combination.template_id,
          templateImageId: template?.imageId,
          templateServerAssetId: workflowTemplate?.asset_id,
          templateName: workflowTemplate?.name || template?.displayName,
          templateOrder: workflowTemplate?.order || 0,
          templateCount: latestWorkflow.templates.length,
          garmentId: garment?.id || combination.garment_id,
          garmentImageId: garment?.garmentImageId || '',
          garmentServerAssetId: workflowGarment?.asset_id,
          garmentFileName: workflowGarment?.filename || garment?.garmentFileName || 'garment.png',
          index,
          serverBatchId: latestWorkflow.batch_id || undefined,
          status: 'queued',
          createdAt: new Date(latestWorkflow.created_at).getTime(),
        }
      }) || []
      setBatch((latest) => {
        const sameProject = latest?.serverProjectId === project.id
        const base = sameProject && latest ? latest : createEmptyBatch(globalParams)
        const latestWorkflowIsCurrent = Boolean(
          latestWorkflow && base.serverWorkflowId === latestWorkflow.workflow_job_id,
        )
        const currentItemIds = new Set(base.items.map((item) => item.id))
        const latestWorkflowItemsAreCurrent = latestWorkflowIsCurrent
          && base.items.length === recoveredItems.length
          && recoveredItems.every((item) => currentItemIds.has(item.id))
        const shouldAdoptLatestWorkflow = Boolean(latestWorkflow && !latestWorkflowItemsAreCurrent)
        return {
          ...base,
          id: project.id,
          serverProjectId: project.id,
          serverProjectName: project.name,
          serverWorkflowId: latestWorkflow?.workflow_job_id || (sameProject ? base.serverWorkflowId : undefined),
          serverBatchId: latestWorkflow?.batch_id
            || (sameProject && latestWorkflowIsCurrent ? base.serverBatchId : undefined),
          serverBatchIds: sameProject
            ? appendTrackedServerBatchId(base.serverBatchIds, latestWorkflow?.batch_id || undefined)
            : appendTrackedServerBatchId([], latestWorkflow?.batch_id || undefined),
          generationMode: sameProject ? base.generationMode : latestWorkflow?.generation_mode || 'normal_tryon',
          combinationMode: sameProject
            ? base.combinationMode
            : draft.combination_mode === 'one_to_one' || latestWorkflowLooksOneToOne
              ? 'one_to_one'
              : 'cartesian',
          templateImageId: defaultTemplate?.imageId,
          templateServerAssetId: defaultTemplate?.serverAssetId,
          templateFileName: defaultTemplate?.fileName,
          templateWidth: defaultTemplate?.width,
          templateHeight: defaultTemplate?.height,
          templateSourceType: draft.template_source_type === 'listing_generated_output' ? 'listing_generated_output' : 'upload',
          templateSourceId: typeof draft.template_source_id === 'string' ? draft.template_source_id : undefined,
          templates,
          garments,
          sampleGarmentId: sameProject && garments.some((item) => item.id === base.sampleGarmentId)
            ? base.sampleGarmentId
            : garments[0]?.id,
          fontReferenceOverrides: sameProject && !shouldAdoptLatestWorkflow && Object.keys(base.fontReferenceOverrides || {}).length
            ? base.fontReferenceOverrides
            : recoveredFontReferenceOverrides,
          styleProfiles: sameProject && !shouldAdoptLatestWorkflow && base.styleProfiles?.length
            ? base.styleProfiles
            : latestWorkflow?.garment_profile
              ? [restoreWorkflowStyleProfile(latestWorkflow.garment_profile, garments)]
              : [],
          items: sameProject && !shouldAdoptLatestWorkflow && base.items.length ? base.items : recoveredItems,
          queuePaused: true,
          updatedAt: Date.now(),
        }
      })
      if (templateUpdated) {
        showToast('已将 Listing 生成图设为当前批量套图模板。', 'success')
      }
      completed = true
      window.setTimeout(() => document.getElementById('batch-tryon-garments')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 150)
    }).catch((error) => {
      loadedProjectRef.current = null
      if (!cancelled) showToast(friendlyError(error), 'error')
    })
    return () => {
      cancelled = true
      if (!completed && loadedProjectRef.current === projectId) loadedProjectRef.current = null
    }
  }, [globalParams, projectId, setBatch, showToast, templateUpdated])

  useEffect(() => {
    if (!batch) setBatch(createEmptyBatch(globalParams))
  }, [batch, globalParams, setBatch])

  useEffect(() => {
    if (!batch) return
    const needsNormalization = !Array.isArray(batch.templates)
      || !Array.isArray(batch.garments)
      || !batch.presetSelection
      || typeof batch.adminTestMode !== 'boolean'
      || (batch.combinationMode !== 'cartesian' && batch.combinationMode !== 'one_to_one')
      || (batch.garments.length > 0 && !batch.garments.some((item) => item.id === batch.sampleGarmentId))
    if (needsNormalization) setBatch(normalizeBatchTryOnBatch(batch))
  }, [batch, setBatch])

  useEffect(() => {
    if (!batch) return
    setBatch((current) => {
      if (!current || current.id !== batch.id) return current
      let changed = false
      const items = current.items.map((item) => {
        if (!item.taskId) return item
        const task = tasks.find((candidate) => candidate.id === item.taskId)
        if (!task) return item
        if (task.status === 'done' && task.outputImages[0]) {
          if (item.status === 'done' && item.outputImageId === task.outputImages[0]) return item
          changed = true
          return { ...item, status: 'done' as const, outputImageId: task.outputImages[0], error: undefined, finishedAt: task.finishedAt ?? Date.now() }
        }
        if (task.status === 'error' && !task.falRecoverable && !task.customRecoverable) {
          if (item.status === 'error' && item.error === task.error) return item
          changed = true
          return { ...item, status: 'error' as const, error: task.error || '生成失败，请重试。', finishedAt: task.finishedAt ?? Date.now() }
        }
        return item
      })
      return changed ? { ...current, items, updatedAt: Date.now() } : current
    })
  }, [batch?.id, tasks, setBatch])

  const profileError = runtimeConfig.isStandalone ? getBatchTryOnProfileError(settings) : null
  const progress = useMemo(() => summarizeItems(batch?.items ?? []), [batch?.items])
  const selectedTemplates = useMemo(() => (batch?.templates ?? []).filter((item) => item.selected), [batch?.templates])
  const selectedGarments = useMemo(() => (batch?.garments ?? []).filter((item) => item.selected), [batch?.garments])
  const generationTemplates = useMemo(() => runtimeConfig.isStandalone
    ? selectedTemplates
    : selectedTemplates.filter((template) => template.validationStatus === 'approved'), [selectedTemplates])
  const generationBatch = useMemo(() => batch ? {
    ...batch,
    templates: batch.templates.map((template) => ({
      ...template,
      selected: runtimeConfig.isStandalone
        ? template.selected
        : Boolean(template.selected && template.validationStatus === 'approved'),
    })),
  } : null, [batch])
  const validationGenerationTargets = useMemo(() => selectedTemplates.filter((template) => (
    !['generating', 'pending_review', 'approved'].includes(template.validationStatus || 'not_generated')
  )), [selectedTemplates])
  const validationPromptMissingTemplates = useMemo(() => validationGenerationTargets.filter((template) => {
    const config = templatePromptDrafts[template.id]
    return !config?.presetId || !config.analysisPrompt.trim()
  }), [templatePromptDrafts, validationGenerationTargets])
  const generateAllValidationDisabledReason = !selectedTemplates.length
    ? '请先选择至少一个模板'
    : !(batch?.sampleGarmentId || selectedGarments.length)
      ? '请先选择样图商品'
      : validationPromptMissingTemplates.length
        ? `请先配置提示词预设：${validationPromptMissingTemplates.map((template) => template.displayName).join('、')}`
        : validationGenerationTargets.length === 0
          ? '当前没有需要生成的样图'
          : ''
  useEffect(() => {
    if (!promptPresets.length || !selectedTemplates.length) return
    const fallback = promptPresets.find((preset) => preset.template_type === 'pure_white') || promptPresets[0]
    if (!fallback) return
    let changed = false
    const next = { ...templatePromptDraftsRef.current }
    for (const template of selectedTemplates) {
      if (next[template.id]) continue
      next[template.id] = {
        templateType: fallback.template_type,
        presetId: fallback.id,
        analysisPrompt: fallback.analysis_prompt_template,
      }
      changed = true
    }
    if (!changed) return
    templatePromptDraftsRef.current = next
    setTemplatePromptDrafts(next)
    setBatch((current) => current ? {
      ...current,
      templatePromptConfigs: next,
      updatedAt: Date.now(),
    } : current)
    if (batch?.serverWorkspaceId) persistWorkspaceBatch(batch.serverWorkspaceId)
  }, [batch?.serverWorkspaceId, persistWorkspaceBatch, promptPresets, selectedTemplates, setBatch])
  const combinationPairs = useMemo(() => generationBatch ? getBatchTryOnCombinationPairs(generationBatch) : [], [generationBatch])
  const pendingGenerationPairs = useMemo(() => generationBatch
    ? getUnsubmittedBatchTryOnCombinationPairs(generationBatch, batch?.items || [])
    : [], [batch?.items, generationBatch])
  const pendingGenerationTemplateIds = useMemo(() => new Set(
    pendingGenerationPairs.map(({ template }) => template.id),
  ), [pendingGenerationPairs])
  const pendingGenerationTemplates = useMemo(() => generationTemplates.filter(
    (template) => pendingGenerationTemplateIds.has(template.id),
  ), [generationTemplates, pendingGenerationTemplateIds])
  const estimatedGenerationCount = pendingGenerationPairs.length
  const combinationError = generationBatch ? getBatchTryOnCombinationError(generationBatch) : ''
  const pairedFontReferenceCount = useMemo(() => {
    if (!batch) return 0
    return combinationPairs.filter(({ template, garment }) => Boolean(
      batch.fontReferenceOverrides?.[batchTryOnFontReferenceKey(template.id, garment.id)] || garment.fontReference,
    )).length
  }, [batch, combinationPairs])
  const outputSize = batch ? resolveOutputSize(batch) : 'auto'
  const isRunning = progress.running + progress.queued + progress.retry_waiting > 0
    || Boolean(batch && !batch.queuePaused && progress.pending > 0)
  const configurationLocked = isBatchTryOnConfigurationLocked(
    runtimeConfig.isStandalone,
    isRunning,
    matrixSubmitting,
  )
  const promptSubmissionLocked = !runtimeConfig.isStandalone && (
    promptWorkflowStatus === 'analyzing_prompts' || promptWorkflowStatus === 'awaiting_prompt_confirmation'
  )
  const startDisabledReason = generationTemplates.length === 0
    ? (runtimeConfig.isStandalone ? '请至少选择一张模特模板图' : '请至少勾选一个已通过样图验证的模板')
    : selectedGarments.length === 0
      ? '请至少选择一张待套服装'
      : estimatedGenerationCount > MAX_BATCH_TRY_ON_MATRIX_ITEMS
        ? `本次组合不能超过 ${MAX_BATCH_TRY_ON_MATRIX_ITEMS} 张`
      : combinationError
        ? combinationError
      : estimatedGenerationCount === 0
        ? '当前已通过模板的组合都已提交，不需要重复生成'
      : profileError
        ? profileError
        : ''

  const updateBatch = (patch: Partial<BatchTryOnBatch>) => {
    setBatch((current) => current ? { ...current, ...patch, updatedAt: Date.now() } : current)
  }

  const switchWorkspaceTab = (tab: BatchTryOnWorkspaceTab) => {
    if (tab.id === batch?.serverWorkspaceId) return
    const saved = tab.config.batch as BatchTryOnBatch | undefined
    const next = saved ? normalizeBatchTryOnBatch({
      ...saved,
      serverWorkspaceId: tab.id,
      serverProjectId: tab.project_id || batch?.serverProjectId,
      serverProjectName: batch?.serverProjectName,
    }) : {
      ...createEmptyBatch(globalParams),
      serverWorkspaceId: tab.id,
      serverProjectId: tab.project_id || batch?.serverProjectId,
      serverProjectName: batch?.serverProjectName,
    }
    switchingWorkspaceRef.current = true
    workspaceHydratedRef.current = tab.id
    stopBatchTryOnWorkflowPolling()
    stopServerPolling()
    setBatch(next)
    setTemplatePromptRecords([])
    setPromptWorkflowStatus(null)
    const projectId = tab.project_id || batch?.serverProjectId
    if (projectId) {
      void getLatestBatchTryOnWorkflow(projectId, tab.id).then((workflow) => {
        const currentBatch = useStore.getState().batchTryOnBatch
        if (!shouldRestoreBatchTryOnWorkflow(workflow.created_at, currentBatch?.queueClearedAt)) return
        const validationTemplateId = resolveValidationWorkflowTemplateId(workflow)
        if (validationTemplateId) validationWorkflowTemplateRef.current.set(workflow.workflow_job_id, validationTemplateId)
        workflowItemIdsRef.current.set(
          workflow.workflow_job_id,
          new Set(workflow.combinations.map((item) => item.client_item_id)),
        )
        setTemplatePromptRecords(workflow.template_prompts || [])
        setPromptWorkflowStatus(workflow.status)
        setBatch((current) => current?.serverWorkspaceId === tab.id ? {
          ...current,
          serverWorkflowId: workflow.workflow_job_id,
          serverBatchId: workflow.batch_id || current.serverBatchId,
          serverBatchIds: appendTrackedServerBatchId(current.serverBatchIds, workflow.batch_id || undefined),
          queuePaused: !workflow.batch_id,
          updatedAt: Date.now(),
        } : current)
        if (workflow.batch_id) void pollServerBatch(workflow.batch_id)
        else void pollBatchTryOnWorkflow(workflow.workflow_job_id)
      }).catch(() => undefined)
    }
    queueMicrotask(() => { switchingWorkspaceRef.current = false })
  }

  const createWorkspaceTab = async () => {
    if (!batch?.serverProjectId || workspaceTabsBusy) return
    try {
      setWorkspaceTabsBusy(true)
      // Save the current tab before switching. Otherwise the pending 700 ms
      // autosave is cancelled by the workspace switch and the old workspace
      // can look as if it was replaced by the newly created one.
      if (workspaceSaveTimerRef.current) {
        window.clearTimeout(workspaceSaveTimerRef.current)
        workspaceSaveTimerRef.current = null
      }
      if (batch.serverWorkspaceId) await persistWorkspaceBatch(batch.serverWorkspaceId, batch)
      const empty = { ...createEmptyBatch(globalParams), serverProjectId: batch.serverProjectId, serverProjectName: batch.serverProjectName }
      const created = await createBatchTryOnWorkspace(batch.serverProjectId, undefined, { batch: empty, concurrency: empty.concurrency })
      suppressedWorkspaceIdsRef.current.delete(created.id)
      setWorkspaceTabs((items) => mergeWorkspaceTabs(items, [created], suppressedWorkspaceIdsRef.current))
      switchWorkspaceTab(created)
      const refreshed = await listBatchTryOnWorkspaces(batch.serverProjectId)
      setWorkspaceTabs((items) => mergeWorkspaceTabs(items, refreshed.items, suppressedWorkspaceIdsRef.current))
    } catch (error) {
      showToast(friendlyError(error), 'error')
    } finally {
      setWorkspaceTabsBusy(false)
    }
  }

  const renameWorkspaceTab = async (tab: BatchTryOnWorkspaceTab, value: string) => {
    const name = value.trim()
    if (!name || name === tab.name) return
    try {
      const saved = await updateBatchTryOnWorkspace(tab.id, { name })
      setWorkspaceTabs((items) => items.map((item) => item.id === saved.id ? saved : item))
    } catch (error) {
      showToast(friendlyError(error), 'error')
      throw error
    }
  }

  const removeWorkspaceDraft = async (tab: BatchTryOnWorkspaceTab) => {
    if (!window.confirm(`删除草稿“${tab.name}”？此操作不会删除项目素材。`)) return
    try {
      suppressedWorkspaceIdsRef.current.add(tab.id)
      await deleteBatchTryOnWorkspace(tab.id)
      const remaining = workspaceTabs.filter((item) => item.id !== tab.id)
      setWorkspaceTabs(remaining)
      if (batch?.serverWorkspaceId === tab.id && remaining[0]) switchWorkspaceTab(remaining[0])
    } catch (error) {
      suppressedWorkspaceIdsRef.current.delete(tab.id)
      showToast(friendlyError(error), 'error')
    }
  }

  const hardDeleteWorkspaceTab = async (tab: BatchTryOnWorkspaceTab) => {
    if (!window.confirm(
      `永久删除“${tab.name}”？\n\n该标签下的验证批次、正式生成任务、审核版本和专属生成图片都会被清除。原始模板、服装、额度流水和审计日志会保留。`,
    )) return
    if (!window.confirm('这是不可恢复操作。确定要永久删除整个批次吗？')) return
    try {
      setWorkspaceTabsBusy(true)
      suppressedWorkspaceIdsRef.current.add(tab.id)
      if (workspaceSaveTimerRef.current && batch?.serverWorkspaceId === tab.id) {
        window.clearTimeout(workspaceSaveTimerRef.current)
        workspaceSaveTimerRef.current = null
      }
      workspaceSaveRevisionRef.current.set(tab.id, (workspaceSaveRevisionRef.current.get(tab.id) || 0) + 1)
      // Let an already-running autosave finish before deleting. The revision bump above
      // prevents queued saves from recreating stale workspace state afterwards.
      await workspaceSaveChainRef.current.catch(() => undefined)
      const result = await hardDeleteBatchTryOnWorkspace(tab.id)
      let remaining = workspaceTabs.filter((item) => item.id !== tab.id)
      setWorkspaceTabs(remaining)
      if (batch?.serverWorkspaceId === tab.id) {
        stopBatchTryOnWorkflowPolling()
        stopServerPolling()
        if (!remaining.length && batch.serverProjectId) {
          const empty = {
            ...createEmptyBatch(globalParams),
            serverProjectId: batch.serverProjectId,
            serverProjectName: batch.serverProjectName,
          }
          const created = await createBatchTryOnWorkspace(
            batch.serverProjectId,
            undefined,
            { batch: empty, concurrency: empty.concurrency },
          )
          remaining = [created]
          setWorkspaceTabs(remaining)
        }
        if (remaining[0]) switchWorkspaceTab(remaining[0])
      }
      const retained = result.retained_shared_assets ? `，保留 ${result.retained_shared_assets} 个共享素材` : ''
      showToast(`已永久删除 ${result.deleted_batches} 个关联批次、${result.deleted_jobs} 个任务和 ${result.deleted_assets} 张专属生成图片${retained}`, 'success')
    } catch (error) {
      suppressedWorkspaceIdsRef.current.delete(tab.id)
      showToast(friendlyError(error), 'error')
    } finally {
      setWorkspaceTabsBusy(false)
    }
  }

  const updateItem = (batchId: string, itemId: string, patch: Partial<BatchTryOnItem>) => {
    setBatch((current) => current?.id === batchId
      ? { ...current, items: current.items.map((item) => item.id === itemId ? { ...item, ...patch } : item), updatedAt: Date.now() }
      : current)
  }

  const runItem = async (itemId: string) => {
    const current = useStore.getState().batchTryOnBatch
    const item = current?.items.find((candidate) => candidate.id === itemId)
    if (!current || !item?.templateImageId) return
    const batchId = current.id
    const startedAt = Date.now()
    const size = resolveOutputSize(current)
    const aspectRatio = resolveOutputAspectRatio(current)
    const garment = current.garments.find((candidate) => candidate.id === item.garmentId)
    const template = current.templates.find((candidate) => candidate.id === item.templateId)
    const garmentReferenceImageIds = template?.garmentView === 'front'
      ? [garment?.references?.front?.imageId || item.garmentImageId]
      : template?.garmentView === 'back'
        ? [garment?.references?.back?.imageId || item.garmentImageId]
        : template?.garmentView === 'detail'
          ? [garment?.references?.detail?.imageId || item.garmentImageId]
          : template?.garmentView === 'front_back'
            ? [garment?.references?.front?.imageId, garment?.references?.back?.imageId].filter((id): id is string => Boolean(id)).length
              ? [garment?.references?.front?.imageId, garment?.references?.back?.imageId].filter((id): id is string => Boolean(id))
              : [item.garmentImageId]
            : [item.garmentImageId]
    updateItem(batchId, itemId, { status: 'running', error: undefined, outputImageId: undefined, startedAt, finishedAt: undefined })

    try {
      const task = await runBatchTryOnTask({
        batchId,
        garmentFileName: item.garmentFileName,
        index: item.index,
        templateImageId: item.templateImageId,
        garmentImageId: item.garmentImageId,
        garmentReferenceImageIds,
        prompt: buildBatchTryOnPrompt({
          garmentFileName: item.garmentFileName,
          templateName: item.templateName,
          outputSize: size,
          presetSelection: item.presetSelection || current.presetSelection,
          extraRequirements: current.extraRequirements,
        }),
        params: { ...current.params, size, aspect_ratio: aspectRatio, n: 1 },
        onTaskCreated: (taskId) => updateItem(batchId, itemId, { taskId }),
      })
      if (task.status === 'done' && task.outputImages[0]) {
        updateItem(batchId, itemId, { status: 'done', taskId: task.id, outputImageId: task.outputImages[0], error: undefined, finishedAt: task.finishedAt ?? Date.now() })
      } else {
        updateItem(batchId, itemId, { status: 'error', taskId: task.id, error: task.error || '接口没有返回图片，请重试。', finishedAt: task.finishedAt ?? Date.now() })
      }
    } catch (error) {
      updateItem(batchId, itemId, { status: 'error', error: friendlyError(error), finishedAt: Date.now() })
    }
  }

  const getRunner = () => {
    const concurrency = useStore.getState().batchTryOnBatch?.concurrency ?? 12
    if (!runnerRef.current) runnerRef.current = new BatchTryOnQueueController(runItem, concurrency)
    runnerRef.current.setConcurrency(concurrency)
    return runnerRef.current
  }

  const startServerWorkflowItems = async (
    itemIds: string[],
    options: { promptMode?: BatchTryOnPromptMode; submissionKind?: 'validation' | 'production'; validationTemplateId?: string } = {},
  ) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    const isValidation = options.submissionKind === 'validation'
    if (!isValidation) setMatrixSubmitting(true)
    try {
      const selectedItems = current.items.filter((item) => itemIds.includes(item.id))
      let project = current.serverProjectId
        ? await getProject(current.serverProjectId)
        : await createProject({
            project_type: 'batch_tryon',
            name: current.serverProjectName || `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
            draft: {
              preset_selection: current.presetSelection,
              concurrency: current.concurrency,
              admin_test_mode: false,
              generation_mode: current.generationMode || 'normal_tryon',
              combination_mode: current.combinationMode || 'cartesian',
            },
          })
      const links = new Map(project.assets.map((link) => [`${link.role}:${link.asset.id}`, link.id]))
      const templateAssets = new Map<string, string>()
      const garmentAssets = new Map<string, string>()
      const fontReferenceAssets = new Map<string, string>()
      const prepared: Array<{
        item: BatchTryOnItem
        templateAssetId: string
        garmentAssetId: string
        garmentFontReferenceAssetId?: string
        combinationFontReferenceAssetId?: string
        frontReferenceAssetId?: string
        backReferenceAssetId?: string
        detailReferenceAssetId?: string
        size: string
        aspectRatio: string
      }> = []

      for (const item of selectedItems) {
        const template = current.templates.find((candidate) => candidate.id === item.templateId)
        if (!item.templateImageId) throw new Error(`${item.templateName || '模板图'}读取失败，请重新上传。`)
        const templateImageId = item.templateImageId
        const templateKey = item.templateId || item.templateImageId
        const templateAssetId = await resolveBatchTryOnAssetId(
          templateAssets,
          templateKey,
          item.templateServerAssetId || template?.serverAssetId,
          async () => {
            const dataUrl = await ensureImageCached(templateImageId)
            if (!dataUrl) throw new Error(`${item.templateName || '模板图'}读取失败，请重新上传。`)
            return (await uploadDataUrlAsset(dataUrl, 'model_template', item.templateName || 'model-template')).id
          },
        )
        if (!links.has(`model_template:${templateAssetId}`)) {
          project = await linkProjectAsset(
            project.id, templateAssetId, 'model_template', template?.isDefault ? 0 : (item.templateOrder || 0),
            template?.displayName || item.templateName, Boolean(template?.isDefault),
          )
          const link = project.assets.find((candidate) => candidate.role === 'model_template' && candidate.asset.id === templateAssetId)
          if (link) links.set(`model_template:${templateAssetId}`, link.id)
        }

        const garment = current.garments.find((candidate) => candidate.id === item.garmentId)
        const garmentKey = item.garmentId || item.garmentImageId
        const garmentAssetId = await resolveBatchTryOnAssetId(
          garmentAssets,
          garmentKey,
          item.garmentServerAssetId || garment?.serverAssetId,
          async () => {
            const dataUrl = await ensureImageCached(item.garmentImageId)
            if (!dataUrl) throw new Error(`${item.garmentFileName}读取失败，请重新上传。`)
            return (await uploadDataUrlAsset(dataUrl, 'garment', item.garmentFileName)).id
          },
        )
        if (!links.has(`garment:${garmentAssetId}`)) {
          project = await linkProjectAsset(
            project.id, garmentAssetId, 'garment', garment?.index ?? item.index, item.garmentFileName,
          )
          const link = project.assets.find((candidate) => candidate.role === 'garment' && candidate.asset.id === garmentAssetId)
          if (link) links.set(`garment:${garmentAssetId}`, link.id)
        }
        const combinationKey = batchTryOnFontReferenceKey(
          item.templateId || item.templateImageId || item.id,
          item.garmentId || item.garmentImageId,
        )
        const garmentFontReference = garment?.fontReference
        const combinationFontReference = current.fontReferenceOverrides?.[combinationKey]
        const uploadFontReference = async (reference: NonNullable<typeof garmentFontReference>) => {
          const assetId = await resolveBatchTryOnAssetId(
            fontReferenceAssets,
            reference.imageId,
            reference.serverAssetId,
            async () => {
              const dataUrl = await ensureImageCached(reference.imageId)
              if (!dataUrl) throw new Error(`${reference.fileName}读取失败，请重新上传。`)
              return (await uploadDataUrlAsset(dataUrl, 'style_reference', reference.fileName)).id
            },
          )
          if (!links.has(`font_reference:${assetId}`)) {
            project = await linkProjectAsset(project.id, assetId, 'font_reference', 0, reference.fileName)
            const link = project.assets.find((candidate) => candidate.role === 'font_reference' && candidate.asset.id === assetId)
            if (link) links.set(`font_reference:${assetId}`, link.id)
          }
          return assetId
        }
        const garmentFontReferenceAssetId = garmentFontReference
          ? await uploadFontReference(garmentFontReference)
          : undefined
        const combinationFontReferenceAssetId = combinationFontReference
          ? await uploadFontReference(combinationFontReference)
          : undefined
        const uploadDerivedReference = async (reference: BatchTryOnGarmentReference | undefined) => {
          if (!reference) return undefined
          if (!reference.serverAssetId) throw new Error(`${item.garmentFileName}的${reference.garmentView}参考图尚未保存，请重新执行裁剪/遮罩。`)
          return reference.serverAssetId
        }
        prepared.push({
          item,
          templateAssetId,
          garmentAssetId,
          garmentFontReferenceAssetId,
          combinationFontReferenceAssetId,
          frontReferenceAssetId: await uploadDerivedReference(garment?.references?.front),
          backReferenceAssetId: await uploadDerivedReference(garment?.references?.back),
          detailReferenceAssetId: await uploadDerivedReference(garment?.references?.detail),
          size: resolveOutputSizeForTemplate(current, template),
          aspectRatio: resolveOutputAspectRatioForTemplate(current, template),
        })
      }

      const templates = Array.from(new Map(prepared.map((entry) => {
        const template = current.templates.find((candidate) => candidate.id === entry.item.templateId)
        const id = entry.item.templateId || entry.item.templateImageId || entry.item.id
        const promptConfig = templatePromptDraftsRef.current[id]
        const lockedPrompt = options.submissionKind !== 'validation' && template?.promptStrategy !== 'luna_per_image'
          ? template?.validatedPrompt
          : undefined
        const promptText = lockedPrompt || promptConfig?.analysisPrompt.trim()
        if (!promptText) throw new Error(`${entry.item.templateName || '模板'}尚未配置可用提示词。`)
        return [id, {
          template_id: id,
          asset_id: entry.templateAssetId,
          name: entry.item.templateName || template?.displayName || 'model-template',
          order: entry.item.templateOrder || 0,
          focus_area: current.generationMode === 'detail_tryon' ? (template?.focusArea || 'garment_detail') : template?.focusArea,
          crop_type: template?.cropType,
          detail_priority: template?.detailPriority,
          visible_regions: template?.visibleRegions,
          template_type: promptConfig.templateType,
          prompt_preset_id: promptConfig.presetId || undefined,
          analysis_prompt: promptText,
          garment_view: template?.garmentView || 'auto',
          prompt_strategy: template?.promptStrategy,
        }]
      })).values())
      const garments = Array.from(new Map(prepared.map((entry) => {
        const id = entry.item.garmentId || entry.item.garmentImageId
        return [id, {
          garment_id: id,
          asset_id: entry.garmentAssetId,
          filename: entry.item.garmentFileName,
          order: current.garments.find((garment) => garment.id === entry.item.garmentId)?.index ?? entry.item.index,
          font_reference_asset_id: entry.garmentFontReferenceAssetId,
          front_reference_asset_id: entry.frontReferenceAssetId,
          back_reference_asset_id: entry.backReferenceAssetId,
          detail_reference_asset_id: entry.detailReferenceAssetId,
        }]
      })).values())
      if (!isValidation) {
        setTemplateAnalysisProfiles({})
        setTemplatePromptRecords([])
        setPromptWorkflowStatus('analyzing_prompts')
      }
      const effectivePromptMode = options.promptMode || promptMode
      let workflow = await createBatchTryOnWorkflow({
        project_id: project.id,
        name: `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
        idempotency_key: `batch-workflow:${randomUuid()}`,
        generation_mode: current.generationMode || 'normal_tryon',
        prompt_mode: effectivePromptMode,
        templates,
        garments,
        combinations: prepared.map((entry, index) => {
          const dimensions = /^(\d+)x(\d+)$/.exec(entry.size)
          return {
            client_item_id: entry.item.id,
            template_id: entry.item.templateId || entry.item.templateImageId || entry.item.id,
            garment_id: entry.item.garmentId || entry.item.garmentImageId,
            order: index,
            size: entry.size,
            aspect_ratio: entry.aspectRatio,
            requested_width: dimensions ? Number(dimensions[1]) : undefined,
            requested_height: dimensions ? Number(dimensions[2]) : undefined,
            font_reference_asset_id: entry.combinationFontReferenceAssetId,
          }
        }),
        // The template prompt workflow owns all creative instructions. Do not append legacy
        // workspace presets or global requirements a second time to image-generation prompts.
        preset_selection: {},
        extra_requirements: '',
        size: prepared[0]?.size || '2048x2048',
        aspect_ratio: prepared[0]?.aspectRatio || '1:1',
        quality: current.params.quality,
        output_format: current.params.output_format,
        output_compression: current.params.output_compression,
        concurrency: current.concurrency,
        admin_test_mode: false,
        workspace_batch_id: current.serverWorkspaceId,
        submission_kind: options.submissionKind || 'production',
      })
      workflowItemIdsRef.current.set(workflow.workflow_job_id, new Set(itemIds))
      if (options.validationTemplateId) validationWorkflowTemplateRef.current.set(workflow.workflow_job_id, options.validationTemplateId)
      if (
        !workflow.batch_id
        && workflow.template_prompts.length > 0
        && workflow.template_prompts.every((record) => record.prompt_status === 'effective')
      ) {
        workflow = await submitConfirmedBatchTryOnWorkflow(
          workflow.workflow_job_id,
          `direct-prompt:${randomUuid()}`,
        )
      }
      setBatch((latest) => latest?.id === current.id ? syncLegacyTemplateFields({
        ...latest,
        serverProjectId: project.id,
        serverProjectName: project.name,
        serverWorkflowId: isValidation ? latest.serverWorkflowId : workflow.workflow_job_id,
        serverBatchId: isValidation ? latest.serverBatchId : workflow.batch_id || undefined,
        serverBatchIds: appendTrackedServerBatchId(latest.serverBatchIds, workflow.batch_id || undefined),
        queuePaused: isValidation ? (workflow.batch_id ? false : latest.queuePaused) : !workflow.batch_id,
        templates: latest.templates.map((template) => ({
          ...template,
          serverAssetId: template.serverAssetId || templateAssets.get(template.id),
        })),
        garments: latest.garments.map((garment) => ({
          ...garment,
          serverAssetId: garment.serverAssetId || garmentAssets.get(garment.id),
          fontReference: garment.fontReference ? {
            ...garment.fontReference,
            serverAssetId: garment.fontReference.serverAssetId || fontReferenceAssets.get(garment.fontReference.imageId),
          } : undefined,
        })),
        fontReferenceOverrides: Object.fromEntries(Object.entries(latest.fontReferenceOverrides || {}).map(([key, reference]) => [key, {
          ...reference,
          serverAssetId: reference.serverAssetId || fontReferenceAssets.get(reference.imageId),
        }])),
        items: latest.items.map((item) => itemIds.includes(item.id) ? {
          ...item,
          serverWorkflowId: workflow.workflow_job_id,
          templateServerAssetId: item.templateServerAssetId || (item.templateId ? templateAssets.get(item.templateId) : undefined),
          garmentServerAssetId: item.garmentServerAssetId || (item.garmentId ? garmentAssets.get(item.garmentId) : undefined),
          status: 'queued',
          error: undefined,
          startedAt: undefined,
          finishedAt: undefined,
        } : item),
        updatedAt: Date.now(),
      }) : latest)
      if (!isValidation) {
        setTemplatePromptRecords(workflow.template_prompts || [])
        setPromptWorkflowStatus(workflow.status)
        setStyleAnalysisStatus(effectivePromptMode === 'direct'
          ? '已直接使用每个模板中输入的预设提示词；未调用 AI 分析。'
          : effectivePromptMode === 'ai_detailed'
            ? `正在使用 GPT-5.6 Luna 为 ${workflow.analysis_call_target} 个图片组合执行逐图精细分析。`
            : `正在为 ${workflow.analysis_call_target} 个模板执行 AI Prompt Analysis。`)
      }
      if (workflow.batch_id) {
        const submitted = await getServerBatch(workflow.batch_id)
        setBatch((latest) => latest?.id === current.id && (isValidation || latest.serverWorkflowId === workflow.workflow_job_id) ? {
          ...latest,
          serverBatchId: isValidation ? latest.serverBatchId : workflow.batch_id || undefined,
          serverBatchIds: appendTrackedServerBatchId(latest.serverBatchIds, workflow.batch_id || undefined),
          queuePaused: false,
          items: applySubmittedBatchTryOnJobs(
            latest.items,
            submitted.jobs.map((job) => job.client_item_id).filter((id): id is string => Boolean(id)),
            submitted.jobs,
          ),
          updatedAt: Date.now(),
        } : latest)
        showToast(isValidation
          ? `样图任务已提交；当前共有 ${submitted.total_jobs} 张进入生成队列。`
          : `已创建 ${submitted.total_jobs} 个图片任务，未调用提示词分析模型。`, 'success')
        void pollServerBatch(workflow.batch_id)
      }
      else if (!isValidation) void pollBatchTryOnWorkflow(workflow.workflow_job_id)
    } catch (error) {
      const message = friendlyError(error)
      if (!isValidation) setStyleAnalysisStatus(null)
      setBatch((latest) => latest ? {
        ...latest,
        queuePaused: isValidation ? latest.queuePaused : true,
        items: latest.items.map((item) => itemIds.includes(item.id)
          ? { ...item, status: 'error', error: message, finishedAt: Date.now() }
          : item),
        updatedAt: Date.now(),
      } : latest)
      showToast(message, 'error')
    } finally {
      if (!isValidation) setMatrixSubmitting(false)
    }
  }

  const startItems = (itemIds: string[]) => {
    if (!batch || itemIds.length === 0) return
    updateBatch({ queuePaused: false })
    setBatch((current) => current ? {
      ...current,
      items: current.items.map((item) => itemIds.includes(item.id) && (item.status === 'error' || item.status === 'stopped')
        ? { ...item, status: 'pending', error: undefined, taskId: undefined, outputImageId: undefined, startedAt: undefined, finishedAt: undefined }
        : item),
      updatedAt: Date.now(),
    } : current)
    if (!runtimeConfig.isStandalone) {
      void startServerWorkflowItems(itemIds)
      return
    }
    void getRunner().start(itemIds).then(() => {
      setBatch((current) => current ? { ...current, queuePaused: false, updatedAt: Date.now() } : current)
    })
  }

  const startNewMatrix = async () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || startDisabledReason || matrixSubmitting) return
    const productionCurrent = runtimeConfig.isStandalone ? current : {
      ...current,
      templates: current.templates.map((template) => ({
        ...template,
        selected: Boolean(template.selected && template.validationStatus === 'approved'),
      })),
    }
    const matrix = buildUnsubmittedBatchTryOnMatrix(productionCurrent, current.items)
    if (!matrix.length) return
    if (matrix.length > MAX_BATCH_TRY_ON_MATRIX_ITEMS) {
      showToast(`单个批次最多生成 ${MAX_BATCH_TRY_ON_MATRIX_ITEMS} 张图片`, 'error')
      return
    }
    const previousBatchStillRunning = !runtimeConfig.isStandalone && isRunning
    if (!runtimeConfig.isStandalone) {
      stopBatchTryOnWorkflowPolling()
      setTemplatePromptRecords([])
      setPromptWorkflowStatus(null)
    }
    setBatch({
      ...current,
      serverWorkflowId: undefined,
      serverBatchId: undefined,
      items: appendBatchTryOnSubmissionItems(current.items, matrix),
      queuePaused: false,
      updatedAt: Date.now(),
    })
    if (runtimeConfig.isStandalone) startItems(matrix.map((item) => item.id))
    else {
      const directIds = matrix.filter((item) => productionCurrent.templates.find((template) => template.id === item.templateId)?.promptStrategy !== 'luna_per_image').map((item) => item.id)
      const detailedIds = matrix.filter((item) => productionCurrent.templates.find((template) => template.id === item.templateId)?.promptStrategy === 'luna_per_image').map((item) => item.id)
      if (directIds.length) await startServerWorkflowItems(directIds, { promptMode: 'direct', submissionKind: 'production' })
      if (detailedIds.length) await startServerWorkflowItems(detailedIds, { promptMode: 'ai_detailed', submissionKind: 'production' })
    }
    if (previousBatchStillRunning) {
      showToast('已开始提交新的独立批次；上一批仍在后台运行，可在任务中心继续查看。', 'success')
    }
  }

  const generateValidationSample = async (templateId: string) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || validationSubmittingTemplateIds.has(templateId)) return
    const template = current.templates.find((item) => item.id === templateId && item.selected)
    const sample = current.garments.find((item) => item.id === current.sampleGarmentId)
      || current.garments.find((item) => item.selected)
    if (!template || !sample) {
      showToast('请先选择模板和样图商品。', 'error')
      return
    }
    if (template.validationStatus === 'generating') return
    setValidationSubmittingTemplateIds((ids) => new Set(ids).add(templateId))
    const itemId = `validation:${template.id}:${randomUuid()}`
    const validationItem: BatchTryOnItem = {
      id: itemId, batchId: current.id, templateId: template.id, templateImageId: template.imageId,
      templateServerAssetId: template.serverAssetId, templateName: template.displayName,
      templateOrder: current.templates.filter((item) => item.selected).findIndex((item) => item.id === template.id) + 1,
      templateCount: 1, garmentId: sample.id, garmentImageId: sample.garmentImageId,
      garmentServerAssetId: sample.serverAssetId, garmentFileName: sample.garmentFileName,
      presetSelection: {}, presetSummary: '', index: 0, status: 'pending', createdAt: Date.now(),
    }
    setBatch((latest) => latest?.id === current.id ? {
      ...latest,
      sampleGarmentId: sample.id,
      items: [...latest.items, validationItem],
      templates: latest.templates.map((item) => item.id === templateId ? {
        ...item, validationStatus: 'generating', validatedPrompt: undefined,
        validatedPromptVersion: undefined, validatedSampleOutputId: undefined, validatedAt: undefined,
      } : item),
      updatedAt: Date.now(),
    } : latest)
    const mode: BatchTryOnPromptMode = template.promptStrategy === 'luna_per_image'
      ? 'ai_detailed'
      : template.promptStrategy === 'ai_optimize' ? 'ai_analysis' : 'direct'
    try {
      await startServerWorkflowItems([itemId], {
        promptMode: mode, submissionKind: 'validation', validationTemplateId: templateId,
      })
    } finally {
      setValidationSubmittingTemplateIds((ids) => {
        const next = new Set(ids)
        next.delete(templateId)
        return next
      })
    }
  }

  const generateAllValidationSamples = async () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || generateAllValidationDisabledReason) {
      if (generateAllValidationDisabledReason) showToast(generateAllValidationDisabledReason, 'error')
      return
    }
    const templateIds = current.templates
      .filter((template) => template.selected && !['generating', 'pending_review', 'approved'].includes(template.validationStatus || 'not_generated'))
      .map((template) => template.id)
    if (!templateIds.length) return
    showToast(`正在并行提交 ${templateIds.length} 张样图。`, 'success')
    await Promise.all(templateIds.map((templateId) => generateValidationSample(templateId)))
  }

  const setTemplatePromptStrategy = (
    templateId: string, strategy: NonNullable<BatchTryOnTemplate['promptStrategy']>,
  ) => updateTemplates((templates) => templates.map((template) => template.id === templateId ? {
    ...template,
    promptStrategy: strategy,
    validationStatus: template.validationStatus === 'approved' ? 'needs_revalidation' : 'not_generated',
    validatedPrompt: undefined, validatedPromptVersion: undefined,
    validatedSampleOutputId: undefined, validatedAt: undefined,
  } : template))

  const setSampleGarment = (garmentId: string) => {
    if (batch?.sampleGarmentId === garmentId) return
    updateBatch({
      sampleGarmentId: garmentId,
      templates: (batch?.templates || []).map((template) => template.selected ? {
        ...template,
        validationStatus: template.validationStatus === 'approved' ? 'needs_revalidation' : 'not_generated',
        validatedPrompt: undefined, validatedPromptVersion: undefined,
        validatedSampleOutputId: undefined, validatedAt: undefined,
      } : template),
    })
  }

  const approveValidationSample = async (templateId: string) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return false
    const sampleItem = [...current.items].reverse().find((item) => item.id.startsWith(`validation:${templateId}:`) && item.status === 'done')
    if (!sampleItem?.outputImageId) return false
    setPromptActionBusy(true)
    try {
      let record = templatePromptRecords.find((item) => (
        item.client_item_id === sampleItem.id || item.template_id === templateId
      ))
      if (sampleItem.serverWorkflowId) {
        const workflow = await getBatchTryOnWorkflow(sampleItem.serverWorkflowId)
        record = workflow.template_prompts.find((item) => (
          item.client_item_id === sampleItem.id || item.template_id === templateId
        )) || workflow.template_prompts[0] || record
      }
      const prompt = record?.edited_final_prompt?.trim()
        || record?.generated_final_prompt?.trim()
        || record?.analysis_prompt_used?.trim()
        || templatePromptDraftsRef.current[templateId]?.analysisPrompt.trim()
        || ''
      const latest = useStore.getState().batchTryOnBatch
      if (!latest) return false
      setBatch({
        ...latest,
        templates: latest.templates.map((template) => template.id === templateId ? {
          ...template, validationStatus: 'approved', validatedPrompt: prompt,
          validatedPromptVersion: record?.prompt_version || 1,
          validatedSampleOutputId: sampleItem.outputImageId, validatedAt: Date.now(),
        } : template),
        updatedAt: Date.now(),
      })
      showToast('样图已通过，实际使用的提示词快照已锁定。', 'success')
      return true
    } catch (error) {
      showToast(`读取样图提示词快照失败，暂未通过：${friendlyError(error)}`, 'error')
      return false
    } finally {
      setPromptActionBusy(false)
    }
  }

  const rejectValidationSample = (templateId: string) => updateTemplates((templates) => templates.map((template) => (
    template.id === templateId ? { ...template, validationStatus: 'rejected' } : template
  )))

  const openValidationPromptEditor = async (templateId: string) => {
    const current = useStore.getState().batchTryOnBatch
    const template = current?.templates.find((item) => item.id === templateId)
    if (!current || !template) return
    const sample = [...current.items].reverse().find((item) => (
      item.id.startsWith(`validation:${templateId}:`) && item.status === 'done'
    ))
    const configuredPrompt = templatePromptDraftsRef.current[templateId]?.analysisPrompt.trim() || ''
    const initialPromptValues = resolveBatchTryOnValidationPromptValues(configuredPrompt)
    setValidationPromptEditor({
      templateId,
      templateName: template.displayName || template.fileName,
      outputImageId: sample?.outputImageId,
      validationStatus: template.validationStatus || 'not_generated',
      promptStrategy: template.promptStrategy || 'luna_per_image',
      analysisPrompt: initialPromptValues.analysisPrompt,
      originalAnalysisPrompt: initialPromptValues.analysisPrompt,
      sampleFinalPrompt: initialPromptValues.sampleFinalPrompt,
      sampleFinalPromptLabel: initialPromptValues.sampleFinalPromptLabel,
      loading: Boolean(sample?.serverWorkflowId),
    })
    if (!sample?.serverWorkflowId) return
    try {
      const workflow = await getBatchTryOnWorkflow(sample.serverWorkflowId)
      const record = workflow.template_prompts.find((item) => (
        item.client_item_id === sample.id || item.template_id === templateId
      )) || workflow.template_prompts[0]
      const promptValues = resolveBatchTryOnValidationPromptValues(configuredPrompt, record)
      setValidationPromptEditor((currentEditor) => currentEditor?.templateId === templateId ? {
        ...currentEditor,
        analysisPrompt: promptValues.analysisPrompt,
        originalAnalysisPrompt: promptValues.analysisPrompt,
        sampleFinalPrompt: promptValues.sampleFinalPrompt,
        sampleFinalPromptLabel: promptValues.sampleFinalPromptLabel,
        loading: false,
      } : currentEditor)
    } catch (error) {
      setValidationPromptEditor((currentEditor) => currentEditor?.templateId === templateId ? {
        ...currentEditor,
        loading: false,
      } : currentEditor)
      showToast(`读取样图提示词快照失败，已显示当前模板提示词：${friendlyError(error)}`, 'error')
    }
  }

  const submitValidationPromptAdjustment = async () => {
    if (!validationPromptEditor || validationPromptRegenerating) return
    const prompt = validationPromptEditor.analysisPrompt.trim()
    if (!prompt) {
      showToast('提示词不能为空。', 'error')
      return
    }
    setValidationPromptRegenerating(true)
    try {
      const currentStrategy = useStore.getState().batchTryOnBatch?.templates.find(
        (template) => template.id === validationPromptEditor.templateId,
      )?.promptStrategy || 'luna_per_image'
      const currentStrategyLabel = currentStrategy === 'luna_per_image'
        ? 'Luna 精细逐图'
        : currentStrategy === 'ai_optimize' ? 'AI 分析优化' : '直接使用预设'
      updateTemplatePromptConfig(validationPromptEditor.templateId, { analysisPrompt: prompt })
      updateTemplates((templates) => templates.map((template) => template.id === validationPromptEditor.templateId ? {
        ...template,
        validationStatus: 'rejected',
        validatedPrompt: undefined,
        validatedPromptVersion: undefined,
        validatedSampleOutputId: undefined,
        validatedAt: undefined,
      } : template))
      await generateValidationSample(validationPromptEditor.templateId)
      setValidationPromptEditor(null)
      showToast(`已按修改后的提示词重新提交样图，并继续使用“${currentStrategyLabel}”策略。`, 'success')
    } finally {
      setValidationPromptRegenerating(false)
    }
  }

  const analyzeCurrentTemplate = async (templateId: string) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || matrixSubmitting) return
    if (runtimeConfig.isStandalone) {
      showToast('AI 模板分析仅支持多人模式。', 'error')
      return
    }
    if (promptMode === 'direct') {
      showToast('请先选择“AI 分析优化”或“Luna 精细逐图”。', 'error')
      return
    }
    const template = current.templates.find((item) => item.id === templateId)
    if (!template) {
      showToast('当前模板不存在，请刷新页面后重试。', 'error')
      return
    }
    const promptConfig = templatePromptDrafts[templateId]
    if (!promptConfig?.analysisPrompt.trim()) {
      showToast('请先为当前模板配置 AI 分析提示词。', 'error')
      return
    }
    const matrix = buildBatchTryOnTemplateMatrix(current, templateId)
    if (!matrix.length) {
      showToast('请至少选择一件待套服装。', 'error')
      return
    }

    stopBatchTryOnWorkflowPolling()
    setTemplatePromptRecords([])
    setPromptWorkflowStatus(null)
    setStyleAnalysisStatus(`正在为“${template.displayName || template.fileName}”创建新的独立分析工作流…`)
    setBatch({
      ...current,
      serverWorkflowId: undefined,
      serverBatchId: undefined,
      items: appendBatchTryOnSubmissionItems(current.items, matrix),
      queuePaused: false,
      updatedAt: Date.now(),
    })
    showToast(`已提交“${template.displayName || template.fileName}”的独立提示词分析。`, 'success')
    await startServerWorkflowItems(matrix.map((item) => item.id))
  }

  const updateTemplatePromptConfig = (templateId: string, patch: Partial<TemplatePromptDraftConfig>) => {
    const fallback = promptPresets.find((preset) => preset.template_type === 'pure_white') || promptPresets[0]
    const base: TemplatePromptDraftConfig = templatePromptDraftsRef.current[templateId] || {
      templateType: fallback?.template_type || 'pure_white',
      presetId: fallback?.id || '',
      analysisPrompt: fallback?.analysis_prompt_template || '',
    }
    const nextDrafts = {
      ...templatePromptDraftsRef.current,
      [templateId]: { ...base, ...patch },
    }
    templatePromptDraftsRef.current = nextDrafts
    setTemplatePromptDrafts(nextDrafts)
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    const nextBatch = syncLegacyTemplateFields({
      ...current,
      templatePromptConfigs: nextDrafts,
      templates: current.templates.map((template) => template.id === templateId ? {
        ...template,
        validationStatus: ['approved', 'pending_review', 'rejected', 'needs_revalidation'].includes(template.validationStatus || '')
          ? 'needs_revalidation'
          : template.validationStatus,
        validatedPrompt: template.validationStatus === 'approved' ? undefined : template.validatedPrompt,
        validatedPromptVersion: template.validationStatus === 'approved' ? undefined : template.validatedPromptVersion,
        validatedSampleOutputId: template.validationStatus === 'approved' ? undefined : template.validatedSampleOutputId,
        validatedAt: template.validationStatus === 'approved' ? undefined : template.validatedAt,
      } : template),
      updatedAt: Date.now(),
    })
    setBatch(nextBatch)
    if (nextBatch.serverWorkspaceId) persistWorkspaceBatch(nextBatch.serverWorkspaceId, nextBatch)
  }

  const changeTemplateGarmentView = (templateId: string, garmentView: BatchTryOnTemplateGarmentView) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    const selectedTemplate = current.templates.find((template) => template.id === templateId)
    updateBatch({
      templates: current.templates.map((template) => template.id === templateId ? {
        ...template, garmentView,
        validationStatus: template.validationStatus === 'approved' ? 'needs_revalidation' : template.validationStatus,
        validatedPrompt: undefined, validatedPromptVersion: undefined,
        validatedSampleOutputId: undefined, validatedAt: undefined,
      } : template),
    })
    if (current.serverProjectId && selectedTemplate?.serverAssetId) {
      const projectId = current.serverProjectId
      const templateAssetId = selectedTemplate.serverAssetId
      projectDraftSaveRef.current = projectDraftSaveRef.current
        .catch(() => undefined)
        .then(async () => {
          const project = await getProject(projectId)
          const draft = project.latest_version.draft_json
          await saveProjectVersion(projectId, {
            ...draft,
            template_garment_views: {
              ...readTemplateGarmentViews(draft),
              [templateAssetId]: garmentView,
            },
          }, project.latest_version.version_number, '保存模板服装参考视图')
        })
      void projectDraftSaveRef.current.catch((error) => {
        showToast(`服装参考视图保存失败：${friendlyError(error)}`, 'error')
      })
    }
    if (templatePromptRecords.length > 0) {
      stopBatchTryOnWorkflowPolling()
      setTemplatePromptRecords([])
      setPromptWorkflowStatus(null)
      setStyleAnalysisStatus('图B服装参考已切换，原分析结果已失效，请重新分析当前模板。')
    }
  }

  const confirmTemplatePrompt = async (record: BatchTryOnTemplatePrompt, finalPrompt: string) => {
    if (!batch?.serverWorkflowId) return
    setPromptActionBusy(true)
    try {
      const saved = await confirmBatchTryOnTemplatePrompt(batch.serverWorkflowId, record.id, finalPrompt)
      setTemplatePromptRecords((current) => current.map((item) => item.id === saved.id ? saved : item))
      showToast('最终换衣提示词已确认并生效。', 'success')
    } catch (error) {
      showToast(friendlyError(error), 'error')
    } finally {
      setPromptActionBusy(false)
    }
  }

  const reanalyzeTemplatePrompt = async (record: BatchTryOnTemplatePrompt, analysisPrompt: string) => {
    if (!batch?.serverWorkflowId) return
    setPromptActionBusy(true)
    try {
      const updated = await reanalyzeBatchTryOnTemplatePrompt(
        batch.serverWorkflowId, record.id, analysisPrompt,
      )
      setTemplatePromptRecords((current) => current.map((item) => item.id === updated.id ? updated : item))
      setPromptWorkflowStatus('analyzing_prompts')
      setStyleAnalysisStatus('正在重新分析该模板的最终换衣提示词…')
      void pollBatchTryOnWorkflow(batch.serverWorkflowId)
    } catch (error) {
      showToast(friendlyError(error), 'error')
    } finally {
      setPromptActionBusy(false)
    }
  }

  const submitConfirmedWorkflow = async () => {
    if (!batch?.serverWorkflowId) return
    setPromptActionBusy(true)
    try {
      const workflow = await submitConfirmedBatchTryOnWorkflow(
        batch.serverWorkflowId, `prompt-confirm:${randomUuid()}`,
      )
      setPromptWorkflowStatus(workflow.status)
      setTemplatePromptRecords(workflow.template_prompts || [])
      if (!workflow.batch_id) throw new Error('图片批次创建失败：服务端未返回 batch_id。')
      const submitted = await getServerBatch(workflow.batch_id)
      setBatch((current) => current?.serverWorkflowId === workflow.workflow_job_id ? {
        ...current,
        serverBatchId: workflow.batch_id || undefined,
        serverBatchIds: appendTrackedServerBatchId(current.serverBatchIds, workflow.batch_id || undefined),
        queuePaused: false,
        items: applySubmittedBatchTryOnJobs(
          current.items,
          submitted.jobs.map((job) => job.client_item_id).filter((id): id is string => Boolean(id)),
          submitted.jobs,
        ),
        updatedAt: Date.now(),
      } : current)
      setStyleAnalysisStatus('最终提示词已确认，图片任务已进入队列。')
      showToast(`已创建 ${submitted.total_jobs} 个图片任务。`, 'success')
      void pollServerBatch(workflow.batch_id)
    } catch (error) {
      showToast(friendlyError(error), 'error')
    } finally {
      setPromptActionBusy(false)
    }
  }

  useEffect(() => {
    const workflowId = batch?.serverWorkflowId
    if (!workflowId || !validationWorkflowTemplateRef.current.has(workflowId)) return
    if (!templatePromptRecords.length || validationWorkflowSubmittingRef.current.has(workflowId)) return
    const ready = templatePromptRecords.every((record) => ['ready', 'effective'].includes(record.prompt_status))
    if (!ready) return
    validationWorkflowSubmittingRef.current.add(workflowId)
    void (async () => {
      try {
        for (const record of templatePromptRecords) {
          if (record.prompt_status !== 'ready') continue
          await confirmBatchTryOnTemplatePrompt(
            workflowId, record.id, record.edited_final_prompt || record.generated_final_prompt,
          )
        }
        const workflow = await submitConfirmedBatchTryOnWorkflow(workflowId, `validation-confirm:${randomUuid()}`)
        if (!workflow.batch_id) throw new Error('验证样图批次创建失败。')
        const submitted = await getServerBatch(workflow.batch_id)
        setBatch((current) => current?.serverWorkflowId === workflowId ? {
          ...current,
          serverBatchId: workflow.batch_id || undefined,
          serverBatchIds: appendTrackedServerBatchId(current.serverBatchIds, workflow.batch_id || undefined),
          queuePaused: false,
          items: applySubmittedBatchTryOnJobs(
            current.items,
            submitted.jobs.map((job) => job.client_item_id).filter((id): id is string => Boolean(id)),
            submitted.jobs,
          ),
          updatedAt: Date.now(),
        } : current)
        void pollServerBatch(workflow.batch_id)
      } catch (error) {
        validationWorkflowSubmittingRef.current.delete(workflowId)
        const templateId = validationWorkflowTemplateRef.current.get(workflowId)
        if (templateId) rejectValidationSample(templateId)
        showToast(friendlyError(error), 'error')
      }
    })()
  }, [batch?.serverWorkflowId, templatePromptRecords, pollServerBatch, setBatch, showToast])

  useEffect(() => {
    if (!batch) return
    const updates = new Map<string, BatchTryOnTemplate['validationStatus']>()
    for (const template of batch.templates) {
      if (template.validationStatus !== 'generating') continue
      const sample = [...batch.items].reverse().find((item) => item.id.startsWith(`validation:${template.id}:`))
      if (sample?.status === 'done' && sample.outputImageId) updates.set(template.id, 'pending_review')
      else if (sample?.status === 'error' || sample?.status === 'stopped') updates.set(template.id, 'rejected')
    }
    if (!updates.size) return
    setBatch((current) => current ? {
      ...current,
      templates: current.templates.map((template) => updates.has(template.id) ? {
        ...template, validationStatus: updates.get(template.id),
      } : template),
      updatedAt: Date.now(),
    } : current)
  }, [batch, setBatch])

  const saveAnalysisPromptAsPreset = async (templateId: string) => {
    const config = templatePromptDrafts[templateId]
    if (!config?.analysisPrompt.trim()) return
    const label = window.prompt('个人预设名称', '批量套图自定义预设')?.trim()
    if (!label) return
    setPromptActionBusy(true)
    try {
      const preset = await createBatchTryOnPromptPreset({
        template_type: config.templateType, label, analysis_prompt_template: config.analysisPrompt,
      })
      setPromptPresets((current) => [...current, preset])
      updateTemplatePromptConfig(templateId, { presetId: preset.id })
      showToast('已另存为个人提示词预设。', 'success')
    } catch (error) {
      showToast(friendlyError(error), 'error')
    } finally {
      setPromptActionBusy(false)
    }
  }

  const pauseQueue = () => {
    if (!runtimeConfig.isStandalone && batch?.serverBatchId) {
      void pauseServerBatch(batch.serverBatchId).then(() => {
        stopServerPolling()
        setBatch((current) => current ? { ...current, queuePaused: true, items: current.items.map((item) => item.status === 'running' ? { ...item, status: 'stopped' } : item), updatedAt: Date.now() } : current)
        showToast('服务端批次已暂停；已进入上游请求的任务可能仍会完成', 'info')
      }).catch((error) => showToast(friendlyError(error), 'error'))
      return
    }
    getRunner().pause()
    updateBatch({ queuePaused: true })
    showToast('队列已暂停，正在生成的任务会继续完成', 'info')
  }

  const resumeQueue = () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    if (!runtimeConfig.isStandalone && current.serverBatchId) {
      void resumeServerBatch(current.serverBatchId).then(() => {
        setBatch((latest) => latest ? { ...latest, queuePaused: false, items: latest.items.map((item) => item.status === 'stopped' ? { ...item, status: 'running' } : item), updatedAt: Date.now() } : latest)
        void pollServerBatch(current.serverBatchId!)
      }).catch((error) => showToast(friendlyError(error), 'error'))
      return
    }
    const pendingIds = current.items.filter((item) => item.status === 'pending' || item.status === 'stopped').map((item) => item.id)
    const runner = getRunner()
    runner.enqueue(pendingIds)
    updateBatch({ queuePaused: false })
    void runner.resume()
  }

  const uploadTemplates = async (files: File[]) => {
    if (configurationLocked || files.length === 0) return
    const current = normalizeBatchTryOnBatch(batch ?? createEmptyBatch(globalParams))
    const remaining = MAX_BATCH_TRY_ON_TEMPLATES - current.templates.length
    if (remaining <= 0) {
      showToast(`模板图最多 ${MAX_BATCH_TRY_ON_TEMPLATES} 张`, 'error')
      return
    }
    const added: BatchTryOnTemplate[] = []
    const errors: string[] = []
    let project: Project | undefined
    if (!runtimeConfig.isStandalone) {
      try {
        project = current.serverProjectId
          ? await getProject(current.serverProjectId)
          : await createProject({
              project_type: 'batch_tryon',
              name: current.serverProjectName || `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
              draft: {
                preset_selection: current.presetSelection,
                concurrency: current.concurrency,
                admin_test_mode: false,
                generation_mode: current.generationMode || 'normal_tryon',
                combination_mode: current.combinationMode || 'cartesian',
              },
            })
      } catch (error) {
        showToast(`模板项目读取失败：${friendlyError(error)}`, 'error')
        return
      }
    }
    for (const file of files.slice(0, remaining)) {
      try {
        validateImageFile(file)
        const image = await createInputImageFromFile(file)
        if (!image) throw new Error('模板图读取失败')
        const stored = await getImage(image.id)
        let template: BatchTryOnTemplate = {
          id: createId(),
          imageId: image.id,
          fileName: file.name,
          displayName: stripExtension(file.name),
          width: stored?.width,
          height: stored?.height,
          selected: true,
          isDefault: current.templates.length === 0 && added.length === 0,
          sourceType: 'upload',
          promptStrategy: 'luna_per_image',
          validationStatus: 'not_generated',
        }
        if (project) {
          template = (await persistBatchTryOnTemplates(
            project,
            [template],
            current.templates.length + added.length,
          ))[0]
        }
        added.push(template)
      } catch (error) {
        errors.push(`${file.name}：${friendlyError(error)}`)
      }
    }
    if (added.length) {
      setBatch(syncLegacyTemplateFields({
        ...current,
        serverProjectId: project?.id || current.serverProjectId,
        serverProjectName: project?.name || current.serverProjectName,
        templates: [...current.templates, ...added],
        queuePaused: true,
        updatedAt: Date.now(),
      }))
      if (project && searchParams.get('project_id') !== project.id) {
        const nextSearchParams = new URLSearchParams(searchParams)
        nextSearchParams.set('project_id', project.id)
        setSearchParams(nextSearchParams, { replace: true })
      }
      showToast(`已添加 ${added.length} 张模板图`, 'success')
    }
    if (files.length > remaining) errors.push(`超过上限的 ${files.length - remaining} 张模板未添加`)
    if (errors.length) showToast(errors[0], 'error')
  }

  const removeTemplate = (template: BatchTryOnTemplate) => {
    if (configurationLocked) return
    if (batch?.serverProjectId && template.projectAssetLinkId) {
      void unlinkProjectAsset(batch.serverProjectId, template.projectAssetLinkId)
        .catch((error) => showToast(`模板项目关联删除失败：${friendlyError(error)}`, 'error'))
    }
    setBatch((current) => {
      if (!current) return current
      const templates = current.templates.filter((candidate) => candidate.id !== template.id)
      const fontReferenceOverrides = Object.fromEntries(Object.entries(current.fontReferenceOverrides || {}).filter(
        ([key]) => !key.startsWith(`${template.id}:`),
      ))
      if (templates.length && !templates.some((candidate) => candidate.isDefault)) templates[0] = { ...templates[0], isDefault: true }
      return syncLegacyTemplateFields({
        ...current,
        templates,
        fontReferenceOverrides,
        items: current.items.filter((item) => item.templateId !== template.id),
        queuePaused: true,
        updatedAt: Date.now(),
      })
    })
    window.setTimeout(() => void deleteImageIfUnreferenced(template.imageId), 0)
  }

  const updateTemplates = (updater: (templates: BatchTryOnTemplate[]) => BatchTryOnTemplate[]) => {
    setBatch((current) => current ? syncLegacyTemplateFields({
      ...current,
      templates: updater(current.templates),
      updatedAt: Date.now(),
    }) : current)
  }

  const setDefaultTemplate = (templateId: string) => {
    const template = batch?.templates.find((item) => item.id === templateId)
    updateTemplates((templates) => templates.map((item) => ({ ...item, isDefault: item.id === templateId })))
    if (batch?.serverProjectId && template?.projectAssetLinkId) {
      void updateProjectAsset(batch.serverProjectId, template.projectAssetLinkId, { is_default: true })
        .catch((error) => showToast(`默认模板保存失败：${friendlyError(error)}`, 'error'))
    }
  }

  const uploadGarments = async (files: File[]) => {
    if (configurationLocked || files.length === 0) return
    const current = normalizeBatchTryOnBatch(batch ?? createEmptyBatch(globalParams))
    const remaining = MAX_BATCH_TRY_ON_ITEMS - current.garments.length
    if (remaining <= 0) {
      showToast(`待套服装最多 ${MAX_BATCH_TRY_ON_ITEMS} 张`, 'error')
      return
    }

    const added: BatchTryOnGarment[] = []
    const errors: string[] = []
    for (const file of files.slice(0, remaining)) {
      try {
        validateImageFile(file)
        const image = await createInputImageFromFile(file)
        if (!image) throw new Error('图片读取失败')
        added.push({
          id: createId(),
          batchId: current.id,
          garmentImageId: image.id,
          garmentFileName: file.name,
          index: current.garments.length + added.length,
          selected: true,
          createdAt: Date.now(),
        })
      } catch (error) {
        errors.push(`${file.name}：${friendlyError(error)}`)
      }
    }
    if (added.length > 0) {
      setBatch({
        ...current,
        garments: [...current.garments, ...added],
        sampleGarmentId: current.sampleGarmentId || added[0].id,
        queuePaused: true,
        updatedAt: Date.now(),
      })
      showToast(`已添加 ${added.length} 张待套服装`, 'success')
    }
    if (files.length > remaining) errors.push(`超过上限的 ${files.length - remaining} 张图片未添加`)
    if (errors.length > 0) showToast(errors[0], 'error')
  }

  const openGarmentPreprocess = (garmentId?: string) => {
    if (!batch?.garments.length) {
      showToast('请先上传服装原图。', 'error')
      return
    }
    if (!garmentId && !batch.garments.some((garment) => garment.selected)) {
      showToast('请先勾选需要批量处理的服装。', 'error')
      return
    }
    setPreprocessGarmentId(garmentId)
    setPreprocessOpen(true)
  }

  const saveGarmentReferences = async (previews: GarmentReferencePreview[]) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || !previews.length) return
    setPreprocessSaving(true)
    try {
      let project = current.serverProjectId
        ? await getProject(current.serverProjectId)
        : await createProject({
            project_type: 'batch_tryon',
            name: current.serverProjectName || `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
            draft: {
              concurrency: current.concurrency,
              generation_mode: current.generationMode || 'normal_tryon',
              combination_mode: current.combinationMode || 'cartesian',
            },
          })
      const persistedTemplates = current.templates.length
        ? await persistBatchTryOnTemplates(project, current.templates)
        : []
      const uploadedOriginals = new Map<string, { assetId: string; linkId?: string }>()
      const saved = new Map<string, BatchTryOnGarmentReference>()
      const saveErrors: string[] = []
      for (const preview of previews) {
        const garment = current.garments.find((item) => item.id === preview.garmentId)
        if (!garment) continue
        try {
          let original = uploadedOriginals.get(garment.id)
          if (!original) {
            let assetId = garment.serverAssetId
            if (!assetId) {
              const dataUrl = await ensureImageCached(garment.garmentImageId)
              if (!dataUrl) throw new Error(`${garment.garmentFileName}原图读取失败。`)
              assetId = (await uploadDataUrlAsset(dataUrl, 'garment', garment.garmentFileName)).id
            }
            if (!project.assets.some((link) => link.role === 'garment' && link.asset.id === assetId)) {
              const link = await linkProjectAssetCompact(project.id, assetId, 'garment', garment.index, garment.garmentFileName)
              project = {
                ...project,
                assets: [...project.assets, {
                  id: link.id, role: link.role, sort_order: link.sort_order,
                  display_name: link.display_name, is_default: link.is_default,
                  asset: { id: assetId } as typeof project.assets[number]['asset'],
                  created_at: link.created_at,
                }],
              }
            }
            original = {
              assetId,
              linkId: project.assets.find((link) => link.role === 'garment' && link.asset.id === assetId)?.id,
            }
            uploadedOriginals.set(garment.id, original)
          }
          const compactTransform = compactGarmentTransform(preview.transform)
          const asset = await uploadGarmentReferenceDataUrl(preview.dataUrl, garment.garmentFileName, {
            sourceAssetId: original.assetId,
            garmentView: preview.garmentView,
            transformType: compactTransform.eraseStrokes.length
              ? (compactTransform.mode === 'crop' ? 'crop_mask' : 'mask')
              : compactTransform.mode,
            transformMetadata: garmentTransformMetadata(compactTransform),
          })
          const newLink = await linkProjectAssetCompact(
            project.id, asset.id, `garment_reference.${preview.garmentView}`,
            garment.index, `${garment.garmentFileName} · ${preview.garmentView}`,
          )
          const newLinkId = newLink.id
          cacheImageDataUrl(asset.id, preview.dataUrl)
          const imageId = asset.id
          const previous = garment.references?.[preview.garmentView]
          if (previous?.projectAssetLinkId && previous.projectAssetLinkId !== newLinkId) {
            try {
              await unlinkProjectAsset(project.id, previous.projectAssetLinkId)
              project = {
                ...project,
                assets: project.assets.filter((link) => link.id !== previous.projectAssetLinkId),
              }
            } catch {
              // The newly linked reference is already safe; a stale old link can be cleaned up later.
            }
          }
          saved.set(`${garment.id}:${preview.garmentView}`, {
            imageId,
            serverAssetId: asset.id,
            projectAssetLinkId: newLinkId,
            sourceAssetId: original.assetId,
            fileName: asset.filename,
            garmentView: preview.garmentView,
            transform: compactTransform,
          })
        } catch (error) {
          saveErrors.push(`${garment.garmentFileName} · ${preview.garmentView}: ${friendlyError(error)}`)
        }
      }
      setBatch((latest) => latest?.id === current.id ? {
        ...latest,
        serverProjectId: project.id,
        serverProjectName: project.name,
        templates: persistedTemplates,
        garments: latest.garments.map((garment) => {
          const original = uploadedOriginals.get(garment.id)
          const references = { ...garment.references }
          for (const view of ['front', 'back', 'detail'] as const) {
            const reference = saved.get(`${garment.id}:${view}`)
            if (reference) references[view] = reference
          }
          return {
            ...garment,
            serverAssetId: garment.serverAssetId || original?.assetId,
            projectAssetLinkId: garment.projectAssetLinkId || original?.linkId,
            references,
          }
        }),
        updatedAt: Date.now(),
      } : latest)
      if (saveErrors.length) {
        showToast(`已保存 ${saved.size} 张；${saveErrors.length} 张失败：${saveErrors[0]}`, 'error')
      } else {
        setPreprocessOpen(false)
        showToast(`已保存 ${saved.size} 张干净服装参考图；原图保持不变。`, 'success')
      }
    } catch (error) {
      showToast(`服装参考图保存失败：${friendlyError(error)}`, 'error')
    } finally {
      setPreprocessSaving(false)
    }
  }

  const removeGarment = (item: BatchTryOnGarment) => {
    if (configurationLocked) return
    if (batch?.serverProjectId && item.projectAssetLinkId) {
      void unlinkProjectAsset(batch.serverProjectId, item.projectAssetLinkId)
        .catch((error) => showToast(`服装项目关联删除失败：${friendlyError(error)}`, 'error'))
    }
    if (batch?.serverProjectId) for (const reference of Object.values(item.references || {})) {
      if (reference?.projectAssetLinkId) void unlinkProjectAsset(batch.serverProjectId, reference.projectAssetLinkId).catch(() => undefined)
    }
    setBatch((current) => current ? {
      ...current,
      garments: current.garments.filter((candidate) => candidate.id !== item.id).map((candidate, index) => ({ ...candidate, index })),
      sampleGarmentId: current.sampleGarmentId === item.id
        ? current.garments.find((candidate) => candidate.id !== item.id)?.id
        : current.sampleGarmentId,
      templates: current.sampleGarmentId === item.id ? current.templates.map((template) => ({
        ...template,
        validationStatus: template.validationStatus === 'approved' ? 'needs_revalidation' : 'not_generated',
        validatedPrompt: undefined, validatedPromptVersion: undefined,
        validatedSampleOutputId: undefined, validatedAt: undefined,
      })) : current.templates,
      fontReferenceOverrides: Object.fromEntries(Object.entries(current.fontReferenceOverrides || {}).filter(
        ([key]) => !key.endsWith(`:${item.id}`),
      )),
      items: current.items.filter((candidate) => candidate.garmentId !== item.id),
      updatedAt: Date.now(),
    } : current)
    window.setTimeout(() => {
      void deleteImageIfUnreferenced(item.garmentImageId)
      for (const reference of Object.values(item.references || {})) {
        if (reference?.imageId) void deleteImageIfUnreferenced(reference.imageId)
      }
    }, 0)
  }

  const clearGarments = () => {
    if (!batch || configurationLocked) return
    const ids = [
      ...batch.garments.flatMap((item) => [
        item.garmentImageId, item.fontReference?.imageId,
        ...Object.values(item.references || {}).map((reference) => reference?.imageId),
      ].filter((id): id is string => Boolean(id))),
      ...Object.values(batch.fontReferenceOverrides || {}).map((item) => item.imageId),
    ]
    if (batch.serverProjectId) {
      for (const garment of batch.garments) {
        if (garment.projectAssetLinkId) {
          void unlinkProjectAsset(batch.serverProjectId, garment.projectAssetLinkId)
            .catch((error) => showToast(`服装项目关联删除失败：${friendlyError(error)}`, 'error'))
        }
        for (const reference of Object.values(garment.references || {})) if (reference?.projectAssetLinkId) {
          void unlinkProjectAsset(batch.serverProjectId, reference.projectAssetLinkId).catch(() => undefined)
        }
      }
    }
    updateBatch({ garments: [], sampleGarmentId: undefined, fontReferenceOverrides: {}, items: [], queuePaused: true })
    window.setTimeout(() => ids.forEach((id) => void deleteImageIfUnreferenced(id)), 0)
  }

  const clearBatch = () => {
    if (!batch) return
    const cleared = clearBatchTryOnQueueState(batch)
    runnerRef.current?.stopPending()
    runnerRef.current = null
    stopServerPolling()
    stopBatchTryOnWorkflowPolling()
    stopValidationWorkflowPolling()
    setSelectedReviewItems(new Map())
    setBatchDiagnostics(null)
    setTemplatePromptRecords([])
    setPromptWorkflowStatus(null)
    setStyleAnalysisStatus(null)
    setBatch(cleared)
    if (cleared.serverWorkspaceId) persistWorkspaceBatch(cleared.serverWorkspaceId, cleared)
    showToast('当前页面队列已清空，模板、服装和历史批次均已保留', 'success')
  }

  const requestClearBatch = () => {
    if (progress.running === 0) {
      clearBatch()
      return
    }
    setConfirmDialog({
      title: '清空当前页面队列？',
      message: '页面中的任务和结果会被清空；已经发送的请求不会被强制终止，完成后仍可在批次历史中查看。模板、服装和生成设置都会保留。',
      confirmText: '清空页面队列',
      cancelText: '取消',
      tone: 'warning',
      action: clearBatch,
    })
  }

  const downloadOne = async (item: BatchTryOnItem) => {
    if (!runtimeConfig.isStandalone && item.serverOutputDownloadUrl) {
      try {
        await downloadAuthenticatedFile(
          item.serverOutputDownloadUrl,
          item.serverOutputDownloadFilename || item.serverOutputFilename || 'batch-tryon.png',
        )
        showToast('结果图已下载', 'success')
      } catch (error) {
        showToast(`结果图下载失败：${friendlyError(error)}`, 'error')
      }
      return
    }
    if (!batch || !item.outputImageId) return
    const [fileName] = createBatchTryOnFileNames([withTemplateFilenameInfo(batch, item)])
    const base = fileName.replace(/\.[^.]+$/, '')
    const result = await downloadImageIds([item.outputImageId], base)
    showToast(result.successCount ? '结果图已下载' : '结果图下载失败', result.successCount ? 'success' : 'error')
  }

  const downloadAll = async () => {
    if (!batch) return
    if (!runtimeConfig.isStandalone && batch.serverBatchId) {
      try {
        await downloadBatchTryOnResultsZip(batch.serverBatchId)
        showToast('批量套图结果已开始下载', 'success')
      } catch (error) {
        showToast(`批量下载失败：${friendlyError(error)}`, 'error')
      }
      return
    }
    const items = batch.items.flatMap((item) => {
      if (!item.outputImageId) return []
      const filenameInfo = withTemplateFilenameInfo(batch, item)
      return [{
        imageId: item.outputImageId,
        garmentFileName: item.garmentFileName,
        templateName: item.templateName,
        templateIndex: filenameInfo.templateIndex,
        templateCount: filenameInfo.templateCount,
        index: item.index,
      }]
    })
    try {
      const result = await downloadBatchTryOnZip(items, batch.id)
      showToast(`已打包 ${result.successCount} 张结果${result.failCount ? `，${result.failCount} 张失败` : ''}`, result.successCount ? 'success' : 'error')
    } catch (error) {
      showToast(`批量下载失败：${friendlyError(error)}`, 'error')
    }
  }

  const applyReviewChange = (detail: BatchTryOnReviewDetail, taskId?: string) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    const localItem = current.items.find((item) => (
      item.id === detail.client_item_id || item.serverReviewItemId === detail.item_id
    ))
    if (!localItem) {
      showToast('审核结果已保存，但当前页面任务状态同步失败，请刷新页面后查看。', 'error')
      return
    }
    const version = detail.current_version
    updateItem(current.id, localItem.id, {
      taskId: taskId ?? version?.task_id ?? undefined,
      status: detail.review_status === 'regenerating' ? 'running' : detail.review_status === 'generation_failed' ? 'error' : version?.generation_status === 'succeeded' ? 'done' : 'running',
      serverReviewItemId: detail.item_id,
      serverReviewStatus: detail.review_status,
      serverCurrentVersionId: detail.current_version_id ?? undefined,
      serverApprovedVersionId: detail.approved_version_id ?? undefined,
      regenerationCount: detail.regeneration_count,
      serverVersionNumber: version?.version_number,
      serverOutputAssetId: version?.generated_asset?.id,
      serverOutputFilename: version?.generated_asset?.display_filename,
      serverOutputDownloadFilename: version?.generated_asset?.download_filename,
      serverOutputDownloadUrl: version?.generated_asset?.download_url,
      error: detail.review_status === 'generation_failed' ? '重新生成失败，请查看详情。' : undefined,
      startedAt: detail.review_status === 'regenerating' ? Date.now() : undefined,
      finishedAt: version?.completed_at ? new Date(version.completed_at).getTime() : undefined,
    })
    if (taskId) void pollRegeneratedJobs([taskId])
  }

  const readFontReference = async (file: File) => {
    validateImageFile(file)
    const image = await createInputImageFromFile(file)
    if (!image) throw new Error('字体参考图读取失败')
    return { imageId: image.id, fileName: file.name }
  }

  const setGarmentFontReference = async (garmentId: string, file: File) => {
    try {
      const reference = await readFontReference(file)
      const previous = useStore.getState().batchTryOnBatch?.garments.find((item) => item.id === garmentId)?.fontReference
      setBatch((current) => current ? {
        ...current,
        garments: current.garments.map((item) => item.id === garmentId ? { ...item, fontReference: reference } : item),
        updatedAt: Date.now(),
      } : current)
      if (previous?.imageId && previous.imageId !== reference.imageId) window.setTimeout(() => void deleteImageIfUnreferenced(previous.imageId), 0)
      showToast('已设为当前服装的默认字体参考图。', 'success')
    } catch (error) {
      showToast(friendlyError(error), 'error')
    }
  }

  const bulkMatchGarmentFontReferences = async (files: File[]) => {
    if (!batch || files.length === 0) return

    const validFiles: File[] = []
    const invalidFiles: string[] = []
    for (const file of files) {
      try {
        validateImageFile(file)
        validFiles.push(file)
      } catch {
        invalidFiles.push(file.name)
      }
    }

    const matchResult = matchFontReferencesByIdentifier(
      batch.garments.map((garment) => ({
        id: garment.id,
        garmentFileName: garment.garmentFileName,
      })),
      validFiles.map((file) => ({ value: file, name: file.name })),
    )

    const references = new Map<string, { imageId: string; fileName: string }>()
    const failedReads: string[] = []
    for (const assignment of matchResult.assignments) {
      try {
        references.set(assignment.garmentId, await readFontReference(assignment.reference.value))
      } catch {
        failedReads.push(assignment.reference.name)
      }
    }

    if (references.size > 0) {
      const previousReferences = batch.garments
        .filter((garment) => references.has(garment.id) && garment.fontReference?.imageId)
        .map((garment) => garment.fontReference!.imageId)
      setBatch((current) => current ? {
        ...current,
        garments: current.garments.map((garment) => {
          const reference = references.get(garment.id)
          return reference ? { ...garment, fontReference: reference } : garment
        }),
        updatedAt: Date.now(),
      } : current)
      for (const imageId of previousReferences) {
        if (!Array.from(references.values()).some((reference) => reference.imageId === imageId)) {
          window.setTimeout(() => void deleteImageIfUnreferenced(imageId), 0)
        }
      }
    }

    const conflictCount = matchResult.ambiguous.length + matchResult.duplicateGarmentMatches.length
    const skippedCount = matchResult.unmatched.length + invalidFiles.length + failedReads.length
    const summary = [
      `已按数字编号匹配 ${references.size} 张字体参考图`,
      skippedCount ? `未匹配或不可用 ${skippedCount} 张` : '',
      conflictCount ? `编号冲突 ${conflictCount} 组` : '',
    ].filter(Boolean).join('；')
    showToast(summary, references.size > 0 ? (conflictCount || skippedCount ? 'info' : 'success') : 'error')
  }

  const setCombinationFontReference = async (templateId: string, garmentId: string, file: File) => {
    try {
      const reference = await readFontReference(file)
      const key = batchTryOnFontReferenceKey(templateId, garmentId)
      const previous = useStore.getState().batchTryOnBatch?.fontReferenceOverrides?.[key]
      setBatch((current) => current ? {
        ...current,
        fontReferenceOverrides: { ...(current.fontReferenceOverrides || {}), [key]: reference },
        updatedAt: Date.now(),
      } : current)
      if (previous?.imageId && previous.imageId !== reference.imageId) window.setTimeout(() => void deleteImageIfUnreferenced(previous.imageId), 0)
      showToast('已为当前模板与服装组合设置字体参考覆盖。', 'success')
    } catch (error) {
      showToast(friendlyError(error), 'error')
    }
  }

  const clearGarmentFontReference = (garmentId: string) => {
    const previous = batch?.garments.find((item) => item.id === garmentId)?.fontReference
    setBatch((current) => current ? {
      ...current,
      garments: current.garments.map((item) => item.id === garmentId ? { ...item, fontReference: undefined } : item),
      updatedAt: Date.now(),
    } : current)
    if (previous?.imageId) window.setTimeout(() => void deleteImageIfUnreferenced(previous.imageId), 0)
  }

  const clearCombinationFontReference = (templateId: string, garmentId: string) => {
    const key = batchTryOnFontReferenceKey(templateId, garmentId)
    const previous = batch?.fontReferenceOverrides?.[key]
    setBatch((current) => {
      if (!current) return current
      const overrides = { ...(current.fontReferenceOverrides || {}) }
      delete overrides[key]
      return { ...current, fontReferenceOverrides: overrides, updatedAt: Date.now() }
    })
    if (previous?.imageId) window.setTimeout(() => void deleteImageIfUnreferenced(previous.imageId), 0)
  }

  const validBulkSelections = () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return []
    const selectedIds = new Set(selectedReviewItems.keys())
    return current.items.flatMap((item) => {
      if (!item.serverReviewItemId || !selectedIds.has(item.serverReviewItemId)) return []
      const selected = toSelectedBatchTryOnReviewItem(item)
      return selected ? [selected] : []
    })
  }

  const toggleBulkSelection = (item: BatchTryOnItem, selected: boolean) => {
    const selection = toSelectedBatchTryOnReviewItem(item)
    if (!selection) {
      showToast('只有生成成功且输入素材完整的当前版本可以批量重新生成。', 'error')
      return
    }
    setSelectedReviewItems((current) => {
      const next = new Map(current)
      if (selected) next.set(selection.itemId, selection)
      else next.delete(selection.itemId)
      return next
    })
  }

  const selectBulkItems = (items: BatchTryOnItem[]) => {
    setSelectedReviewItems((current) => {
      const next = new Map(current)
      for (const item of items) {
        const selection = toSelectedBatchTryOnReviewItem(item)
        if (selection) next.set(selection.itemId, selection)
      }
      return next
    })
  }

  const invertBulkItems = (items: BatchTryOnItem[]) => {
    setSelectedReviewItems((current) => {
      const next = new Map(current)
      for (const item of items) {
        const selection = toSelectedBatchTryOnReviewItem(item)
        if (!selection) continue
        if (next.has(selection.itemId)) next.delete(selection.itemId)
        else next.set(selection.itemId, selection)
      }
      return next
    })
  }

  const openBulkRegenerate = () => {
    if (!selectedReviewItems.size) {
      showToast('请先选择需要重新生成的图片', 'error')
      return
    }
    const valid = validBulkSelections()
    if (!valid.length) {
      showToast('当前选择中没有可重新生成的图片，请刷新任务状态后重试。', 'error')
      return
    }
    setShowBulkRegenerate(true)
  }

  const openBulkLuna = () => {
    if (!selectedReviewItems.size) {
      showToast('请先选择需要 Luna 精细分析的图片', 'error')
      return
    }
    if (!validBulkSelections().length) {
      showToast('当前选择中没有可分析的成功结果，请刷新任务状态后重试。', 'error')
      return
    }
    setShowBulkLuna(true)
  }

  const submitBulkLuna = async ({ autoRegenerate }: { autoRegenerate: boolean }) => {
    const selected = validBulkSelections()
    showToast(autoRegenerate ? '正在创建 Luna 分析与自动重生成任务…' : '正在创建 Luna 批量分析任务…', 'success')
    const result = await batchAnalyzeAndRegenerateBatchTryOnVersions({
      items: selected.map((item) => ({ item_id: item.itemId, version_id: item.versionId })),
      focus_notes: null,
      template_type: null,
      prompt_preset_id: null,
      template_prompt_override: null,
      auto_regenerate: autoRegenerate,
      idempotency_key: `batch-luna:${randomUuid()}`,
    })
    const accepted = new Set(result.analysis_tasks.map((task) => task.item_id))
    setBatch((current) => current ? {
      ...current,
      items: current.items.map((item) => item.serverReviewItemId && accepted.has(item.serverReviewItemId)
        ? { ...item, serverReviewStatus: autoRegenerate ? 'regenerating' : item.serverReviewStatus }
        : item),
      updatedAt: Date.now(),
    } : current)
    setSelectedReviewItems((current) => {
      const next = new Map(current)
      accepted.forEach((id) => next.delete(id))
      return next
    })
    showToast(`已提交 ${result.analysis_tasks.length} 张 Luna 分析${autoRegenerate ? '；完成后自动进入生图队列' : ''}${result.failed_count ? `，失败 ${result.failed_count} 张` : ''}`, result.failed_count ? 'error' : 'success')
    return result
  }

  const openTemplateBulkRegenerate = (items: BatchTryOnItem[]) => {
    const selections = items.flatMap((item) => {
      const selection = toSelectedBatchTryOnReviewItem(item)
      return selection ? [selection] : []
    })
    if (!selections.length) {
      showToast('当前模板没有可重新生成的成功结果。', 'error')
      return
    }
    setSelectedReviewItems(new Map(selections.map((item) => [item.itemId, item])))
    setShowBulkRegenerate(true)
  }

  const submitBulkRegenerate = async (
    selected: SelectedBatchTryOnReviewItem[],
    reviewNotes: string,
  ): Promise<BatchTryOnBatchRegenerateResponse> => {
    showToast('正在创建批量重新生成任务...', 'success')
    const result = await batchRegenerateBatchTryOnVersions({
      items: selected.map((item) => ({
        item_id: item.itemId,
        version_id: item.versionId,
      })),
      review_notes: reviewNotes,
      idempotency_key: `batch-review:${randomUuid()}`,
    })
    const createdByItem = new Map(result.created_tasks.map((task) => [task.client_item_id, task]))
    const succeededIds = new Set(result.created_tasks.map((task) => task.item_id))
    setBatch((current) => {
      if (!current) return current
      return {
        ...current,
        items: current.items.map((item) => {
          const task = createdByItem.get(item.id)
          if (!task) return item
          return {
            ...item,
            taskId: task.task_id,
            status: 'queued',
            error: undefined,
            serverReviewStatus: 'regenerating',
            serverCurrentVersionId: task.version_id,
            serverVersionNumber: (item.serverVersionNumber ?? 1) + (task.created ? 1 : 0),
            regenerationCount: (item.regenerationCount ?? 0) + (task.created ? 1 : 0),
            startedAt: undefined,
            finishedAt: undefined,
          }
        }),
        queuePaused: false,
        updatedAt: Date.now(),
      }
    })
    setSelectedReviewItems((current) => {
      const next = new Map(current)
      for (const itemId of succeededIds) next.delete(itemId)
      return next
    })
    if (batch?.serverBatchId) void pollServerBatch(batch.serverBatchId)
    const regeneratedTaskIds = result.created_tasks.map((task) => task.task_id)
    if (regeneratedTaskIds.length) void pollRegeneratedJobs(regeneratedTaskIds)
    if (result.failed_count) {
      showToast(`成功创建 ${result.created_count} 个，失败 ${result.failed_count} 个`, 'error')
    } else {
      showToast(`已为 ${result.created_count + result.replayed_count} 张图片创建重新生成任务`, 'success')
    }
    return result
  }

  const bulkApprove = async () => {
    if (!selectedReviewItems.size) {
      showToast('请先选择需要审核通过的图片', 'error')
      return
    }
    const current = useStore.getState().batchTryOnBatch
    const targets = current?.items.flatMap((item) => (
      item.serverReviewItemId
      && item.serverCurrentVersionId
      && item.serverReviewStatus === 'pending'
      && item.status === 'done'
      && selectedReviewItems.has(item.serverReviewItemId)
        ? [{ itemId: item.serverReviewItemId, versionId: item.serverCurrentVersionId }]
        : []
    )) ?? []
    if (!targets.length) {
      showToast('当前选择中没有可审核通过的待审核结果。', 'error')
      return
    }
    if (!window.confirm(`将审核通过 ${targets.length} 张图片，是否继续？`)) return
    const settled = await Promise.allSettled(
      targets.map((target) => approveBatchTryOnVersion(target.itemId, target.versionId)),
    )
    const succeeded = new Set<string>()
    settled.forEach((result, index) => {
      if (result.status === 'fulfilled') {
        succeeded.add(targets[index].itemId)
        applyReviewChange(result.value)
      }
    })
    setSelectedReviewItems((selected) => {
      const next = new Map(selected)
      for (const itemId of succeeded) next.delete(itemId)
      return next
    })
    const failed = settled.length - succeeded.size
    showToast(
      failed ? `审核通过 ${succeeded.size} 张，失败 ${failed} 张` : `已审核通过 ${succeeded.size} 张`,
      failed ? 'error' : 'success',
    )
  }

  const downloadTemplateResults = async (
    templateId: string,
    scope: 'approved' | 'all_succeeded',
    templateName: string,
    reviewItemIds: string[],
  ) => {
    if (!reviewItemIds.length) {
      showToast('当前模板没有已同步到服务端的结果，不能打包。', 'error')
      return
    }
    try {
      showToast(`正在打包“${templateName}”结果...`, 'success')
      await downloadSelectedBatchTryOnTemplateZip(templateId, reviewItemIds, scope)
      showToast(`“${templateName}”结果已开始下载`, 'success')
    } catch (error) {
      showToast(`模板打包失败：${friendlyError(error)}`, 'error')
    }
  }

  const advanceReview = (currentReviewItemId: string) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return false
    const next = findNextPendingReviewItem(current.items, currentReviewItemId)
    if (!next?.serverReviewItemId) return false
    setReviewItemId(next.serverReviewItemId)
    return true
  }

  if (!batch) return <div className="p-6 text-sm text-gray-400">正在恢复批量套图批次...</div>

  return (
    <div className="bg-gray-50/70 p-4 dark:bg-gray-950/50 sm:p-5">
      {!runtimeConfig.isStandalone && batch.serverProjectId && <BatchTryOnWorkspaceTabs
        tabs={workspaceTabs}
        activeId={batch.serverWorkspaceId}
        busy={workspaceTabsBusy}
        canHardDelete={auth.hasPermission('assets.delete') && auth.hasPermission('jobs.cancel')}
        onSelect={switchWorkspaceTab}
        onCreate={() => void createWorkspaceTab()}
        onRename={renameWorkspaceTab}
        onDeleteDraft={(tab) => void removeWorkspaceDraft(tab)}
        onHardDelete={(tab) => void hardDeleteWorkspaceTab(tab)}
      />}
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <BatchTryOnTemplateManager
          templates={batch.templates}
          maxItems={MAX_BATCH_TRY_ON_TEMPLATES}
          disabled={configurationLocked}
          promptPresets={promptPresets}
          promptPresetIds={Object.fromEntries(Object.entries(templatePromptDrafts).map(([templateId, config]) => [templateId, config.presetId]))}
          generateAllCount={validationGenerationTargets.length}
          generateAllDisabledReason={generateAllValidationDisabledReason}
          combinationMode={batch.combinationMode || 'cartesian'}
          onUpload={(files) => void uploadTemplates(files)}
          onRemove={removeTemplate}
          onPromptPresetChange={(templateId, presetId) => {
            const preset = promptPresets.find((item) => item.id === presetId)
            if (!preset) return
            updateTemplatePromptConfig(templateId, {
              templateType: preset.template_type,
              presetId: preset.id,
              analysisPrompt: preset.analysis_prompt_template,
            })
          }}
          onGenerateAllValidations={() => void generateAllValidationSamples()}
          onSetDefault={setDefaultTemplate}
          onToggle={(templateId) => updateTemplates((templates) => templates.map((item) => item.id === templateId ? { ...item, selected: !item.selected } : item))}
          onToggleAll={(selected) => updateTemplates((templates) => templates.map((item) => ({ ...item, selected })))}
          onView={(imageId) => setLightboxImageId(imageId)}
          detailMode={(batch.generationMode || 'normal_tryon') === 'detail_tryon'}
          onDetailChange={(templateId, patch) => updateBatch({
            templates: batch.templates.map((template) => template.id === templateId ? { ...template, ...patch } : template),
          })}
          onGarmentViewChange={changeTemplateGarmentView}
          onPromptStrategyChange={setTemplatePromptStrategy}
          onGenerateValidation={(templateId) => void generateValidationSample(templateId)}
          onReviewValidation={(templateId) => document.getElementById(`validation-${templateId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
        />
        <div id="batch-tryon-garments"><BatchTryOnGarmentList
          items={batch.garments}
          maxItems={MAX_BATCH_TRY_ON_ITEMS}
          disabled={configurationLocked}
          combinationMode={batch.combinationMode || 'cartesian'}
          onUpload={(files) => void uploadGarments(files)}
          onRemove={removeGarment}
          onClear={clearGarments}
          onToggle={(garmentId) => updateBatch({ garments: batch.garments.map((item) => item.id === garmentId ? { ...item, selected: !item.selected } : item) })}
          onToggleAll={(selected) => updateBatch({ garments: batch.garments.map((item) => ({ ...item, selected })) })}
          onView={(imageId) => setLightboxImageId(imageId)}
          onFontReferenceUpload={(garmentId, file) => void setGarmentFontReference(garmentId, file)}
          onFontReferenceRemove={clearGarmentFontReference}
          onBulkFontReferenceUpload={(files) => void bulkMatchGarmentFontReferences(files)}
          onPreprocess={openGarmentPreprocess}
          sampleGarmentId={batch.sampleGarmentId}
          onSetSampleGarment={setSampleGarment}
        /></div>
      </div>

      <BatchTryOnGarmentPreprocessDialog
        open={preprocessOpen}
        garments={batch.garments.filter((garment) => garment.selected || garment.id === preprocessGarmentId)}
        initialGarmentId={preprocessGarmentId}
        saving={preprocessSaving}
        onClose={() => setPreprocessOpen(false)}
        onSave={saveGarmentReferences}
      />

      {!runtimeConfig.isStandalone && selectedTemplates.some((template) => template.validationStatus !== 'not_generated') && <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="flex items-center justify-between gap-3"><div><h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">样图验证</h3><p className="mt-1 text-xs text-gray-500">已通过的模板可以直接参与正式批量；其他模板可继续单独调整和验证。</p></div><span className="text-xs font-semibold text-gray-500">已通过 {generationTemplates.length}/{selectedTemplates.length}</span></div>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {selectedTemplates.map((template) => {
            const sample = [...batch.items].reverse().find((item) => item.id.startsWith(`validation:${template.id}:`))
            return <article id={`validation-${template.id}`} key={template.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
              <div className="flex items-center justify-between gap-2"><div className="truncate text-xs font-semibold">{template.displayName}</div><span className="text-[11px] text-gray-500">{template.promptStrategy === 'ai_optimize' ? 'AI分析优化' : template.promptStrategy === 'luna_per_image' ? 'Luna逐图' : '直接预设'}</span></div>
              {sample?.outputImageId ? <button type="button" onClick={() => void openValidationPromptEditor(template.id)} className="mt-2 block aspect-square w-full overflow-hidden rounded-lg bg-gray-100" title="打开样图审核与提示词调整"><BatchTryOnImage imageId={sample.outputImageId} alt={`${template.displayName} 验证样图`} className="h-full w-full object-cover" /></button> : <div className="mt-2 flex aspect-square items-center justify-center rounded-lg bg-gray-50 text-xs text-gray-400 dark:bg-white/[0.03]">{template.validationStatus === 'generating' ? '样图生成中…' : sample?.error || '尚无样图'}</div>}
              <div className="mt-2 flex gap-2">
                {template.validationStatus === 'pending_review' && <><button type="button" disabled={promptActionBusy} onClick={() => void approveValidationSample(template.id)} className="h-8 flex-1 rounded-lg bg-emerald-600 text-xs font-semibold text-white disabled:opacity-40">效果通过</button><button type="button" disabled={promptActionBusy} onClick={() => void openValidationPromptEditor(template.id)} className="h-8 flex-1 rounded-lg border border-gray-200 text-xs font-semibold disabled:opacity-40">效果调整</button></>}
                {template.validationStatus === 'approved' && <><span className="flex h-8 flex-1 items-center justify-center rounded-lg bg-emerald-50 text-xs font-semibold text-emerald-700">✓ Prompt V{template.validatedPromptVersion || 1} 已锁定</span><button type="button" onClick={() => void generateValidationSample(template.id)} className="h-8 rounded-lg border border-gray-200 px-3 text-xs font-semibold">重新验证</button></>}
                {(template.validationStatus === 'rejected' || template.validationStatus === 'needs_revalidation') && <button type="button" onClick={() => void generateValidationSample(template.id)} className="h-8 w-full rounded-lg bg-blue-600 text-xs font-semibold text-white">重新生成样图</button>}
              </div>
            </article>
          })}
        </div>
        {generationTemplates.length > 0 && <div className="mt-4 flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/20 dark:bg-emerald-500/10 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-bold text-emerald-900 dark:text-emerald-100">{estimatedGenerationCount > 0 ? '样图都调好啦，可以开始整批生成了' : '当前已通过的组合都已经提交啦'}</div>
            <div className="mt-1 text-xs text-emerald-700 dark:text-emerald-200">{estimatedGenerationCount > 0
              ? `本次只会提交 ${pendingGenerationTemplates.length} 个新通过模板尚未生成的 ${estimatedGenerationCount} 张图片；已发送组合不会重复。`
              : '如果需要重做已提交的图片，请在任务结果中使用重新生成。'}</div>
          </div>
          <button type="button" disabled={Boolean(startDisabledReason || matrixSubmitting)} title={startDisabledReason} onClick={() => setShowGenerateConfirmation(true)} className="h-10 shrink-0 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">{matrixSubmitting ? '正在提交新批次…' : '一键生成全部组合'}</button>
        </div>}
      </section>}

      {runtimeConfig.isStandalone && <BatchTryOnPresetPanel
        selection={batch.presetSelection}
        disabled={configurationLocked}
        onChange={(presetSelection) => updateBatch({ presetSelection })}
      />}

      <details open={runtimeConfig.isStandalone} className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <summary className="cursor-pointer list-none text-sm font-semibold text-gray-800 dark:text-gray-100">高级设置 <span className="ml-2 text-xs font-normal text-gray-400">输出尺寸、质量、格式、组合与并发</span></summary>
        <div className={`mt-4 ${runtimeConfig.isStandalone ? 'grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.85fr)]' : ''}`}>
          {runtimeConfig.isStandalone && <label>
            <span className="text-sm font-bold text-gray-900 dark:text-gray-100">额外要求</span>
            <textarea value={batch.extraRequirements} disabled={configurationLocked} onChange={(event) => updateBatch({ extraRequirements: event.target.value })} className="mt-2 min-h-32 w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100" placeholder="例如：衣服自然放下，不要塞进裤子；保持原图只展示到膝盖；服装使用印染效果，不要变成刺绣。" />
            <span className="mt-1.5 block text-xs text-gray-400">只影响当前批次，且不会覆盖内置的服装与模特保真规则。</span>
          </label>}
          <div>
            <div className="text-sm font-bold text-gray-900 dark:text-gray-100">输出设置</div>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              <FieldSelect
                label="生成模式"
                value={batch.generationMode || 'normal_tryon'}
                disabled={configurationLocked}
                onChange={(value) => updateBatch({ generationMode: value as NonNullable<BatchTryOnBatch['generationMode']> })}
                options={[
                  { value: 'normal_tryon', label: '普通批量换衣' },
                  { value: 'detail_tryon', label: '细节模板换衣' },
                ]}
              />
              <FieldSelect
                label="组合方式"
                value={batch.combinationMode || 'cartesian'}
                disabled={configurationLocked}
                onChange={(value) => updateBatch({ combinationMode: value as NonNullable<BatchTryOnBatch['combinationMode']> })}
                options={[
                  { value: 'cartesian', label: '笛卡尔组合' },
                  { value: 'one_to_one', label: '按顺序一一对应' },
                ]}
              />
              <label className="min-w-0"><span className="mb-1 block text-xs text-gray-500 dark:text-gray-400">比例与交付尺寸</span><button type="button" disabled={configurationLocked} onClick={() => setShowSizePicker(true)} className="h-9 w-full rounded-lg border border-gray-200 bg-gray-50 px-2 text-left text-xs font-semibold text-gray-800 outline-none transition hover:border-blue-300 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100">{batch.aspectRatio === 'template' ? '跟随模板' : batch.aspectRatio} · {outputSize}</button></label>
              <FieldSelect label="输出质量" value={batch.params.quality} disabled={configurationLocked} onChange={(value) => updateBatch({ params: { ...batch.params, quality: value as TaskParams['quality'] } })} options={['high', 'medium', 'low', 'auto'].map((value) => ({ value, label: value }))} />
              <FieldSelect label="输出格式" value={batch.params.output_format} disabled={configurationLocked} onChange={(value) => updateBatch({ params: { ...batch.params, output_format: value as TaskParams['output_format'] } })} options={[{ value: 'jpeg', label: 'JPEG' }, { value: 'png', label: 'PNG' }, { value: 'webp', label: 'WEBP' }]} />
              <FieldSelect
                label="目标并发"
                value={String(batch.concurrency)}
                disabled={configurationLocked}
                onChange={(value) => updateBatch({ concurrency: Number(value) as BatchTryOnBatch['concurrency'] })}
                options={getBatchTryOnConcurrencyOptions().map((value) => ({ value: String(value), label: `${value}` }))}
              />
            </div>
            <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-xs text-gray-600 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-300">
              <div className="font-semibold text-blue-700 dark:text-blue-300">待提交模板 {pendingGenerationTemplates.length} ｜ 服装 {selectedGarments.length} ｜ 本次 {estimatedGenerationCount} 张</div>
              {batch.combinationMode === 'one_to_one' && <>
                <div className={`mt-1 font-semibold ${combinationError ? 'text-amber-700 dark:text-amber-300' : 'text-emerald-700 dark:text-emerald-300'}`}>
                  {combinationError || `已建立 ${combinationPairs.length} 组一一对应关系，其中 ${pairedFontReferenceCount} 组已绑定字体参考图`}
                </div>
                {!combinationError && combinationPairs.length > 0 && <div className="mt-2 max-h-32 space-y-1 overflow-y-auto rounded-lg border border-gray-200 bg-white p-2 dark:border-white/[0.08] dark:bg-gray-950">
                  {combinationPairs.map(({ template, garment }, index) => {
                    const reference = batch.fontReferenceOverrides?.[batchTryOnFontReferenceKey(template.id, garment.id)] || garment.fontReference
                    return <div key={`${template.id}:${garment.id}`} className="truncate" title={`${template.displayName} → ${garment.garmentFileName} → ${reference?.fileName || '未设置字体参考'}`}>
                      {index + 1}. {template.displayName} → {garment.garmentFileName} → {reference ? `字体：${reference.fileName}` : '未设置字体参考'}
                    </div>
                  })}
                </div>}
              </>}
              {batch.aspectRatio !== 'template' && <button type="button" disabled={configurationLocked} onClick={() => updateBatch({ aspectRatio: 'template', params: { ...batch.params, size: 'auto', aspect_ratio: 'auto' } })} className="mt-1 font-semibold text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-300">恢复跟随模板图（默认 2K）</button>}
              {profileError && <button type="button" onClick={() => setShowSettings(true, 'api')} className="mt-2 text-left font-semibold text-red-600 underline decoration-red-300 underline-offset-2 dark:text-red-300">{profileError} 点击前往设置</button>}
            </div>
          </div>
        </div>
      </details>

      {!runtimeConfig.isStandalone && (
        <details className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
          <summary className="cursor-pointer list-none text-sm font-semibold text-gray-800 dark:text-gray-100">提示词与高级调整 <span className="ml-2 text-xs font-normal text-gray-400">需要修改预设或查看 AI 结果时展开</span></summary>
          <BatchTryOnPromptTemplatePanel
          templates={selectedTemplates}
          garments={selectedGarments}
          fontReferenceOverrides={batch.fontReferenceOverrides}
          presets={promptPresets}
          promptMode={promptMode}
          onPromptModeChange={setPromptMode}
          templateConfigs={templatePromptDrafts}
          records={templatePromptRecords}
          status={styleAnalysisStatus}
          busy={promptActionBusy || promptWorkflowStatus === 'analyzing_prompts'}
          workflowReady={promptWorkflowStatus === 'awaiting_prompt_confirmation'}
          canManageSystemPresets={isPlatformAdmin}
          onManageSystemPresets={() => setShowSystemPresetManager(true)}
          onTemplateConfigChange={updateTemplatePromptConfig}
          onAnalyzeCurrentTemplate={analyzeCurrentTemplate}
          onReanalyze={reanalyzeTemplatePrompt}
          onConfirm={confirmTemplatePrompt}
          onSubmit={submitConfirmedWorkflow}
          onSaveAsPersonalPreset={saveAnalysisPromptAsPreset}
          onSetGarmentFontReference={(garmentId, file) => void setGarmentFontReference(garmentId, file)}
          onSetCombinationFontReference={(templateId, garmentId, file) => void setCombinationFontReference(templateId, garmentId, file)}
          onClearGarmentFontReference={clearGarmentFontReference}
          onClearCombinationFontReference={clearCombinationFontReference}
          onGarmentViewChange={changeTemplateGarmentView}
          onViewImage={setLightboxImageId}
          />
        </details>
      )}

      {(runtimeConfig.isStandalone || Boolean(batch.styleProfiles?.length) || Object.keys(templateAnalysisProfiles).length > 0) && (
        <BatchTryOnStyleAnalysisPanel
          profiles={batch.styleProfiles ?? []}
          garments={batch.garments}
          templates={batch.templates}
          templateProfiles={templateAnalysisProfiles}
          status={styleAnalysisStatus}
        />
      )}

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">任务队列与结果</h3>
            <div className="mt-1 text-sm text-gray-600 dark:text-gray-300">已完成 {progress.done} / {batch.items.length}，失败 {progress.error}，生成中 {progress.running}，等待队列 {progress.queued + progress.retry_waiting}，未提交 {progress.pending}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {runtimeConfig.isStandalone && !isRunning && <button type="button" disabled={Boolean(startDisabledReason || matrixSubmitting || promptSubmissionLocked)} title={startDisabledReason || (promptSubmissionLocked ? '请先完成当前提示词分析确认' : '')} onClick={() => setShowGenerateConfirmation(true)} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">{matrixSubmitting ? '正在提交新批次…' : '一键生成全部组合'}</button>}
            {isRunning && !batch.queuePaused && <button type="button" onClick={pauseQueue} className="h-10 rounded-xl border border-amber-200 bg-amber-50 px-3 text-sm font-semibold text-amber-700 transition hover:bg-amber-100 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">暂停队列</button>}
            {batch.queuePaused && (progress.stopped > 0 || (progress.pending > 0 && batch.items.some((item) => item.startedAt))) && <button type="button" disabled={Boolean(profileError || !batch.templates.length)} onClick={resumeQueue} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">继续生成</button>}
            {progress.error > 0 && <button type="button" onClick={() => startItems(getFailedBatchTryOnItemIds(batch.items))} className="h-10 rounded-xl border border-gray-200 px-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.06]">重试失败任务</button>}
            {progress.done > 0 && <button type="button" onClick={() => void downloadAll()} className="h-10 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200">下载成功结果</button>}
            <button type="button" onClick={requestClearBatch} className="h-10 rounded-xl px-3 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-400/10">清空当前队列</button>
          </div>
        </div>
        {startDisabledReason && (!runtimeConfig.isStandalone || !isRunning) && <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">暂时无法开始：{startDisabledReason}</div>}
        {!runtimeConfig.isStandalone && isRunning && <div className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">当前批次在后台运行中；你可以继续调整素材和设置并提交新的独立批次，旧批次可在任务中心查看。</div>}
        {batchDiagnostics && auth.hasPermission('audit.read') && (
          <div className="mt-3 grid gap-2 rounded-xl border border-blue-100 bg-blue-50/60 p-3 text-xs text-blue-900 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-100 sm:grid-cols-2 lg:grid-cols-4">
            <span>目标并发 {batchDiagnostics.configured_concurrency} · 有效上限 {batchDiagnostics.effective_concurrency}</span>
            <span>当前运行 {batchDiagnostics.active_jobs} · 实际峰值 {batchDiagnostics.actual_max_concurrency}</span>
            <span>排队 {batchDiagnostics.status_counts.queued || 0} · 等待通道 {batchDiagnostics.status_counts.waiting_for_resource || 0} · 技术重试 {batchDiagnostics.status_counts.retry_waiting || 0}</span>
            <span>成功 {batchDiagnostics.status_counts.succeeded || 0} · 失败 {batchDiagnostics.status_counts.failed || 0}</span>
            <span>平均耗时 {formatDiagnosticDuration(batchDiagnostics.average_generation_ms)}</span>
            <span>429 {batchDiagnostics.http_status_counts['429'] || 0} · 5xx {count5xx(batchDiagnostics.http_status_counts)} · timeout {countTimeouts(batchDiagnostics.error_code_counts)}</span>
            <span>Worker {batchDiagnostics.online_workers.length} 个 · 配置并发 {batchDiagnostics.worker_concurrency}</span>
            <span className={batchDiagnostics.stale_jobs ? 'font-semibold text-red-600 dark:text-red-300' : ''}>Broker {batchDiagnostics.broker_queue_length} · 失联 {batchDiagnostics.stale_jobs}</span>
            <span>资源池配置 {batchDiagnostics.resource_key_capacity} · 当前可用 {batchDiagnostics.resource_available_capacity}</span>
            {batchDiagnostics.limitation_reasons.length > 0 && <span className="sm:col-span-2 lg:col-span-4 rounded-lg bg-amber-50 px-2 py-1.5 font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">并发受限：{batchDiagnostics.limitation_reasons.join('；')}</span>}
            {batchDiagnostics.availability_reasons.length > 0 && <span className="sm:col-span-2 lg:col-span-4 rounded-lg bg-amber-50 px-2 py-1.5 font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">临时等待：{batchDiagnostics.availability_reasons.join('；')}</span>}
            {batchDiagnostics.resource_channels.length > 0 && (
              <div className="sm:col-span-2 lg:col-span-4 grid gap-2 sm:grid-cols-2">
                {batchDiagnostics.resource_channels.map((channel) => (
                  <div key={channel.key_id} className={`rounded-lg px-3 py-2 ${channel.recovery_state === 'healthy' ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-100' : channel.recovery_state === 'probing' ? 'bg-violet-50 text-violet-800 dark:bg-violet-500/10 dark:text-violet-100' : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-100'}`}>
                    <div className="flex items-center justify-between gap-2 font-bold">
                      <span>{channel.provider_name}</span>
                      <span>{batchChannelStateLabel(channel.recovery_state)}</span>
                    </div>
                    <div className="mt-1">
                      有效并发 {channel.effective_capacity}/{channel.configured_capacity}
                      {' · '}当前请求 {channel.active}
                      {' · '}连续失败 {channel.consecutive_failures}
                    </div>
                    {channel.recovery_state === 'cooling' && <div className="mt-1 font-bold">下次探测倒计时 {formatCooldownSeconds(channel.cooldown_remaining_seconds)}</div>}
                    {channel.recovery_state === 'waiting_probe' && <div className="mt-1 font-bold">冷却结束，等待调度探测任务</div>}
                    {channel.recovery_state === 'probing' && <div className="mt-1 font-bold">单探针运行中，成功后自动恢复完整并发</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${batch.items.length ? ((progress.done + progress.error) / batch.items.length) * 100 : 0}%` }} /></div>
        <div className="mt-4">
          <BatchTryOnQueue
            items={batch.items}
            selectedItemIds={new Set(selectedReviewItems.keys())}
            canBulkApprove={!runtimeConfig.isStandalone && auth.hasPermission('batch_tryon.review')}
            canBulkRegenerate={!runtimeConfig.isStandalone && auth.hasPermission('batch_tryon.review') && auth.hasPermission('jobs.submit')}
            onView={(imageId) => setLightboxImageId(imageId, batch.items.flatMap((item) => item.outputImageId ? [item.outputImageId] : []))}
            onDownload={(item) => void downloadOne(item)}
            onRetry={(item) => startItems([item.id])}
            onReview={(item) => item.serverReviewItemId && setReviewItemId(item.serverReviewItemId)}
            onToggleSelection={toggleBulkSelection}
            onSelectItems={selectBulkItems}
            onInvertSelection={invertBulkItems}
            onClearSelection={() => setSelectedReviewItems(new Map())}
            onBulkRegenerate={openBulkRegenerate}
            onBulkLunaAnalyze={openBulkLuna}
            onBulkRegenerateItems={openTemplateBulkRegenerate}
            onBulkApprove={() => void bulkApprove()}
            onDownloadTemplate={(templateId, scope, templateName, reviewItemIds) => void downloadTemplateResults(templateId, scope, templateName, reviewItemIds)}
          />
        </div>
      </section>
      {!runtimeConfig.isStandalone && batch.serverProjectId && (
        <BatchTryOnBatchHistory projectId={batch.serverProjectId} />
      )}
      {showSizePicker && <SizePickerModal currentSize={outputSize} currentAspectRatio={resolveOutputAspectRatio(batch)} allowAuto={false} onSelect={(size, aspectRatio) => { updateBatch({ aspectRatio: aspectRatio as BatchTryOnAspectRatio, params: { ...batch.params, size, aspect_ratio: aspectRatio } }); setShowSizePicker(false) }} onClose={() => setShowSizePicker(false)} />}
      {reviewItemId && !runtimeConfig.isStandalone && <BatchTryOnReviewDialog
        itemId={reviewItemId}
        items={batch.items}
        canApprove={auth.hasPermission('batch_tryon.review')}
        canRegenerate={auth.hasPermission('batch_tryon.review') && auth.hasPermission('jobs.submit')}
        selectedItemIds={new Set(selectedReviewItems.keys())}
        onClose={() => setReviewItemId(null)}
        onSelectItem={setReviewItemId}
        onChanged={applyReviewChange}
        onAdvance={advanceReview}
      />}
      {showBulkRegenerate && !runtimeConfig.isStandalone && <BatchTryOnBulkRegenerateDialog
        selected={validBulkSelections()}
        invalidCount={selectedReviewItems.size - validBulkSelections().length}
        onClose={() => setShowBulkRegenerate(false)}
        onSubmit={submitBulkRegenerate}
      />}
      {showBulkLuna && !runtimeConfig.isStandalone && <BatchTryOnBulkLunaDialog
        selected={validBulkSelections()}
        invalidCount={selectedReviewItems.size - validBulkSelections().length}
        onClose={() => setShowBulkLuna(false)}
        onSubmit={submitBulkLuna}
      />}
      {showSystemPresetManager && isPlatformAdmin && <BatchTryOnSystemPresetManager
        presets={promptPresets}
        onClose={() => setShowSystemPresetManager(false)}
        onUpdated={(updated) => {
          setPromptPresets((current) => current.map((preset) => preset.id === updated.id ? updated : preset))
          showToast('系统提示词预设已更新；需要时点击“重新加载预设”应用到当前模板。', 'success')
        }}
        onError={(message) => showToast(message, 'error')}
      />}
      {showGenerateConfirmation && <div className="fixed inset-0 z-[120] flex items-center justify-center bg-gray-950/60 p-4" role="dialog" aria-modal="true" aria-label="确认生成全部组合" onMouseDown={(event) => {
        if (event.target === event.currentTarget && !matrixSubmitting) setShowGenerateConfirmation(false)
      }}>
        <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-950">
          <div className="px-6 pb-2 pt-6 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-2xl dark:bg-blue-500/10">✨</div>
            <h2 className="mt-4 text-lg font-bold text-gray-950 dark:text-white">准备好生成整批啦</h2>
            <p className="mt-2 text-sm leading-6 text-gray-500">样图已经确认完成，我们会按当前配置创建一个新的独立批次。</p>
          </div>
          <div className="grid grid-cols-3 gap-3 px-6 py-5">
            <div className="rounded-xl bg-gray-50 px-3 py-4 text-center dark:bg-white/[0.05]"><div className="text-2xl font-bold text-gray-950 dark:text-white">{pendingGenerationTemplates.length}</div><div className="mt-1 text-xs text-gray-500">个待提交模板</div></div>
            <div className="rounded-xl bg-gray-50 px-3 py-4 text-center dark:bg-white/[0.05]"><div className="text-2xl font-bold text-gray-950 dark:text-white">{selectedGarments.length}</div><div className="mt-1 text-xs text-gray-500">件服装</div></div>
            <div className="rounded-xl bg-blue-50 px-3 py-4 text-center dark:bg-blue-500/10"><div className="text-2xl font-bold text-blue-700 dark:text-blue-200">{estimatedGenerationCount}</div><div className="mt-1 text-xs text-blue-600 dark:text-blue-300">图片张数</div></div>
          </div>
          <div className="mx-6 rounded-xl border border-amber-100 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-800 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-200">
            这里只统计尚未提交的新组合，已经发送过的模板和服装组合不会再生成一次。
          </div>
          <div className="mt-5 flex gap-3 border-t border-gray-100 px-6 py-4 dark:border-white/[0.08]">
            <button type="button" disabled={matrixSubmitting} onClick={() => setShowGenerateConfirmation(false)} className="h-10 flex-1 rounded-xl border border-gray-200 text-sm font-semibold text-gray-600 transition hover:bg-gray-50 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-300 dark:hover:bg-white/[0.05]">我再检查一下</button>
            <button type="button" disabled={Boolean(startDisabledReason || matrixSubmitting)} onClick={() => {
              setShowGenerateConfirmation(false)
              void startNewMatrix()
            }} className="h-10 flex-1 rounded-xl bg-blue-600 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:opacity-40">{matrixSubmitting ? '正在提交…' : '确认，开始全部生成'}</button>
          </div>
        </div>
      </div>}
      {validationPromptEditor && <div className="fixed inset-0 z-[120] flex items-center justify-center bg-gray-950/60 p-4" role="dialog" aria-modal="true" aria-label="样图验证与提示词调整" onMouseDown={(event) => {
        if (event.target === event.currentTarget && !validationPromptRegenerating) setValidationPromptEditor(null)
      }}>
        <div className="flex max-h-[94vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-950">
          <header className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4 dark:border-white/[0.08]">
            <div>
              <h2 className="text-base font-bold text-gray-950 dark:text-white">样图验证</h2>
              <p className="mt-1 text-xs text-gray-500">{validationPromptEditor.templateName} · 系统分析预设与样图结果分开管理</p>
            </div>
            <button type="button" disabled={validationPromptRegenerating} onClick={() => setValidationPromptEditor(null)} className="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 disabled:opacity-40 dark:hover:bg-white/[0.06]">关闭</button>
          </header>
          <div className="grid min-h-0 flex-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(380px,0.9fr)] lg:overflow-hidden">
            <section className="flex min-h-0 flex-col border-b border-gray-100 bg-gray-50 p-5 dark:border-white/[0.08] dark:bg-gray-900 lg:border-b-0 lg:border-r">
              <div className="flex min-h-[320px] flex-1 items-center justify-center overflow-hidden rounded-2xl border border-gray-200 bg-white p-3 dark:border-white/[0.08] dark:bg-gray-950">
                {validationPromptEditor.outputImageId
                  ? <BatchTryOnImage imageId={validationPromptEditor.outputImageId} alt={`${validationPromptEditor.templateName} 验证样图`} className="max-h-[62vh] max-w-full object-contain" />
                  : <div className="text-sm text-gray-400">样图暂时无法显示</div>}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <button type="button" disabled={promptActionBusy || validationPromptRegenerating || validationPromptEditor.validationStatus !== 'pending_review'} onClick={() => void (async () => {
                  if (await approveValidationSample(validationPromptEditor.templateId)) setValidationPromptEditor(null)
                })()} className="h-11 rounded-xl bg-emerald-600 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-45">
                  {validationPromptEditor.validationStatus === 'approved' ? '✓ 已通过' : promptActionBusy ? '正在确认…' : '效果通过'}
                </button>
                <button type="button" disabled={validationPromptRegenerating || !validationPromptEditor.analysisPrompt.trim()} onClick={() => void submitValidationPromptAdjustment()} className="h-11 rounded-xl bg-blue-600 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-45">
                  {validationPromptRegenerating ? '正在提交…' : '效果调整'}
                </button>
              </div>
              <p className="mt-2 text-center text-xs text-gray-500">修改右侧模板预设后，点击“效果调整”会重新执行当前样图的 AI 分析与生图，当前样图不会被覆盖。</p>
            </section>
            <section className="flex min-h-0 flex-col overflow-y-auto p-5">
              <div>
                <h3 className="text-sm font-bold text-gray-950 dark:text-white">模板分析预设</h3>
                <p className="mt-1 text-xs leading-5 text-gray-500">这里编辑的是当前模板交给 Luna / AI 的系统预设，不是第一件服装分析后的单图提示词。</p>
              </div>
              <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-200">
                {validationPromptEditor.promptStrategy === 'luna_per_image'
                  ? '正式批量时，每个“模板 × 服装”组合都会使用这份预设独立执行 Luna 分析；当前样图的单图输出不会复用到其他服装。'
                  : validationPromptEditor.promptStrategy === 'ai_optimize'
                    ? '修改后会重新执行当前模板的 AI 分析。下方单图输出仅用于核对，不会反向覆盖系统预设。'
                    : '当前模板选择了“直接使用预设”，修改后的文本将直接用于重新生成样图。'}
              </div>
              <label className="mt-4 flex min-h-0 flex-1 flex-col">
                <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">系统预设提示词</span>
                <textarea
                  value={validationPromptEditor.analysisPrompt}
                  maxLength={MAX_VALIDATION_PROMPT_LENGTH}
                  disabled={validationPromptRegenerating}
                  onChange={(event) => setValidationPromptEditor((current) => current ? { ...current, analysisPrompt: event.target.value } : current)}
                  className="mt-2 min-h-[260px] flex-1 resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-3 text-sm leading-6 text-gray-900 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100"
                  placeholder="请输入用于分析当前模板与每件服装的通用系统预设"
                />
                <span className="mt-1.5 flex items-center justify-between text-xs text-gray-400">
                  <span>模板级配置 · 不应写死第一件服装的颜色、文字、号码或 Logo</span>
                  <span>{validationPromptEditor.analysisPrompt.length}/{MAX_VALIDATION_PROMPT_LENGTH}</span>
                </span>
              </label>
              <div className="mt-4 flex justify-end">
                <button type="button" disabled={validationPromptRegenerating || validationPromptEditor.analysisPrompt === validationPromptEditor.originalAnalysisPrompt} onClick={() => setValidationPromptEditor((current) => current ? { ...current, analysisPrompt: current.originalAnalysisPrompt } : current)} className="h-9 rounded-lg border border-gray-200 px-3 text-xs font-semibold text-gray-600 disabled:opacity-40 dark:border-white/[0.1] dark:text-gray-300">恢复本次原预设</button>
              </div>
              <div className="mt-5 border-t border-gray-100 pt-4 dark:border-white/[0.08]">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">当前样图最终提示词</h4>
                    <p className="mt-1 text-xs leading-5 text-gray-500">这是 Luna / AI 针对当前样图服装生成的只读结果，仅供核对，不会写回系统预设，也不会复用到其他服装。</p>
                  </div>
                  <span className="shrink-0 text-[11px] text-gray-400">{validationPromptEditor.sampleFinalPromptLabel}</span>
                </div>
                {validationPromptEditor.loading
                  ? <div className="mt-3 rounded-xl bg-gray-50 px-3 py-4 text-xs text-gray-500 dark:bg-gray-900">正在读取服务端样图提示词快照…</div>
                  : validationPromptEditor.sampleFinalPrompt
                    ? <div className="mt-3 max-h-52 overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 px-3 py-3 text-xs leading-6 text-gray-700 dark:bg-gray-900 dark:text-gray-200">{validationPromptEditor.sampleFinalPrompt}</div>
                    : <div className="mt-3 rounded-xl border border-dashed border-gray-200 px-3 py-4 text-center text-xs text-gray-500 dark:border-white/[0.1]">当前样图没有可用的最终提示词快照。</div>}
              </div>
            </section>
          </div>
        </div>
      </div>}
    </div>
  )
}

function FieldSelect({ label, value, options, disabled, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; disabled?: boolean; onChange: (value: string) => void }) {
  return <label className="min-w-0"><span className="mb-1 block text-xs text-gray-500 dark:text-gray-400">{label}</span><select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-gray-200 bg-gray-50 px-2 text-xs font-semibold text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100">{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
}

function createId() {
  return randomUuid()
}

function validateImageFile(file: File) {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type.toLowerCase())) throw new Error('图片格式不支持，请使用 PNG、JPG、JPEG 或 WEBP。')
  const maxBytes = runtimeConfig.isStandalone ? MAX_BATCH_TRY_ON_FILE_BYTES : MAX_MULTIUSER_FILE_BYTES
  if (file.size > maxBytes) throw new Error(`单张图片不能超过 ${maxBytes / 1024 / 1024} MB。`)
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').trim() || '未命名模板'
}

function formatDiagnosticDuration(value: number | null) {
  if (value == null) return '—'
  return value < 1_000 ? `${value}ms` : `${Math.round(value / 100) / 10}s`
}

function formatCooldownSeconds(seconds: number) {
  const safe = Math.max(0, Math.ceil(seconds))
  const minutes = Math.floor(safe / 60)
  const remainder = safe % 60
  return minutes > 0 ? `${minutes}分${String(remainder).padStart(2, '0')}秒` : `${remainder}秒`
}

function batchChannelStateLabel(state: ServerJobBatchDiagnostics['resource_channels'][number]['recovery_state']) {
  return {
    healthy: '健康',
    cooling: '冷却中',
    waiting_probe: '等待探测',
    probing: '探测中',
    disabled: '已停用',
  }[state]
}

function count5xx(statusCounts: Record<string, number>) {
  return Object.entries(statusCounts).reduce((sum, [status, count]) => /^5\d\d$/.test(status) ? sum + count : sum, 0)
}

function countTimeouts(errorCounts: Record<string, number>) {
  return Object.entries(errorCounts).reduce((sum, [code, count]) => /timeout/i.test(code) ? sum + count : sum, 0)
}

function friendlyError(error: unknown) {
  if (error instanceof DOMException && error.name === 'AbortError') return '请求超时或已中断，请重试。'
  const message = error instanceof Error ? error.message : String(error)
  if (/timeout|timed out|超时/i.test(message)) return `请求超时：${message}`
  if (/empty|没有返回|no image/i.test(message)) return `API 返回空图片：${message}`
  return message || '操作失败，请重试。'
}
