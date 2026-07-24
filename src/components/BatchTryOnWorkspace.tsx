import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type {
  BatchTryOnAspectRatio, BatchTryOnBatch, BatchTryOnGarment, BatchTryOnItem,
  BatchTryOnTemplate, TaskParams,
} from '../types'
import { getImage } from '../lib/db'
import { calculateDeliverySize, resolveImageSize } from '../lib/imageSizeResolver'
import { buildBatchTryOnPrompt } from '../lib/batchTryOnPrompt'
import { BatchTryOnQueueController, getFailedBatchTryOnItemIds } from '../lib/batchTryOnQueue'
import { createBatchTryOnFileNames, downloadBatchTryOnZip } from '../lib/batchTryOnFiles'
import { downloadImageIds } from '../lib/downloadImages'
import { downloadAuthenticatedFile, downloadBatchTryOnResultsZip } from '../lib/serverDownloads'
import { getActiveApiProfile } from '../lib/apiProfiles'
import { runtimeConfig } from '../app/runtimeConfig'
import { uploadDataUrlAsset, importServerAsset, importServerOutput } from '../lib/serverImageAssets'
import {
  getServerBatch, getServerBatchDiagnostics, pauseServerBatch, resolveModelCode,
  resumeServerBatch, submitServerBatch,
} from '../lib/jobsApi'
import type { ServerJobBatchDiagnostics } from '../lib/jobsApi'
import { randomUuid } from '../lib/randomUuid'
import {
  createInputImageFromFile,
  deleteImageIfUnreferenced,
  ensureImageCached,
  getBatchTryOnProfileError,
  runBatchTryOnTask,
  useStore,
} from '../store'
import BatchTryOnTemplateManager from './BatchTryOnTemplateManager'
import BatchTryOnGarmentList from './BatchTryOnGarmentList'
import BatchTryOnQueue from './BatchTryOnQueue'
import SizePickerModal from './SizePickerModal'
import BatchTryOnReviewDialog from './BatchTryOnReviewDialog'
import { useAuth } from '../app/AuthContext'
import type { BatchTryOnReviewDetail } from '../lib/batchTryOnReviewApi'
import { findNextPendingReviewItem } from '../lib/batchTryOnReviewQueue'
import {
  createProject, getProject, linkProjectAsset, unlinkProjectAsset, updateProjectAsset,
} from '../lib/contentApi'
import BatchTryOnPresetPanel from './BatchTryOnPresetPanel'
import {
  DEFAULT_BATCH_TRY_ON_PRESET_SELECTION,
  resolveBatchTryOnPresetSelection,
  summarizeBatchTryOnPresets,
} from '../lib/batchTryOnPresets'
import { buildBatchTryOnMatrix } from '../lib/batchTryOnMatrix'
import { getBatchTryOnConcurrencyOptions } from '../lib/batchTryOnConcurrency'

export const MAX_BATCH_TRY_ON_ITEMS = 50
export const MAX_BATCH_TRY_ON_TEMPLATES = 10
export const MAX_BATCH_TRY_ON_MATRIX_ITEMS = 500
const MAX_BATCH_TRY_ON_FILE_BYTES = 50 * 1024 * 1024
const MAX_MULTIUSER_FILE_BYTES = 20 * 1024 * 1024
const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
export default function BatchTryOnWorkspace() {
  const [searchParams] = useSearchParams()
  const auth = useAuth()
  const isAdmin = Boolean(auth.identity?.role_codes.some((role) => role === 'platform_admin' || role === 'organization_admin'))
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
  const serverPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [showSizePicker, setShowSizePicker] = useState(false)
  const [reviewItemId, setReviewItemId] = useState<string | null>(null)
  const [batchDiagnostics, setBatchDiagnostics] = useState<ServerJobBatchDiagnostics | null>(null)
  const loadedProjectRef = useRef<string | null>(null)
  const projectId = searchParams.get('project_id')
  const templateUpdated = searchParams.get('template_updated') === 'true'

  useEffect(() => {
    if (runtimeConfig.isStandalone || !projectId || loadedProjectRef.current === projectId) return
    let cancelled = false
    let completed = false
    loadedProjectRef.current = projectId
    void getProject(projectId).then(async (project) => {
      if (project.project_type !== 'batch_tryon') throw new Error('目标项目不是批量套图项目。')
      const templateLinks = project.assets.filter((link) => link.role === 'model_template')
      if (!templateLinks.length) throw new Error('该批量套图项目尚未设置模特模板图。')
      const current = useStore.getState().batchTryOnBatch
      const currentTemplates = current?.serverProjectId === project.id ? current.templates || [] : []
      const currentGarments = current?.serverProjectId === project.id ? current.garments || [] : []
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
        })
      }
      const garmentLinks = project.assets.filter((link) => link.role === 'garment')
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
        })
      }
      if (cancelled) return
      const draft = project.latest_version.draft_json
      const defaultTemplate = templates.find((item) => item.isDefault) || templates[0]
      setBatch((latest) => {
        const sameProject = latest?.serverProjectId === project.id
        const base = sameProject && latest ? latest : createEmptyBatch(globalParams)
        return {
          ...base,
          id: project.id,
          serverProjectId: project.id,
          serverProjectName: project.name,
          serverBatchId: sameProject ? base.serverBatchId : undefined,
          templateImageId: defaultTemplate.imageId,
          templateServerAssetId: defaultTemplate.serverAssetId,
          templateFileName: defaultTemplate.fileName,
          templateWidth: defaultTemplate.width,
          templateHeight: defaultTemplate.height,
          templateSourceType: draft.template_source_type === 'listing_generated_output' ? 'listing_generated_output' : 'upload',
          templateSourceId: typeof draft.template_source_id === 'string' ? draft.template_source_id : undefined,
          templates,
          garments,
          items: sameProject ? base.items : [],
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

  const activeProfile = getActiveApiProfile(settings)
  const profileError = runtimeConfig.isStandalone ? getBatchTryOnProfileError(settings) : null
  const progress = useMemo(() => summarizeItems(batch?.items ?? []), [batch?.items])
  const selectedTemplates = useMemo(() => (batch?.templates ?? []).filter((item) => item.selected), [batch?.templates])
  const selectedGarments = useMemo(() => (batch?.garments ?? []).filter((item) => item.selected), [batch?.garments])
  const estimatedGenerationCount = selectedTemplates.length * selectedGarments.length
  const outputSize = batch ? resolveOutputSize(batch) : 'auto'
  const isRunning = progress.running + progress.queued + progress.retry_waiting > 0
    || Boolean(batch && !batch.queuePaused && progress.pending > 0)
  const startDisabledReason = selectedTemplates.length === 0
    ? '请至少选择一张模特模板图'
    : selectedGarments.length === 0
      ? '请至少选择一张待套服装'
      : estimatedGenerationCount > MAX_BATCH_TRY_ON_MATRIX_ITEMS
        ? `本次组合不能超过 ${MAX_BATCH_TRY_ON_MATRIX_ITEMS} 张`
      : profileError
        ? profileError
        : ''

  const updateBatch = (patch: Partial<BatchTryOnBatch>) => {
    setBatch((current) => current ? { ...current, ...patch, updatedAt: Date.now() } : current)
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
    updateItem(batchId, itemId, { status: 'running', error: undefined, outputImageId: undefined, startedAt, finishedAt: undefined })

    try {
      const task = await runBatchTryOnTask({
        batchId,
        garmentFileName: item.garmentFileName,
        index: item.index,
        templateImageId: item.templateImageId,
        garmentImageId: item.garmentImageId,
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
    const concurrency = useStore.getState().batchTryOnBatch?.concurrency ?? 2
    if (!runnerRef.current) runnerRef.current = new BatchTryOnQueueController(runItem, concurrency)
    runnerRef.current.setConcurrency(concurrency)
    return runnerRef.current
  }

  const pollServerBatch = async (serverBatchId: string) => {
    if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
    serverPollTimerRef.current = null
    try {
      const serverBatch = await getServerBatch(serverBatchId)
      if (auth.hasPermission('audit.read')) {
        void getServerBatchDiagnostics(serverBatchId)
          .then(setBatchDiagnostics)
          .catch(() => setBatchDiagnostics(null))
      }
      const current = useStore.getState().batchTryOnBatch
      if (!current || current.serverBatchId !== serverBatchId) return
      const jobs = new Map<string | null, (typeof serverBatch.jobs)[number]>()
      for (const job of serverBatch.jobs) {
        const existing = jobs.get(job.client_item_id)
        if (!existing || job.is_current_review_version || (!existing.is_current_review_version && job.created_at > existing.created_at)) {
          jobs.set(job.client_item_id, job)
        }
      }
      const nextItems: BatchTryOnItem[] = []
      for (const item of current.items) {
        const job = jobs.get(item.id)
        if (!job) { nextItems.push(item); continue }
        if (job.status === 'succeeded' && job.outputs[0]) {
          let outputImageId = item.outputImageId
          if (!outputImageId || item.outputTaskId !== job.id) outputImageId = await importServerOutput(job.outputs[0])
          nextItems.push({
            ...item,
            taskId: job.id,
            outputTaskId: job.id,
            outputImageId,
            serverOutputAssetId: job.outputs[0].asset_id,
            serverOutputFilename: job.outputs[0].display_filename || job.outputs[0].filename,
            serverOutputDownloadFilename: job.outputs[0].download_filename || job.outputs[0].filename,
            serverOutputDownloadUrl: job.outputs[0].download_url,
            serverVersionNumber: job.review_version_number ?? undefined,
            status: 'done',
            error: undefined,
            finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : Date.now(),
            serverReviewItemId: job.review_item_id ?? item.serverReviewItemId,
            serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus']) ?? item.serverReviewStatus,
            serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId,
            serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId,
            regenerationCount: job.regeneration_count,
          })
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          nextItems.push({ ...item, taskId: job.id, status: job.status === 'cancelled' ? 'stopped' : 'error', error: job.error_message || (job.status === 'cancelled' ? '任务已取消' : '生成失败'), finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : Date.now(), serverReviewItemId: job.review_item_id ?? item.serverReviewItemId, serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus']) ?? 'generation_failed', serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId, serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId, regenerationCount: job.regeneration_count })
        } else {
          const status = serverBatch.status === 'paused'
            ? 'stopped'
            : job.status === 'running'
              ? 'running'
              : job.status === 'retry_waiting'
                ? 'retry_waiting'
                : 'queued'
          nextItems.push({
            ...item,
            taskId: job.id,
            status,
            error: undefined,
            startedAt: job.started_at ? new Date(job.started_at).getTime() : item.startedAt,
            serverReviewItemId: job.review_item_id ?? item.serverReviewItemId,
            serverReviewStatus: (job.review_status as BatchTryOnItem['serverReviewStatus']) ?? item.serverReviewStatus,
            serverCurrentVersionId: job.current_version_id ?? item.serverCurrentVersionId,
            serverApprovedVersionId: job.approved_version_id ?? item.serverApprovedVersionId,
            regenerationCount: job.regeneration_count,
            serverVersionNumber: job.review_version_number ?? item.serverVersionNumber,
          })
        }
      }
      const terminal = ['succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(serverBatch.status)
      setBatch({ ...current, items: nextItems, queuePaused: serverBatch.status === 'paused' || terminal, updatedAt: Date.now() })
      if (!terminal && serverBatch.status !== 'paused') {
        serverPollTimerRef.current = setTimeout(() => { void pollServerBatch(serverBatchId) }, 2_000)
      }
    } catch (error) {
      showToast(`批次状态同步失败，正在重试：${friendlyError(error)}`, 'error')
      serverPollTimerRef.current = setTimeout(() => { void pollServerBatch(serverBatchId) }, 5_000)
    }
  }

  const startServerItems = async (itemIds: string[]) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
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
              admin_test_mode: current.adminTestMode,
            },
          })
      const projectId = project.id
      const projectLinkByAssetRole = new Map(
        project.assets.map((link) => [`${link.role}:${link.asset.id}`, link.id]),
      )
      // The configured relay accepts multiple repeated `image` parts on /images/edits.
      // Keep the capability truthful: multi-image input is transported by image_edit.
      const modelCode = await resolveModelCode('image_edit', 'batch_tryon.generate')
      const templateAssets = new Map<string, string>()
      const garmentAssets = new Map<string, string>()
      const templateProjectLinks = new Map<string, string>()
      const garmentProjectLinks = new Map<string, string>()
      const requestItems = []
      for (const item of selectedItems) {
        const template = current.templates.find((candidate) => candidate.id === item.templateId)
        if (!item.templateImageId) throw new Error(`${item.templateName || '模板图'} 读取失败，请重新上传。`)
        let templateAssetId = item.templateServerAssetId
          || template?.serverAssetId
          || templateAssets.get(item.templateId || item.templateImageId)
        if (!templateAssetId) {
          const templateDataUrl = await ensureImageCached(item.templateImageId)
          if (!templateDataUrl) throw new Error(`${item.templateName || '模板图'} 读取失败，请重新上传。`)
          templateAssetId = (await uploadDataUrlAsset(templateDataUrl, 'model_template', item.templateName || 'model-template')).id
          templateAssets.set(item.templateId || item.templateImageId, templateAssetId)
        }
        const templateLinkKey = `model_template:${templateAssetId}`
        let templateProjectLinkId = template?.projectAssetLinkId || projectLinkByAssetRole.get(templateLinkKey)
        if (!templateProjectLinkId) {
          project = await linkProjectAsset(
            projectId,
            templateAssetId,
            'model_template',
            template?.isDefault ? 0 : Math.max(1, current.templates.indexOf(template!) + 1),
            template?.displayName || item.templateName,
            Boolean(template?.isDefault),
          )
          templateProjectLinkId = project.assets.find(
            (link) => link.role === 'model_template' && link.asset.id === templateAssetId,
          )?.id
          if (templateProjectLinkId) projectLinkByAssetRole.set(templateLinkKey, templateProjectLinkId)
        }
        if (templateProjectLinkId && item.templateId) templateProjectLinks.set(item.templateId, templateProjectLinkId)

        const garment = current.garments.find((candidate) => candidate.id === item.garmentId)
        let garmentAssetId = item.garmentServerAssetId
          || garment?.serverAssetId
          || garmentAssets.get(item.garmentId || item.garmentImageId)
        const garmentDataUrl = await ensureImageCached(item.garmentImageId)
        if (!garmentDataUrl) throw new Error(`${item.garmentFileName} 读取失败，请重新上传。`)
        if (!garmentAssetId) {
          garmentAssetId = (await uploadDataUrlAsset(garmentDataUrl, 'garment', item.garmentFileName)).id
          garmentAssets.set(item.garmentId || item.garmentImageId, garmentAssetId)
        }
        const garmentLinkKey = `garment:${garmentAssetId}`
        let garmentProjectLinkId = garment?.projectAssetLinkId || projectLinkByAssetRole.get(garmentLinkKey)
        if (!garmentProjectLinkId) {
          project = await linkProjectAsset(
            projectId,
            garmentAssetId,
            'garment',
            garment?.index ?? item.index,
            item.garmentFileName,
          )
          garmentProjectLinkId = project.assets.find(
            (link) => link.role === 'garment' && link.asset.id === garmentAssetId,
          )?.id
          if (garmentProjectLinkId) projectLinkByAssetRole.set(garmentLinkKey, garmentProjectLinkId)
        }
        if (garmentProjectLinkId && item.garmentId) garmentProjectLinks.set(item.garmentId, garmentProjectLinkId)

        const size = resolveOutputSizeForTemplate(current, template)
        const aspectRatio = resolveOutputAspectRatioForTemplate(current, template)
        const presetSelection = item.presetSelection || current.presetSelection
        const presetSummary = item.presetSummary || summarizeBatchTryOnPresets(presetSelection)
        requestItems.push({
          client_item_id: item.id,
          prompt: buildBatchTryOnPrompt({
            garmentFileName: item.garmentFileName,
            templateName: item.templateName,
            outputSize: size,
            presetSelection,
            extraRequirements: current.extraRequirements,
          }),
          reference_asset_ids: [templateAssetId, garmentAssetId],
          size,
          aspect_ratio: aspectRatio,
          quality: current.params.quality,
          output_format: current.params.output_format,
          output_compression: current.params.output_compression,
          metadata: {
            garment_filename: item.garmentFileName,
            garment_id: item.garmentId,
            template_id: item.templateId,
            template_name: item.templateName,
            preset_codes: presetSelection,
            preset_summary: presetSummary,
            index: item.index,
          },
        })
      }
      setBatch((latest) => latest?.id === current.id ? syncLegacyTemplateFields({
        ...latest,
        serverProjectId: projectId,
        serverProjectName: project.name,
        templates: latest.templates.map((template) => ({
          ...template,
          serverAssetId: template.serverAssetId || templateAssets.get(template.id),
          projectAssetLinkId: template.projectAssetLinkId || templateProjectLinks.get(template.id),
        })),
        garments: latest.garments.map((garment) => ({
          ...garment,
          serverAssetId: garment.serverAssetId || garmentAssets.get(garment.id),
          projectAssetLinkId: garment.projectAssetLinkId || garmentProjectLinks.get(garment.id),
        })),
        items: latest.items.map((item) => ({
          ...item,
          templateServerAssetId: item.templateServerAssetId || (item.templateId ? templateAssets.get(item.templateId) : undefined),
          garmentServerAssetId: item.garmentServerAssetId || (item.garmentId ? garmentAssets.get(item.garmentId) : undefined),
        })),
        updatedAt: Date.now(),
      }) : latest)
      const submitted = await submitServerBatch({
        name: `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
        workspace_type: 'batch_tryon',
        operation_code: 'batch_tryon.generate',
        capability: 'image_edit',
        model_code: modelCode,
        idempotency_key: `batch:${randomUuid()}`,
        project_id: projectId,
        concurrency: current.concurrency,
        admin_test_mode: current.adminTestMode,
        items: requestItems,
      })
      const jobByItem = new Map(submitted.jobs.map((job) => [job.client_item_id, job]))
      setBatch((latest) => latest?.id === current.id ? {
        ...latest,
        serverBatchId: submitted.id,
        queuePaused: false,
        items: latest.items.map((item) => itemIds.includes(item.id)
          ? { ...item, taskId: jobByItem.get(item.id)?.id, status: 'queued', error: undefined, outputImageId: undefined, outputTaskId: undefined, serverOutputAssetId: undefined, serverOutputFilename: undefined, serverOutputDownloadFilename: undefined, serverOutputDownloadUrl: undefined, serverVersionNumber: jobByItem.get(item.id)?.review_version_number ?? undefined, startedAt: undefined, finishedAt: undefined, serverReviewItemId: jobByItem.get(item.id)?.review_item_id ?? undefined, serverReviewStatus: (jobByItem.get(item.id)?.review_status as BatchTryOnItem['serverReviewStatus']) ?? 'pending', serverCurrentVersionId: jobByItem.get(item.id)?.current_version_id ?? undefined, serverApprovedVersionId: jobByItem.get(item.id)?.approved_version_id ?? undefined, regenerationCount: jobByItem.get(item.id)?.regeneration_count ?? 0 }
          : item),
        updatedAt: Date.now(),
      } : latest)
      showToast(`服务端批次已创建，共 ${submitted.total_jobs} 个任务`, 'success')
      void pollServerBatch(submitted.id)
    } catch (error) {
      setBatch((latest) => latest ? { ...latest, queuePaused: true, items: latest.items.map((item) => itemIds.includes(item.id) ? { ...item, status: 'error', error: friendlyError(error), finishedAt: Date.now() } : item), updatedAt: Date.now() } : latest)
      showToast(friendlyError(error), 'error')
    }
  }

  useEffect(() => {
    if (!runtimeConfig.isStandalone && batch?.serverBatchId) {
      void pollServerBatch(batch.serverBatchId)
    }
    return () => {
      if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
      serverPollTimerRef.current = null
    }
    // 恢复只跟随服务端批次 ID，避免每次轮询更新 items 后重复启动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.serverBatchId])

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
      void startServerItems(itemIds)
      return
    }
    void getRunner().start(itemIds).then(() => {
      setBatch((current) => current ? { ...current, queuePaused: false, updatedAt: Date.now() } : current)
    })
  }

  const startNewMatrix = () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current || startDisabledReason) return
    const matrix = buildBatchTryOnMatrix(current)
    if (!matrix.length) return
    if (matrix.length > MAX_BATCH_TRY_ON_MATRIX_ITEMS) {
      showToast(`单个批次最多生成 ${MAX_BATCH_TRY_ON_MATRIX_ITEMS} 张图片`, 'error')
      return
    }
    setBatch({
      ...current,
      serverBatchId: undefined,
      items: matrix,
      queuePaused: false,
      updatedAt: Date.now(),
    })
    startItems(matrix.map((item) => item.id))
  }

  const pauseQueue = () => {
    if (!runtimeConfig.isStandalone && batch?.serverBatchId) {
      void pauseServerBatch(batch.serverBatchId).then(() => {
        if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
        serverPollTimerRef.current = null
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
    if (isRunning || files.length === 0) return
    const current = normalizeBatchTryOnBatch(batch ?? createEmptyBatch(globalParams))
    const remaining = MAX_BATCH_TRY_ON_TEMPLATES - current.templates.length
    if (remaining <= 0) {
      showToast(`模板图最多 ${MAX_BATCH_TRY_ON_TEMPLATES} 张`, 'error')
      return
    }
    const added: BatchTryOnTemplate[] = []
    const errors: string[] = []
    for (const file of files.slice(0, remaining)) {
      try {
        validateImageFile(file)
        const image = await createInputImageFromFile(file)
        if (!image) throw new Error('模板图读取失败')
        const stored = await getImage(image.id)
        added.push({
          id: createId(),
          imageId: image.id,
          fileName: file.name,
          displayName: stripExtension(file.name),
          width: stored?.width,
          height: stored?.height,
          selected: true,
          isDefault: current.templates.length === 0 && added.length === 0,
          sourceType: 'upload',
        })
      } catch (error) {
        errors.push(`${file.name}：${friendlyError(error)}`)
      }
    }
    if (added.length) {
      setBatch(syncLegacyTemplateFields({
        ...current,
        templates: [...current.templates, ...added],
        queuePaused: true,
        updatedAt: Date.now(),
      }))
      showToast(`已添加 ${added.length} 张模板图`, 'success')
    }
    if (files.length > remaining) errors.push(`超过上限的 ${files.length - remaining} 张模板未添加`)
    if (errors.length) showToast(errors[0], 'error')
  }

  const removeTemplate = (template: BatchTryOnTemplate) => {
    if (isRunning) return
    if (batch?.serverProjectId && template.projectAssetLinkId) {
      void unlinkProjectAsset(batch.serverProjectId, template.projectAssetLinkId)
        .catch((error) => showToast(`模板项目关联删除失败：${friendlyError(error)}`, 'error'))
    }
    setBatch((current) => {
      if (!current) return current
      const templates = current.templates.filter((candidate) => candidate.id !== template.id)
      if (templates.length && !templates.some((candidate) => candidate.isDefault)) templates[0] = { ...templates[0], isDefault: true }
      return syncLegacyTemplateFields({
        ...current,
        templates,
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

  const renameTemplate = (templateId: string, displayName: string) => {
    const template = batch?.templates.find((item) => item.id === templateId)
    updateTemplates((templates) => templates.map((item) => item.id === templateId ? { ...item, displayName } : item))
    if (batch?.serverProjectId && template?.projectAssetLinkId && displayName.trim()) {
      void updateProjectAsset(batch.serverProjectId, template.projectAssetLinkId, { display_name: displayName.trim() })
        .catch((error) => showToast(`模板名称保存失败：${friendlyError(error)}`, 'error'))
    }
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
    if (isRunning || files.length === 0) return
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
      setBatch({ ...current, garments: [...current.garments, ...added], queuePaused: true, updatedAt: Date.now() })
      showToast(`已添加 ${added.length} 张待套服装`, 'success')
    }
    if (files.length > remaining) errors.push(`超过上限的 ${files.length - remaining} 张图片未添加`)
    if (errors.length > 0) showToast(errors[0], 'error')
  }

  const removeGarment = (item: BatchTryOnGarment) => {
    if (isRunning) return
    if (batch?.serverProjectId && item.projectAssetLinkId) {
      void unlinkProjectAsset(batch.serverProjectId, item.projectAssetLinkId)
        .catch((error) => showToast(`服装项目关联删除失败：${friendlyError(error)}`, 'error'))
    }
    setBatch((current) => current ? {
      ...current,
      garments: current.garments.filter((candidate) => candidate.id !== item.id).map((candidate, index) => ({ ...candidate, index })),
      items: current.items.filter((candidate) => candidate.garmentId !== item.id),
      updatedAt: Date.now(),
    } : current)
    window.setTimeout(() => void deleteImageIfUnreferenced(item.garmentImageId), 0)
  }

  const clearGarments = () => {
    if (!batch || isRunning) return
    const ids = batch.garments.map((item) => item.garmentImageId)
    if (batch.serverProjectId) {
      for (const garment of batch.garments) {
        if (garment.projectAssetLinkId) {
          void unlinkProjectAsset(batch.serverProjectId, garment.projectAssetLinkId)
            .catch((error) => showToast(`服装项目关联删除失败：${friendlyError(error)}`, 'error'))
        }
      }
    }
    updateBatch({ garments: [], items: [], queuePaused: true })
    window.setTimeout(() => ids.forEach((id) => void deleteImageIfUnreferenced(id)), 0)
  }

  const clearBatch = () => {
    if (!batch) return
    const imageIds = [
      ...batch.templates.map((item) => item.imageId),
      ...batch.garments.map((item) => item.garmentImageId),
    ]
    runnerRef.current?.stopPending()
    runnerRef.current = null
    setBatch(null)
    window.setTimeout(() => imageIds.forEach((id) => void deleteImageIfUnreferenced(id)), 0)
    showToast('当前批次已清空', 'success')
  }

  const requestClearBatch = () => {
    if (progress.running === 0) {
      clearBatch()
      return
    }
    setConfirmDialog({
      title: '清空当前批次？',
      message: '已经发送的生成请求不会被强制终止，完成后仍会保留在历史记录中；尚未开始的任务会停止。',
      confirmText: '清空批次',
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
    if (!item.outputImageId) return
    const [fileName] = createBatchTryOnFileNames([item])
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
    const items = batch.items.flatMap((item) => item.outputImageId ? [{ imageId: item.outputImageId, garmentFileName: item.garmentFileName, templateName: item.templateName, index: item.index }] : [])
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
    if (taskId && current.serverBatchId) void pollServerBatch(current.serverBatchId)
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
      <div className="grid gap-4 xl:grid-cols-2">
        <BatchTryOnTemplateManager
          templates={batch.templates}
          maxItems={MAX_BATCH_TRY_ON_TEMPLATES}
          disabled={isRunning}
          onUpload={(files) => void uploadTemplates(files)}
          onRemove={removeTemplate}
          onRename={renameTemplate}
          onSetDefault={setDefaultTemplate}
          onToggle={(templateId) => updateTemplates((templates) => templates.map((item) => item.id === templateId ? { ...item, selected: !item.selected } : item))}
          onToggleAll={(selected) => updateTemplates((templates) => templates.map((item) => ({ ...item, selected })))}
          onView={(imageId) => setLightboxImageId(imageId)}
        />
        <div id="batch-tryon-garments"><BatchTryOnGarmentList
          items={batch.garments}
          maxItems={MAX_BATCH_TRY_ON_ITEMS}
          disabled={isRunning}
          onUpload={(files) => void uploadGarments(files)}
          onRemove={removeGarment}
          onClear={clearGarments}
          onToggle={(garmentId) => updateBatch({ garments: batch.garments.map((item) => item.id === garmentId ? { ...item, selected: !item.selected } : item) })}
          onToggleAll={(selected) => updateBatch({ garments: batch.garments.map((item) => ({ ...item, selected })) })}
          onView={(imageId) => setLightboxImageId(imageId)}
        /></div>
      </div>

      <BatchTryOnPresetPanel
        selection={batch.presetSelection}
        disabled={isRunning}
        onChange={(presetSelection) => updateBatch({ presetSelection })}
      />

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.85fr)]">
          <label>
            <span className="text-sm font-bold text-gray-900 dark:text-gray-100">额外要求</span>
            <textarea value={batch.extraRequirements} disabled={isRunning} onChange={(event) => updateBatch({ extraRequirements: event.target.value })} className="mt-2 min-h-32 w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100" placeholder="例如：衣服自然放下，不要塞进裤子；保持原图只展示到膝盖；服装使用印染效果，不要变成刺绣。" />
            <span className="mt-1.5 block text-xs text-gray-400">只影响当前批次，且不会覆盖内置的服装与模特保真规则。</span>
          </label>
          <div>
            <div className="text-sm font-bold text-gray-900 dark:text-gray-100">输出设置</div>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              <label className="min-w-0"><span className="mb-1 block text-xs text-gray-500 dark:text-gray-400">比例与交付尺寸</span><button type="button" disabled={isRunning} onClick={() => setShowSizePicker(true)} className="h-9 w-full rounded-lg border border-gray-200 bg-gray-50 px-2 text-left text-xs font-semibold text-gray-800 outline-none transition hover:border-blue-300 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100">{batch.aspectRatio === 'template' ? '跟随模板' : batch.aspectRatio} · {outputSize}</button></label>
              <FieldSelect label="输出质量" value={batch.params.quality} disabled={isRunning} onChange={(value) => updateBatch({ params: { ...batch.params, quality: value as TaskParams['quality'] } })} options={['high', 'medium', 'low', 'auto'].map((value) => ({ value, label: value }))} />
              <FieldSelect label="输出格式" value={batch.params.output_format} disabled={isRunning} onChange={(value) => updateBatch({ params: { ...batch.params, output_format: value as TaskParams['output_format'] } })} options={[{ value: 'jpeg', label: 'JPEG' }, { value: 'png', label: 'PNG' }, { value: 'webp', label: 'WEBP' }]} />
              <FieldSelect
                label={batch.adminTestMode ? '管理员测试并发' : '并发数'}
                value={String(batch.concurrency)}
                disabled={isRunning}
                onChange={(value) => updateBatch({ concurrency: Number(value) as BatchTryOnBatch['concurrency'] })}
                options={getBatchTryOnConcurrencyOptions(isAdmin, batch.adminTestMode).map((value) => ({ value: String(value), label: `${value}` }))}
              />
            </div>
            {isAdmin && <label className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-100">
              <input
                type="checkbox"
                checked={batch.adminTestMode}
                disabled={isRunning}
                onChange={(event) => updateBatch({
                  adminTestMode: event.target.checked,
                  concurrency: event.target.checked ? batch.concurrency : Math.min(batch.concurrency, 3) as BatchTryOnBatch['concurrency'],
                })}
              />
              <span><strong>管理员测试模式</strong><br />允许目标并发 5 或 10；实际并发仍受 Worker、团队、用户和资源池上限约束。</span>
            </label>}
            <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-xs text-gray-600 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-300">
              <div>输出尺寸：<span className="font-mono font-semibold">{outputSize}</span> · 每个模板 × 每件服装生成 1 张结果</div>
              <div className="mt-1 font-semibold text-blue-700 dark:text-blue-300">已选模板 {selectedTemplates.length} · 已选服装 {selectedGarments.length} · 预计生成 {estimatedGenerationCount} 张</div>
              {batch.aspectRatio !== 'template' && <button type="button" disabled={isRunning} onClick={() => updateBatch({ aspectRatio: 'template', params: { ...batch.params, size: 'auto', aspect_ratio: 'auto' } })} className="mt-1 font-semibold text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-300">恢复跟随模板图（默认 2K）</button>}
              <div className="mt-1">生图配置：{runtimeConfig.isStandalone ? `${activeProfile.name} · ${activeProfile.model}` : '平台统一资源池（服务端安全调用）'}</div>
              {profileError && <button type="button" onClick={() => setShowSettings(true, 'api')} className="mt-2 text-left font-semibold text-red-600 underline decoration-red-300 underline-offset-2 dark:text-red-300">{profileError} 点击前往设置</button>}
            </div>
          </div>
        </div>
      </section>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">任务队列与结果</h3>
            <div className="mt-1 text-sm text-gray-600 dark:text-gray-300">已完成 {progress.done} / {batch.items.length}，失败 {progress.error}，生成中 {progress.running}，等待队列 {progress.queued + progress.retry_waiting}，未提交 {progress.pending}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {!isRunning && <button type="button" disabled={Boolean(startDisabledReason)} title={startDisabledReason} onClick={startNewMatrix} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">生成 {estimatedGenerationCount} 个组合</button>}
            {isRunning && !batch.queuePaused && <button type="button" onClick={pauseQueue} className="h-10 rounded-xl border border-amber-200 bg-amber-50 px-3 text-sm font-semibold text-amber-700 transition hover:bg-amber-100 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">暂停队列</button>}
            {batch.queuePaused && (progress.stopped > 0 || (progress.pending > 0 && batch.items.some((item) => item.startedAt))) && <button type="button" disabled={Boolean(profileError || !batch.templates.length)} onClick={resumeQueue} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">继续生成</button>}
            {progress.error > 0 && <button type="button" onClick={() => startItems(getFailedBatchTryOnItemIds(batch.items))} className="h-10 rounded-xl border border-gray-200 px-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.06]">重试失败任务</button>}
            {progress.done > 0 && <button type="button" onClick={() => void downloadAll()} className="h-10 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200">下载成功结果</button>}
            <button type="button" onClick={requestClearBatch} className="h-10 rounded-xl px-3 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-400/10">清空当前批次</button>
          </div>
        </div>
        {startDisabledReason && !isRunning && <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">暂时无法开始：{startDisabledReason}</div>}
        {batchDiagnostics && auth.hasPermission('audit.read') && (
          <div className="mt-3 grid gap-2 rounded-xl border border-blue-100 bg-blue-50/60 p-3 text-xs text-blue-900 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-100 sm:grid-cols-2 lg:grid-cols-4">
            <span>目标并发 {batchDiagnostics.configured_concurrency} · 有效上限 {batchDiagnostics.effective_concurrency}</span>
            <span>当前运行 {batchDiagnostics.active_jobs} · 实际峰值 {batchDiagnostics.actual_max_concurrency}</span>
            <span>排队 {batchDiagnostics.status_counts.queued || 0} · 重试中 {batchDiagnostics.status_counts.retry_waiting || 0}</span>
            <span>成功 {batchDiagnostics.status_counts.succeeded || 0} · 失败 {batchDiagnostics.status_counts.failed || 0}</span>
            <span>平均耗时 {formatDiagnosticDuration(batchDiagnostics.average_generation_ms)}</span>
            <span>429 {batchDiagnostics.http_status_counts['429'] || 0} · 5xx {count5xx(batchDiagnostics.http_status_counts)} · timeout {countTimeouts(batchDiagnostics.error_code_counts)}</span>
            <span>Worker {batchDiagnostics.online_workers.length} 个 · 配置并发 {batchDiagnostics.worker_concurrency}</span>
            <span className={batchDiagnostics.stale_jobs ? 'font-semibold text-red-600 dark:text-red-300' : ''}>Broker {batchDiagnostics.broker_queue_length} · 失联 {batchDiagnostics.stale_jobs}</span>
            <span>资源池配置 {batchDiagnostics.resource_key_capacity} · 当前可用 {batchDiagnostics.resource_available_capacity}</span>
            {batchDiagnostics.limitation_reasons.length > 0 && <span className="sm:col-span-2 lg:col-span-4 rounded-lg bg-amber-50 px-2 py-1.5 font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">并发受限：{batchDiagnostics.limitation_reasons.join('；')}</span>}
            {batchDiagnostics.availability_reasons.length > 0 && <span className="sm:col-span-2 lg:col-span-4 rounded-lg bg-amber-50 px-2 py-1.5 font-semibold text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">临时等待：{batchDiagnostics.availability_reasons.join('；')}</span>}
          </div>
        )}
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${batch.items.length ? ((progress.done + progress.error) / batch.items.length) * 100 : 0}%` }} /></div>
        <div className="mt-4">
          <BatchTryOnQueue items={batch.items} onView={(imageId) => setLightboxImageId(imageId, batch.items.flatMap((item) => item.outputImageId ? [item.outputImageId] : []))} onDownload={(item) => void downloadOne(item)} onRetry={(item) => startItems([item.id])} onReview={(item) => item.serverReviewItemId && setReviewItemId(item.serverReviewItemId)} />
        </div>
      </section>
      {showSizePicker && <SizePickerModal currentSize={outputSize} currentAspectRatio={resolveOutputAspectRatio(batch)} allowAuto={false} onSelect={(size, aspectRatio) => { updateBatch({ aspectRatio: aspectRatio as BatchTryOnAspectRatio, params: { ...batch.params, size, aspect_ratio: aspectRatio } }); setShowSizePicker(false) }} onClose={() => setShowSizePicker(false)} />}
      {reviewItemId && !runtimeConfig.isStandalone && <BatchTryOnReviewDialog
        itemId={reviewItemId}
        items={batch.items}
        canApprove={auth.hasPermission('batch_tryon.review')}
        canRegenerate={auth.hasPermission('batch_tryon.review') && auth.hasPermission('jobs.submit')}
        onClose={() => setReviewItemId(null)}
        onSelectItem={setReviewItemId}
        onChanged={applyReviewChange}
        onAdvance={advanceReview}
      />}
    </div>
  )
}

function FieldSelect({ label, value, options, disabled, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; disabled?: boolean; onChange: (value: string) => void }) {
  return <label className="min-w-0"><span className="mb-1 block text-xs text-gray-500 dark:text-gray-400">{label}</span><select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-gray-200 bg-gray-50 px-2 text-xs font-semibold text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100">{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
}

function createEmptyBatch(globalParams: TaskParams): BatchTryOnBatch {
  const now = Date.now()
  return {
    id: createId(),
    templateImageId: null,
    templates: [],
    garments: [],
    items: [],
    presetSelection: { ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION },
    extraRequirements: '',
    aspectRatio: 'template',
    concurrency: 2,
    adminTestMode: false,
    params: { ...globalParams, quality: 'high', n: 1 },
    queuePaused: true,
    createdAt: now,
    updatedAt: now,
  }
}

function createId() {
  return randomUuid()
}

function validateImageFile(file: File) {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type.toLowerCase())) throw new Error('图片格式不支持，请使用 PNG、JPG、JPEG 或 WEBP。')
  const maxBytes = runtimeConfig.isStandalone ? MAX_BATCH_TRY_ON_FILE_BYTES : MAX_MULTIUSER_FILE_BYTES
  if (file.size > maxBytes) throw new Error(`单张图片不能超过 ${maxBytes / 1024 / 1024} MB。`)
}

function resolveOutputSize(batch: BatchTryOnBatch) {
  if (batch.aspectRatio !== 'template' && batch.params.size && batch.params.size !== 'auto') return batch.params.size
  const ratio = batch.aspectRatio === 'template'
    ? batch.templateWidth && batch.templateHeight ? `${batch.templateWidth}:${batch.templateHeight}` : '1:1'
    : batch.aspectRatio
  return calculateDeliverySize('2K', ratio) || '2048x2048'
}

function resolveOutputSizeForTemplate(batch: BatchTryOnBatch, template?: BatchTryOnTemplate) {
  if (batch.aspectRatio !== 'template') return resolveOutputSize(batch)
  const ratio = template?.width && template.height ? `${template.width}:${template.height}` : '1:1'
  return calculateDeliverySize('2K', ratio) || '2048x2048'
}

function resolveOutputAspectRatio(batch: BatchTryOnBatch) {
  if (batch.aspectRatio !== 'template') return batch.aspectRatio
  if (!batch.templateWidth || !batch.templateHeight) return '1:1'
  return resolveImageSize(`${batch.templateWidth}x${batch.templateHeight}`, 'auto').aspectRatio
}

function resolveOutputAspectRatioForTemplate(batch: BatchTryOnBatch, template?: BatchTryOnTemplate) {
  if (batch.aspectRatio !== 'template') return resolveOutputAspectRatio(batch)
  if (!template?.width || !template.height) return '1:1'
  return resolveImageSize(`${template.width}x${template.height}`, 'auto').aspectRatio
}

function normalizeBatchTryOnBatch(batch: BatchTryOnBatch): BatchTryOnBatch {
  const raw = batch as BatchTryOnBatch & {
    templates?: BatchTryOnTemplate[]
    garments?: BatchTryOnGarment[]
    presetSelection?: BatchTryOnBatch['presetSelection']
    adminTestMode?: boolean
  }
  const templates = Array.isArray(raw.templates) ? raw.templates : batch.templateImageId ? [{
    id: `legacy-template-${batch.templateImageId}`,
    imageId: batch.templateImageId,
    serverAssetId: batch.templateServerAssetId,
    fileName: batch.templateFileName || 'model-template.png',
    displayName: stripExtension(batch.templateFileName || '默认模板'),
    width: batch.templateWidth,
    height: batch.templateHeight,
    selected: true,
    isDefault: true,
    sourceType: batch.templateSourceType,
    sourceId: batch.templateSourceId,
  }] : []
  const defaultTemplate = templates.find((item) => item.isDefault) || templates[0]
  const garments = Array.isArray(raw.garments) ? raw.garments : Array.from(
    new Map(batch.items.map((item) => [
      item.garmentId || item.garmentImageId,
      {
        id: item.garmentId || item.id,
        batchId: batch.id,
        garmentImageId: item.garmentImageId,
        serverAssetId: item.garmentServerAssetId,
        garmentFileName: item.garmentFileName,
        index: item.index,
        selected: true,
        createdAt: item.createdAt,
      } satisfies BatchTryOnGarment,
    ])).values(),
  )
  const presetSelection = resolveBatchTryOnPresetSelection({
    ...DEFAULT_BATCH_TRY_ON_PRESET_SELECTION,
    ...(raw.presetSelection || {}),
  })
  return syncLegacyTemplateFields({
    ...batch,
    templates,
    garments,
    items: batch.items.map((item) => ({
      ...item,
      templateId: item.templateId || defaultTemplate?.id,
      templateImageId: item.templateImageId || defaultTemplate?.imageId,
      templateServerAssetId: item.templateServerAssetId || defaultTemplate?.serverAssetId,
      templateName: item.templateName || defaultTemplate?.displayName,
      garmentId: item.garmentId || garments.find((garment) => garment.garmentImageId === item.garmentImageId)?.id,
      presetSelection: item.presetSelection || presetSelection,
      presetSummary: item.presetSummary || summarizeBatchTryOnPresets(item.presetSelection || presetSelection),
    })),
    presetSelection,
    adminTestMode: Boolean(raw.adminTestMode),
    concurrency: ([1, 2, 3, 5, 10].includes(Number(batch.concurrency)) ? batch.concurrency : 2),
  })
}

function syncLegacyTemplateFields(batch: BatchTryOnBatch): BatchTryOnBatch {
  const defaultTemplate = batch.templates.find((item) => item.isDefault) || batch.templates[0]
  return {
    ...batch,
    templateImageId: defaultTemplate?.imageId || null,
    templateServerAssetId: defaultTemplate?.serverAssetId,
    templateSourceType: defaultTemplate?.sourceType,
    templateSourceId: defaultTemplate?.sourceId,
    templateFileName: defaultTemplate?.fileName,
    templateWidth: defaultTemplate?.width,
    templateHeight: defaultTemplate?.height,
  }
}

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').trim() || '未命名模板'
}

function formatDiagnosticDuration(value: number | null) {
  if (value == null) return '—'
  return value < 1_000 ? `${value}ms` : `${Math.round(value / 100) / 10}s`
}

function count5xx(statusCounts: Record<string, number>) {
  return Object.entries(statusCounts).reduce((sum, [status, count]) => /^5\d\d$/.test(status) ? sum + count : sum, 0)
}

function countTimeouts(errorCounts: Record<string, number>) {
  return Object.entries(errorCounts).reduce((sum, [code, count]) => /timeout/i.test(code) ? sum + count : sum, 0)
}

function resetItemForNewRun(item: BatchTryOnItem): BatchTryOnItem {
  return {
    ...item,
    status: 'pending',
    taskId: undefined,
    outputImageId: undefined,
    outputTaskId: undefined,
    serverReviewItemId: undefined,
    serverReviewStatus: undefined,
    serverCurrentVersionId: undefined,
    serverApprovedVersionId: undefined,
    regenerationCount: undefined,
    error: undefined,
    startedAt: undefined,
    finishedAt: undefined,
  }
}

function summarizeItems(items: BatchTryOnItem[]) {
  return items.reduce((summary, item) => {
    summary[item.status]++
    return summary
  }, { pending: 0, queued: 0, retry_waiting: 0, running: 0, done: 0, error: 0, stopped: 0 })
}

function friendlyError(error: unknown) {
  if (error instanceof DOMException && error.name === 'AbortError') return '请求超时或已中断，请重试。'
  const message = error instanceof Error ? error.message : String(error)
  if (/timeout|timed out|超时/i.test(message)) return `请求超时：${message}`
  if (/empty|没有返回|no image/i.test(message)) return `API 返回空图片：${message}`
  return message || '操作失败，请重试。'
}
