import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import AttachmentImageModuleCard from '../components/attachment-image/AttachmentImageModuleCard'
import type { AttachmentResultEntry } from '../components/attachment-image/AttachmentResultReviewPanel'
import AttachmentMaterialSaveDialog from '../components/attachment-image/AttachmentMaterialSaveDialog'
import AttachmentCreativeContextPanel from '../components/attachment-image/AttachmentCreativeContextPanel'
import AttachmentProductIdentityPanel from '../components/attachment-image/AttachmentProductIdentityPanel'
import BatchTryOnGarmentPreprocessDialog, { type GarmentReferencePreview } from '../components/BatchTryOnGarmentPreprocessDialog'
import AuthenticatedImage from '../components/category-listing/AuthenticatedImage'
import {
  ATTACHMENT_WORKBENCH_CONFIG_KEY,
  attachmentModuleDefinitions,
  countRequestedAttachmentImages,
  isAttachmentSessionReady,
  normalizeAttachmentWorkbenchDraft,
  selectedAttachmentModules,
  summarizeAttachmentTaskGroups,
  type AttachmentModuleCode,
  type AttachmentWorkbenchDraft,
} from '../lib/attachmentImageWorkbench'
import { getAsset, type Asset } from '../lib/contentApi'
import { uploadGarmentReferenceDataUrl } from '../lib/serverImageAssets'
import { garmentTransformMetadata } from '../lib/batchTryOnGarmentPreprocess'
import type { BatchTryOnGarment } from '../types'
import {
  createCategoryOutputProject,
  cancelListingImageTaskGroup,
  getCategoryOutputProject,
  getListingOutputOptions,
  getListingWorkflowSession,
  listListingImageTaskGroups,
  listListingWorkflowSessions,
  retryFailedListingImageTaskGroup,
  updateCategoryOutputProject,
  type CategoryOutputProject,
  type ListingImageTaskGroup,
  type ListingImageTask,
  type ListingWorkflowSession,
  type ListingWorkflowSessionSummary,
} from '../lib/listingWorkflowApi'
import { useStore } from '../store'
import { AuthApiError } from '../lib/authApi'
import {
  getAttachmentPlanning,
  getAttachmentReferences,
  getAttachmentProductCompositions,
  getAttachmentProductIdentityLock,
  reextractAttachmentProductIdentityLock,
  updateAttachmentProductIdentityLock,
  updateAttachmentProductMode,
  addAttachmentSecondaryProduct,
  replaceAttachmentSecondaryProduct,
  removeAttachmentSecondaryProduct,
  addAttachmentReference,
  removeAttachmentReference,
  analyzeAttachmentReferences,
  putAttachmentProductReference,
  listAttachmentPlanVersions,
  optimizeAttachmentModulePrompt,
  planAttachmentSuite,
  replanAttachmentModule,
  updateAttachmentModule,
  updateAttachmentVisualDirection,
  type AttachmentPlanningState,
  type AttachmentPlanVersion,
  type AttachmentReferenceState,
  type AttachmentReferenceSlotType,
  type AttachmentGenerationPreview,
  previewAttachmentGeneration,
  generateAttachments,
  discardAttachmentResults,
  getAttachmentResultState,
  resetAttachmentModule,
  retryAttachmentJob,
  reviewAttachmentOutput,
  setAttachmentFinal,
  startAttachmentCreativePlanning,
  getAttachmentCreativePlanning,
  adoptAttachmentCreativeDirection,
  type AttachmentResultState,
  type AttachmentProductComposition,
  type AttachmentProductIdentityLock,
} from '../lib/attachmentPlanningApi'
import { randomUuid } from '../lib/randomUuid'
import {
  getAttachmentMaterialSaveContext,
  getAttachmentMaterialSet,
  saveAttachmentMaterialOutput,
  saveAttachmentMaterialSet,
  type AttachmentMaterialSaveContext,
  type AttachmentMaterialSaveInput,
} from '../lib/attachmentMaterialApi'
import {
  getAttachmentCreativeContext,
  listAIModelPresets,
  listThemePresets,
  listVisualPresets,
  updateAttachmentCreativeContext,
  type AIModelPreset,
  type AttachmentCreativeContext,
  type ThemePreset,
  type VisualPreset,
} from '../lib/creativePresetApi'

const panel = 'rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50'
const terminalGroupStatuses = new Set(['succeeded', 'partially_succeeded', 'failed', 'cancelled'])
const statusLabels: Record<string, string> = {
  analyzing: '分析中', editing: '编辑中', confirmed: '已确认', generating: '生成中', generated: '已生成',
  queued: '排队中', running: '生成中', succeeded: '已完成', partially_succeeded: '部分完成',
  failed: '失败', cancelled: '已中止',
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

function productTitle(session: Pick<ListingWorkflowSession, 'listing_content' | 'structured_attributes'>) {
  const title = session.listing_content?.title
  const attributes = session.structured_attributes || {}
  return title?.zh || title?.en || String(attributes.product_name || attributes.name || '未命名商品')
}

function summaryTitle(session: ListingWorkflowSessionSummary) {
  return session.listing_title_zh || session.listing_title_en || '未命名商品'
}

function SessionHub() {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<ListingWorkflowSessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void listListingWorkflowSessions(100)
      .then((items) => { if (active) setSessions(items) })
      .catch((reason) => { if (active) setError(errorText(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const readySessions = sessions.filter(isAttachmentSessionReady)
  const selected = readySessions.find((item) => item.id === selectedSessionId)
  return <div className="space-y-5 pb-12 pt-6">
    <header className="overflow-hidden rounded-2xl bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-600 p-6 text-white shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-100">Listing Visual Production</div>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="text-2xl font-bold">附图生成工作台</h1><p className="mt-2 max-w-3xl text-sm text-blue-50">选择已确认的商品，通过公司视觉模板、主题和AI模特完成整套附图策划与生成。</p></div>
        <Link className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-blue-700 shadow-sm" to="/workspaces/listing/quick">快速创建商品</Link>
      </div>
    </header>

    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">当前商品</h2><p className="mt-1 text-xs text-gray-500">商品选择已经内嵌到工作台。选择后会恢复该商品现有 Project 和工作状态，不会重复创建。</p></div><Link className={button} to="/workspaces/listing">查看全部商品</Link></div>
      {loading && <div className="mt-5 rounded-xl bg-gray-50 p-5 text-center text-sm text-gray-500 dark:bg-white/[0.03]">正在读取可用商品…</div>}
      {!loading && readySessions.length > 0 && <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <select aria-label="选择商品" value={selectedSessionId} onChange={(event) => setSelectedSessionId(event.target.value)} className="min-h-11 w-full rounded-xl border border-gray-200 bg-white px-3 text-sm text-gray-800 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-100">
          <option value="">请选择一个已确认商品</option>
          {readySessions.map((item) => <option key={item.id} value={item.id}>{summaryTitle(item)} · {item.category_name} · Listing V{item.listing_version_number}</option>)}
        </select>
        <button type="button" className={primary} disabled={!selectedSessionId} onClick={() => navigate(`/attachment-image-workbench/${selectedSessionId}`)}>打开工作台</button>
      </div>}
      {!loading && selected && <div className="mt-4 rounded-2xl border border-blue-100 bg-blue-50/50 p-4 dark:border-blue-400/10 dark:bg-blue-500/5">
        <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="text-sm font-semibold text-gray-950 dark:text-white">{summaryTitle(selected)}</div><div className="mt-1 text-xs text-gray-500">{selected.category_name} · {selected.skill_name} V{selected.skill_version_number || '-'}</div></div><span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-blue-700">{selected.source_asset_ids.length} 张产品图</span></div>
      </div>}
      {!loading && readySessions.length > 0 && !selected && <div className="mt-5 rounded-xl border border-dashed border-gray-200 p-8 text-center dark:border-white/[0.08]"><div className="text-sm font-semibold text-gray-800 dark:text-gray-100">请选择一个已确认商品开始附图制作</div><p className="mt-2 text-xs text-gray-500">选择后会直接进入真正的操作页面，并恢复已有策划、参考图、任务和结果。</p></div>}
      {!loading && !readySessions.length && <div className="mt-5 rounded-xl border border-dashed border-gray-200 p-8 text-center dark:border-white/[0.08]"><div className="text-sm font-semibold text-gray-800 dark:text-gray-100">还没有可用的已确认商品</div><p className="mt-2 text-xs text-gray-500">先使用快速创建完成商品分析和 Listing，再回到这里制作附图。</p><Link className={`${primary} mt-4 inline-block`} to="/workspaces/listing/quick">快速创建商品</Link></div>}
    </section>
  </div>
}

function WorkbenchDetail({ sessionId }: { sessionId: string }) {
  const showToast = useStore((state) => state.showToast)
  const projectRef = useRef<CategoryOutputProject | null>(null)
  const draftRef = useRef<AttachmentWorkbenchDraft | null>(null)
  const hydrated = useRef(false)
  const lastSavedSignature = useRef('')
  const saveQueue = useRef<Promise<void>>(Promise.resolve())
  const [session, setSession] = useState<ListingWorkflowSession | null>(null)
  const [project, setProject] = useState<CategoryOutputProject | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [groups, setGroups] = useState<ListingImageTaskGroup[]>([])
  const [draft, setDraft] = useState<AttachmentWorkbenchDraft>(() => normalizeAttachmentWorkbenchDraft(null))
  const [expanded, setExpanded] = useState<Set<AttachmentModuleCode>>(new Set(['pure_white']))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'dirty' | 'saving' | 'saved' | 'failed'>('idle')
  const [pollingPaused, setPollingPaused] = useState(false)
  const [planning, setPlanning] = useState<AttachmentPlanningState | null>(null)
  const [referenceState, setReferenceState] = useState<AttachmentReferenceState | null>(null)
  const [productCompositions, setProductCompositions] = useState<AttachmentProductComposition[]>([])
  const [productIdentityLock, setProductIdentityLock] = useState<AttachmentProductIdentityLock | null>(null)
  const [productIdentityBusy, setProductIdentityBusy] = useState(false)
  const [productCandidates, setProductCandidates] = useState<ListingWorkflowSessionSummary[]>([])
  const [productCandidateAssets, setProductCandidateAssets] = useState<Record<string, Asset>>({})
  const [referenceBusy, setReferenceBusy] = useState('')
  const [productPreprocessOpen, setProductPreprocessOpen] = useState(false)
  const [productPreprocessSaving, setProductPreprocessSaving] = useState(false)
  const [planningBusy, setPlanningBusy] = useState('')
  const [creativeContext, setCreativeContext] = useState<AttachmentCreativeContext | null>(null)
  const [visualPresets, setVisualPresets] = useState<VisualPreset[]>([])
  const [themePresets, setThemePresets] = useState<ThemePreset[]>([])
  const [modelPresets, setModelPresets] = useState<AIModelPreset[]>([])
  const [creativeContextBusy, setCreativeContextBusy] = useState(false)
  const [visualDirection, setVisualDirection] = useState('')
  const [visualDirty, setVisualDirty] = useState(false)
  const [suiteVersions, setSuiteVersions] = useState<AttachmentPlanVersion[]>([])
  const [suiteHistoryOpen, setSuiteHistoryOpen] = useState(false)
  const [generationPreview, setGenerationPreview] = useState<AttachmentGenerationPreview | null>(null)
  const [generationSelection, setGenerationSelection] = useState<AttachmentModuleCode[]>([])
  const [generationBusy, setGenerationBusy] = useState('')
  const [generationCreativePlanningJobId, setGenerationCreativePlanningJobId] = useState<string | null>(null)
  const [resultState, setResultState] = useState<AttachmentResultState | null>(null)
  const [materialSaveContext, setMaterialSaveContext] = useState<AttachmentMaterialSaveContext | null>(null)
  const [materialSaveOutputId, setMaterialSaveOutputId] = useState<string | null>(null)
  const [materialSaveOpen, setMaterialSaveOpen] = useState(false)
  const [materialSaving, setMaterialSaving] = useState(false)
  const generationIdempotencyRef = useRef('')
  const visualDirtyRef = useRef(false)
  const suitePlanningAwaitingResultRef = useRef(false)

  const refreshGroups = async (projectId: string) => {
    const [response, results] = await Promise.all([
      listListingImageTaskGroups(projectId), getAttachmentResultState(projectId),
    ])
    setGroups(response.items); setResultState(results)
  }

  useEffect(() => {
    let active = true
    hydrated.current = false
    setLoading(true); setError('')
    void (async () => {
      try {
        const [sessionValue, options] = await Promise.all([
          getListingWorkflowSession(sessionId),
          getListingOutputOptions(sessionId),
        ])
        if (!options.listing_confirmed || !options.listing_version_id || !sessionValue.confirmed_at) {
          throw new Error('该商品尚未确认 Listing，暂时不能进入附图生成工作台。')
        }
        const projectValue = options.listing_image_project.project_id
          ? await getCategoryOutputProject('listing-image', options.listing_image_project.project_id)
          : await createCategoryOutputProject('listing-image', sessionId)
        const backendModules = projectValue.modules.filter((item) => typeof item.code === 'string')
        const availableCodes = backendModules.filter((item) => item.available !== false).map((item) => String(item.code))
        const stored = projectValue.prompt_config?.[ATTACHMENT_WORKBENCH_CONFIG_KEY]
        let nextDraft = normalizeAttachmentWorkbenchDraft(stored, availableCodes)
        const storedDraftSignature = JSON.stringify(nextDraft)
        const [loadedAssets, taskGroups, planningValue, referenceValue, resultsValue, compositionValue, sessionCandidates, creativeValue, visualsValue, themesValue, modelsValue, productIdentityValue] = await Promise.all([
          Promise.all(projectValue.source_asset_ids.map((id) => getAsset(id).catch(() => null))),
          listListingImageTaskGroups(projectValue.id),
          getAttachmentPlanning(projectValue.id),
          getAttachmentReferences(projectValue.id),
          getAttachmentResultState(projectValue.id),
          getAttachmentProductCompositions(projectValue.id),
          listListingWorkflowSessions(100),
          getAttachmentCreativeContext(projectValue.id),
          listVisualPresets(),
          listThemePresets(),
          listAIModelPresets(),
          getAttachmentProductIdentityLock(projectValue.id).catch(() => null),
        ])
        const candidateAssetRows = await Promise.all(sessionCandidates
          .filter((item) => item.primary_asset_id)
          .map((item) => getAsset(item.primary_asset_id!).catch(() => null)))
        if (!active) return
        nextDraft = {
          ...nextDraft,
          modules: Object.fromEntries(attachmentModuleDefinitions.map((definition) => {
            const supportsCreative = planningValue.modules.find((item) => item.module_key === definition.code)?.supports_creative
            const moduleDraft = nextDraft.modules[definition.code]
            return [definition.code, supportsCreative ? moduleDraft : { ...moduleDraft, generationMode: 'standard' }]
          })) as AttachmentWorkbenchDraft['modules'],
        }
        setSession(sessionValue); setProject(projectValue); projectRef.current = projectValue
        setAssets(loadedAssets.filter((item): item is Asset => Boolean(item)))
        setGroups(taskGroups.items); setDraft(nextDraft); draftRef.current = nextDraft
        setPlanning(planningValue); setVisualDirection(planningValue.visual_direction_cn)
        setCreativeContext(creativeValue); setVisualPresets(visualsValue); setThemePresets(themesValue); setModelPresets(modelsValue)
        setReferenceState(referenceValue)
        setProductCompositions(compositionValue)
        setProductIdentityLock(productIdentityValue)
        setProductCandidates(sessionCandidates.filter(isAttachmentSessionReady))
        setProductCandidateAssets(Object.fromEntries(candidateAssetRows.filter((item): item is Asset => Boolean(item)).map((item) => [item.id, item])))
        setResultState(resultsValue)
        setVisualDirty(false); visualDirtyRef.current = false
        lastSavedSignature.current = storedDraftSignature
        setSaveStatus(storedDraftSignature === JSON.stringify(nextDraft) ? 'saved' : 'dirty'); hydrated.current = true
      } catch (reason) {
        if (active) setError(errorText(reason))
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false; hydrated.current = false }
  }, [sessionId])

  const applyPlanning = (value: AttachmentPlanningState) => {
    setPlanning(value)
    if (!visualDirtyRef.current) setVisualDirection(value.visual_direction_cn)
  }

  const refreshPlanning = async () => {
    if (!projectRef.current) return null
    const value = await getAttachmentPlanning(projectRef.current.id)
    applyPlanning(value)
    return value
  }

  const changeCreativeContext = async (input: {
    visualPresetId: string
    themePresetId: string | null
    modelSelectionMode: 'recommended' | 'selected' | 'none'
    modelIdentityIds: string[]
  }) => {
    if (!project || !creativeContext) return
    setCreativeContextBusy(true)
    try {
      const value = await updateAttachmentCreativeContext(project.id, {
        visual_preset_id: input.visualPresetId,
        theme_preset_id: input.themePresetId,
        model_selection_mode: input.modelSelectionMode,
        selected_model_identity_version_ids: input.modelIdentityIds,
        expected_creative_context_version: creativeContext.creative_context_version,
      })
      setCreativeContext(value)
      const nextPlanning = await getAttachmentPlanning(project.id)
      applyPlanning(nextPlanning)
      showToast('创意设置已更新。已有图片和历史版本不会变化，当前方案需要重新策划后再生成。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      const latest = await getAttachmentCreativeContext(project.id).catch(() => null)
      if (latest) setCreativeContext(latest)
    } finally {
      setCreativeContextBusy(false)
    }
  }

  const saveDraft = (force = false) => {
    const nextDraft = draftRef.current
    if (!nextDraft) return saveQueue.current
    const requestedSignature = JSON.stringify(nextDraft)
    if (!force && requestedSignature === lastSavedSignature.current) return saveQueue.current
    setSaveStatus('saving')
    saveQueue.current = saveQueue.current.catch(() => undefined).then(async () => {
      const currentProject = projectRef.current
      const currentDraft = draftRef.current
      if (!currentProject || !currentDraft) return
      const value = await updateCategoryOutputProject('listing-image', currentProject.id, {
        prompt_config: {
          ...currentProject.prompt_config,
          [ATTACHMENT_WORKBENCH_CONFIG_KEY]: currentDraft,
        },
        expected_state_version: currentProject.state_version,
      })
      projectRef.current = value; setProject(value)
      lastSavedSignature.current = JSON.stringify(currentDraft)
      setSaveStatus(JSON.stringify(draftRef.current) === lastSavedSignature.current ? 'saved' : 'dirty')
    }).catch((reason) => {
      setSaveStatus('failed'); setError(errorText(reason))
    })
    return saveQueue.current
  }

  useEffect(() => {
    draftRef.current = draft
    if (!hydrated.current || JSON.stringify(draft) === lastSavedSignature.current) return
    setSaveStatus('dirty')
    const timer = window.setTimeout(() => { void saveDraft() }, 900)
    return () => window.clearTimeout(timer)
  }, [draft])

  const attachmentGroups = useMemo(() => groups.filter((group) => group.workflow_mode === 'attachment_standard'), [groups])
  const taskSummary = useMemo(() => summarizeAttachmentTaskGroups(attachmentGroups), [attachmentGroups])
  useEffect(() => {
    if (!project || taskSummary.activeGroups === 0 || pollingPaused) return
    let active = true
    let timer = 0
    const startedAt = Date.now()
    const poll = async () => {
      if (!active) return
      if (Date.now() - startedAt > 30 * 60 * 1000) { setPollingPaused(true); return }
      try { await refreshGroups(project.id) } catch { /* keep the last durable status */ }
      if (active) timer = window.setTimeout(poll, 3000)
    }
    timer = window.setTimeout(poll, 3000)
    return () => { active = false; window.clearTimeout(timer) }
  }, [project?.id, taskSummary.activeGroups, pollingPaused])

  const planningActive = planning?.planning_status === 'planning'
    || planning?.modules.some((item) => item.status === 'planning')
  useEffect(() => {
    if (!project || !planningActive) return
    let active = true
    const timer = window.setInterval(() => {
      if (!active) return
      void getAttachmentPlanning(project.id).then((value) => {
        if (!active) return
        if (suitePlanningAwaitingResultRef.current && value.planning_status !== 'planning') {
          suitePlanningAwaitingResultRef.current = false
          if (value.planning_status === 'ready') {
            visualDirtyRef.current = false
            setVisualDirty(false)
          }
        }
        applyPlanning(value)
      }).catch(() => undefined)
    }, 1600)
    return () => { active = false; window.clearInterval(timer) }
  }, [project?.id, planningActive])

  const referenceAnalysisActive = referenceState?.modules.some((item) => Boolean(item.reference_analysis_job_id))
  useEffect(() => {
    if (!project || !referenceAnalysisActive) return
    let active = true
    const timer = window.setInterval(() => {
      void getAttachmentReferences(project.id).then((value) => { if (active) setReferenceState(value) }).catch(() => undefined)
    }, 1600)
    return () => { active = false; window.clearInterval(timer) }
  }, [project?.id, referenceAnalysisActive])

  useEffect(() => {
    if (!project || productIdentityLock?.status !== 'analyzing') return
    let active = true
    const timer = window.setInterval(() => {
      void getAttachmentProductIdentityLock(project.id).then((value) => { if (active) setProductIdentityLock(value) }).catch(() => undefined)
    }, 1600)
    return () => { active = false; window.clearInterval(timer) }
  }, [project?.id, productIdentityLock?.status])

  const moduleBackend = useMemo(() => Object.fromEntries((project?.modules || []).map((item) => [String(item.code || ''), item])), [project?.modules])
  const selectedModules = selectedAttachmentModules(draft)
  const requestedImages = countRequestedAttachmentImages(draft)
  const attachmentModuleCodes = new Set<string>(attachmentModuleDefinitions.map((definition) => definition.code))
  const resultModuleCount = resultState?.modules.filter((item) => item.visible_output_count > 0).length
    ?? new Set(groups.flatMap((group) => group.tasks
      .filter((task) => task.outputs.length && attachmentModuleCodes.has(task.image_type))
      .map((task) => task.image_type))).size
  const phaseOneSupported = session?.category_code === 'football_jersey'

  const updateModule = (code: AttachmentModuleCode, next: AttachmentWorkbenchDraft['modules'][AttachmentModuleCode]) => {
    setDraft((current) => ({ ...current, modules: { ...current.modules, [code]: next } }))
  }

  const selectAvailable = (selected: boolean) => {
    setDraft((current) => ({
      ...current,
      modules: Object.fromEntries(attachmentModuleDefinitions.map((definition) => [definition.code, {
        ...current.modules[definition.code],
        selected: selected && phaseOneSupported && moduleBackend[definition.code]?.available !== false,
      }])) as AttachmentWorkbenchDraft['modules'],
    }))
  }

  const openMaterialSave = async (outputId: string | null = null) => {
    if (!project) return
    try {
      const context = await getAttachmentMaterialSaveContext(project.id)
      const existing = !outputId && context.existing_material_set_id
        ? await getAttachmentMaterialSet(context.existing_material_set_id)
        : null
      setMaterialSaveContext(outputId ? {
        ...context,
        default_name: `${context.default_name}_单张`,
        existing_material_set_id: null,
        existing_display_name: null,
      } : {
        ...context,
        suggested_tags: existing?.tags || context.suggested_tags,
        existing_note: existing?.note || '',
      })
      setMaterialSaveOutputId(outputId)
      setMaterialSaveOpen(true)
    } catch (reason) { showToast(errorText(reason), 'error') }
  }

  const submitMaterialSave = async (input: AttachmentMaterialSaveInput) => {
    if (!project) return
    setMaterialSaving(true)
    try {
      const result = materialSaveOutputId
        ? await saveAttachmentMaterialOutput(project.id, materialSaveOutputId, input)
        : await saveAttachmentMaterialSet(project.id, input)
      setMaterialSaveOpen(false)
      showToast(result.unchanged
        ? `素材套装内容没有变化，继续保留 V${result.material_set.current_version_number}。`
        : `已保存到个人素材库 · V${result.material_set.current_version_number}。`, 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setMaterialSaving(false) }
  }

  const prepareGeneration = async (moduleKeys: AttachmentModuleCode[]) => {
    if (!project || !moduleKeys.length) return
    setGenerationBusy(moduleKeys.length === 1 ? moduleKeys[0] : 'all')
    try {
      await saveDraft(true)
      if (JSON.stringify(draftRef.current) !== lastSavedSignature.current) {
        throw new Error('工作台设置保存失败，请先保存成功后再生成。')
      }
      const creativeKeys = moduleKeys.filter((key) => draftRef.current?.modules[key].generationMode === 'creative')
      let creativePlanningJobId: string | undefined
      if (creativeKeys.length) {
        const started = await startAttachmentCreativePlanning(
          project.id, creativeKeys, `attachment-creative:${randomUuid()}`,
        )
        creativePlanningJobId = started.planning_job_id
        showToast(`正在一次策划 ${creativeKeys.length} 个模块的创意方向，完成后会打开确认窗口。`, 'success')
        let result = started
        for (let attempt = 0; attempt < 240 && result.status !== 'ready'; attempt += 1) {
          if (['failed', 'cancelled', 'stale'].includes(result.status)) {
            throw new Error(result.error_message || '创意方向策划失败，请重试。')
          }
          await new Promise((resolve) => window.setTimeout(resolve, 1500))
          result = await getAttachmentCreativePlanning(project.id, creativePlanningJobId)
        }
        if (result.status !== 'ready') throw new Error('创意方向策划等待超时，请稍后重试。')
      }
      const preview = await previewAttachmentGeneration(project.id, moduleKeys, creativePlanningJobId)
      generationIdempotencyRef.current = `attachment-generate:${randomUuid()}`
      setGenerationCreativePlanningJobId(creativePlanningJobId || null)
      setGenerationSelection(moduleKeys)
      setGenerationPreview(preview)
    } catch (reason) {
      showToast(errorText(reason), 'error')
    } finally {
      setGenerationBusy('')
    }
  }

  const confirmGeneration = async () => {
    if (!project || !generationPreview || !generationSelection.length) return
    setGenerationBusy('submit')
    try {
      const result = await generateAttachments(project.id, {
        selected_module_keys: generationSelection,
        snapshot_signature: generationPreview.snapshot_signature,
        idempotency_key: generationIdempotencyRef.current,
        creative_planning_job_id: generationCreativePlanningJobId || undefined,
      })
      setGenerationPreview(null)
      setGenerationCreativePlanningJobId(null)
      setPollingPaused(false)
      await refreshGroups(project.id)
      showToast(`任务组 #${result.group_number} 已提交，共 ${result.total_images} 张。`, 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
    } finally {
      setGenerationBusy('')
    }
  }

  const cancelGroup = async (groupId: string) => {
    if (!project) return
    setGenerationBusy(`cancel:${groupId}`)
    try {
      await cancelListingImageTaskGroup(groupId)
      await refreshGroups(project.id)
      showToast('已提交中止请求；正在调用上游的任务会在返回后丢弃结果。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setGenerationBusy('') }
  }

  const retryGroup = async (groupId: string) => {
    if (!project) return
    setGenerationBusy(`retry:${groupId}`)
    try {
      await retryFailedListingImageTaskGroup(groupId, `attachment-retry:${randomUuid()}`)
      setPollingPaused(false)
      await refreshGroups(project.id)
      showToast('失败任务已创建新的重试任务组。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setGenerationBusy('') }
  }

  const approveResult = async (entry: AttachmentResultEntry, makeFinal: boolean) => {
    if (!project) return
    setGenerationBusy(`review:${entry.output.id}`)
    try {
      if (makeFinal) await setAttachmentFinal(project.id, entry.output.id)
      else await reviewAttachmentOutput(project.id, entry.output.id, {
        status: 'approved', expected_review_state_version: entry.output.review_state_version || 0,
      })
      await refreshGroups(project.id)
      showToast(makeFinal ? '已审核通过，并设为当前最终采用版本。' : '已审核通过；当前最终采用版本保持不变。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); await refreshGroups(project.id).catch(() => undefined) } finally { setGenerationBusy('') }
  }

  const rejectResult = async (entry: AttachmentResultEntry, clearFinal: boolean) => {
    if (!project) return
    setGenerationBusy(`review:${entry.output.id}`)
    try {
      await reviewAttachmentOutput(project.id, entry.output.id, {
        status: 'rejected', expected_review_state_version: entry.output.review_state_version || 0,
        clear_final_if_rejected: clearFinal,
      })
      await refreshGroups(project.id)
      showToast(clearFinal ? '图片已打回，最终采用状态也已清除。' : '图片已打回。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); await refreshGroups(project.id).catch(() => undefined) } finally { setGenerationBusy('') }
  }

  const retryTask = async (task: ListingImageTask) => {
    if (!project) return
    setGenerationBusy(`retry-job:${task.id}`)
    try {
      await retryAttachmentJob(project.id, task.id, `attachment-slot-retry:${randomUuid()}`)
      setPollingPaused(false); await refreshGroups(project.id)
      showToast(`候选 ${task.slot_index || '-'} 已按原任务快照单独重试。`, 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setGenerationBusy('') }
  }

  const adoptCreativeDirection = async (entry: AttachmentResultEntry, expectedStateVersion: number) => {
    if (!project) return
    setGenerationBusy(`adopt:${entry.output.id}`)
    try {
      const nextPlanning = await adoptAttachmentCreativeDirection(
        project.id, entry.output.id, expectedStateVersion,
      )
      applyPlanning(nextPlanning)
      const refreshedProject = await getCategoryOutputProject('listing-image', project.id)
      const availableCodes = refreshedProject.modules
        .filter((item) => item.available !== false)
        .map((item) => String(item.code || ''))
      const nextDraft = normalizeAttachmentWorkbenchDraft(
        refreshedProject.prompt_config?.[ATTACHMENT_WORKBENCH_CONFIG_KEY], availableCodes,
      )
      projectRef.current = refreshedProject
      setProject(refreshedProject)
      draftRef.current = nextDraft
      setDraft(nextDraft)
      lastSavedSignature.current = JSON.stringify(nextDraft)
      setSaveStatus('saved')
      setExpanded((current) => new Set(current).add(entry.task.image_type as AttachmentModuleCode))
      showToast('这个创意方向已复制为新的标准方案。你可以先微调方案或Prompt，再生成候选图。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      await refreshPlanning().catch(() => undefined)
    } finally {
      setGenerationBusy('')
    }
  }

  const clearResults = async (moduleKeys: AttachmentModuleCode[]) => {
    if (!project || !moduleKeys.length) return
    if (!window.confirm(`确认清空 ${moduleKeys.length} 个模块的当前结果吗？历史输出、任务、Asset 和对象存储文件都会保留。`)) return
    setGenerationBusy('clear-results')
    try {
      const next = await discardAttachmentResults(project.id, moduleKeys)
      setResultState(next); await refreshGroups(project.id)
      showToast('当前结果区域已清空，历史数据仍可追溯。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setGenerationBusy('') }
  }

  const resetModuleState = async (moduleKey: AttachmentModuleCode) => {
    if (!project) return
    if (!window.confirm('重置会清空该模块当前结果、方案、Prompt、模块参考素材和生成参数，但不会删除历史任务与图片。确认继续吗？')) return
    setGenerationBusy(`reset:${moduleKey}`)
    try {
      const nextPlanning = await resetAttachmentModule(project.id, moduleKey)
      applyPlanning(nextPlanning)
      const definition = attachmentModuleDefinitions.find((item) => item.code === moduleKey)!
      updateModule(moduleKey, { selected: draft.modules[moduleKey].selected, aspectRatio: definition.defaultAspectRatio, imageCount: 1, generationMode: 'standard' })
      setReferenceState(await getAttachmentReferences(project.id))
      await refreshGroups(project.id)
      showToast('模块已恢复初始状态；历史版本和生成结果仍然保留。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error') } finally { setGenerationBusy('') }
  }

  const saveVisualDirection = async () => {
    if (!project || !planning) return
    setPlanningBusy('visual-save')
    const base = planning
    try {
      let value: AttachmentPlanningState
      try {
        value = await updateAttachmentVisualDirection(project.id, {
          visual_direction_cn: visualDirection,
          expected_state_version: base.state_version,
        })
      } catch (reason) {
        if (!(reason instanceof AuthApiError) || reason.status !== 409) throw reason
        const latest = await getAttachmentPlanning(project.id)
        if (latest.visual_direction_cn !== base.visual_direction_cn && latest.visual_direction_cn !== visualDirection) {
          applyPlanning(latest)
          throw new Error('其他页面也修改了整套视觉方向。最新版本已读取，你当前输入仍保留在编辑框中，请确认后再次保存。')
        }
        value = await updateAttachmentVisualDirection(project.id, {
          visual_direction_cn: visualDirection,
          expected_state_version: latest.state_version,
        })
      }
      visualDirtyRef.current = false; setVisualDirty(false); applyPlanning(value)
      showToast('整套视觉方向已保存，并创建了新版本。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
    } finally {
      setPlanningBusy('')
    }
  }

  const saveModulePlanning = async (moduleKey: AttachmentModuleCode, input: {
    plan_summary_cn: string; prompt_cn: string; operator_requirement_cn: string
    aspect_ratio: string; expected_state_version: number
  }) => {
    if (!project || !planning) return
    const base = planning.modules.find((item) => item.module_key === moduleKey)
    if (!base) return
    setPlanningBusy(`save:${moduleKey}`)
    try {
      let value: AttachmentPlanningState
      try {
        value = await updateAttachmentModule(project.id, moduleKey, input)
      } catch (reason) {
        if (!(reason instanceof AuthApiError) || reason.status !== 409) throw reason
        const latest = await getAttachmentPlanning(project.id)
        const remote = latest.modules.find((item) => item.module_key === moduleKey)
        if (!remote) throw reason
        const fields = ['plan_summary_cn', 'prompt_cn', 'operator_requirement_cn', 'aspect_ratio'] as const
        const overlap = fields.some((field) => input[field] !== base[field]
          && remote[field] !== base[field] && remote[field] !== input[field])
        if (overlap) {
          applyPlanning(latest)
          throw new Error('该模块的同一字段已被其他页面修改。最新版本已读取，你当前输入仍保留，请确认差异后再次保存。')
        }
        value = await updateAttachmentModule(project.id, moduleKey, {
          plan_summary_cn: input.plan_summary_cn !== base.plan_summary_cn ? input.plan_summary_cn : remote.plan_summary_cn,
          prompt_cn: input.prompt_cn !== base.prompt_cn ? input.prompt_cn : remote.prompt_cn,
          operator_requirement_cn: input.operator_requirement_cn !== base.operator_requirement_cn ? input.operator_requirement_cn : remote.operator_requirement_cn,
          aspect_ratio: input.aspect_ratio !== base.aspect_ratio ? input.aspect_ratio : remote.aspect_ratio,
          expected_state_version: remote.state_version,
        })
      }
      applyPlanning(value)
      showToast(`${base.module_name}已保存，并创建了新版本。`, 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      throw reason
    } finally {
      setPlanningBusy('')
    }
  }

  const runSuitePlanning = async () => {
    if (!project || !planning || !selectedModules.length) return
    setPlanningBusy('suite')
    try {
      const selectedKeys = selectedModules.map((definition) => definition.code)
      let references = await getAttachmentReferences(project.id)
      let identity = await getAttachmentProductIdentityLock(project.id)
      setReferenceState(references); setProductIdentityLock(identity)
      for (const key of selectedKeys) {
        const state = references.modules.find((item) => item.module_key === key)
        if (state && !state.reference_analysis_job_id && (state.reference_context_dirty || state.understanding?.status !== 'ready')) {
          references = await analyzeAttachmentReferences(project.id, key, `attachment-reference:auto-plan:${key}:${randomUuid()}`)
          setReferenceState(references)
        }
      }
      const deadline = Date.now() + 120_000
      while ((identity.status !== 'ready' || selectedKeys.some((key) => references.modules.find((item) => item.module_key === key)?.understanding?.status !== 'ready')) && Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 1600))
        ;[references, identity] = await Promise.all([getAttachmentReferences(project.id), getAttachmentProductIdentityLock(project.id)])
        setReferenceState(references); setProductIdentityLock(identity)
        const failed = references.modules.find((item) => selectedKeys.includes(item.module_key) && item.understanding?.status === 'failed')
        if (identity.status === 'failed') throw new Error(identity.error_message || '商品事实提取失败，请重新提取')
        if (failed) throw new Error(failed.understanding?.error_message || `${failed.module_key}参考素材分析失败`)
      }
      if (identity.status !== 'ready' || selectedKeys.some((key) => references.modules.find((item) => item.module_key === key)?.understanding?.status !== 'ready')) {
        throw new Error('商品事实或参考素材仍在分析中，请稍后重试')
      }
      const indexed = Object.fromEntries(planning.modules.map((item) => [item.module_key, item]))
      const value = await planAttachmentSuite(project.id, {
        modules: selectedModules.map((definition) => ({
          module_key: definition.code,
          aspect_ratio: draft.modules[definition.code].aspectRatio,
          operator_requirement_cn: indexed[definition.code]?.operator_requirement_cn || '',
        })),
        visual_direction_cn: visualDirection,
        idempotency_key: `attachment-suite:${randomUuid()}`,
      })
      // The submit response still contains the previously persisted visual direction.
      // Keep the user's submitted draft visible until the asynchronous AI result lands.
      suitePlanningAwaitingResultRef.current = true
      visualDirtyRef.current = true
      setVisualDirty(true)
      setPlanning(value)
      showToast('AI整套策划已提交，完成后会自动显示各模块方案与Prompt。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
    } finally {
      setPlanningBusy('')
    }
  }

  const runModulePlanning = async (moduleKey: AttachmentModuleCode, operatorRequirement: string, optimize: boolean) => {
    if (!project) return
    setPlanningBusy(`${optimize ? 'optimize' : 'replan'}:${moduleKey}`)
    try {
      let references = await getAttachmentReferences(project.id)
      let identity = await getAttachmentProductIdentityLock(project.id)
      let moduleReferences = references.modules.find((item) => item.module_key === moduleKey)
      if (moduleReferences && !moduleReferences.reference_analysis_job_id && (moduleReferences.reference_context_dirty || moduleReferences.understanding?.status !== 'ready')) {
        references = await analyzeAttachmentReferences(project.id, moduleKey, `attachment-reference:auto-plan:${moduleKey}:${randomUuid()}`)
        setReferenceState(references)
      }
      const deadline = Date.now() + 120_000
      moduleReferences = references.modules.find((item) => item.module_key === moduleKey)
      while ((identity.status !== 'ready' || moduleReferences?.understanding?.status !== 'ready') && Date.now() < deadline) {
        await new Promise((resolve) => window.setTimeout(resolve, 1600))
        ;[references, identity] = await Promise.all([getAttachmentReferences(project.id), getAttachmentProductIdentityLock(project.id)])
        moduleReferences = references.modules.find((item) => item.module_key === moduleKey)
        setReferenceState(references); setProductIdentityLock(identity)
        if (identity.status === 'failed') throw new Error(identity.error_message || '商品事实提取失败，请重新提取')
        if (moduleReferences?.understanding?.status === 'failed') throw new Error(moduleReferences.understanding.error_message || '参考素材分析失败')
      }
      if (identity.status !== 'ready' || moduleReferences?.understanding?.status !== 'ready') throw new Error('商品事实或参考素材仍在分析中，请稍后重试')
      const input = {
        aspect_ratio: draft.modules[moduleKey].aspectRatio,
        operator_requirement_cn: operatorRequirement,
        idempotency_key: `attachment-${optimize ? 'optimize' : 'replan'}:${moduleKey}:${randomUuid()}`,
      }
      const value = optimize
        ? await optimizeAttachmentModulePrompt(project.id, moduleKey, input)
        : await replanAttachmentModule(project.id, moduleKey, input)
      applyPlanning(value)
      showToast(optimize ? 'Prompt优化任务已提交。' : '单模块重新策划已提交。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      throw reason
    } finally {
      setPlanningBusy('')
    }
  }

  const applyProductComposition = async (next: AttachmentProductComposition) => {
    setProductCompositions((current) => current.map((item) => item.module_key === next.module_key ? next : item))
    const [nextPlanning, nextReferences] = await Promise.all([refreshPlanning(), project ? getAttachmentReferences(project.id) : null])
    if (nextReferences && project) {
      const moduleReferences = nextReferences.modules.find((item) => item.module_key === next.module_key)
      if (moduleReferences && !moduleReferences.reference_analysis_job_id && moduleReferences.reference_context_dirty) {
        setReferenceState(await analyzeAttachmentReferences(project.id, next.module_key, `attachment-reference:auto-composition:${next.module_key}:${randomUuid()}`))
      } else setReferenceState(nextReferences)
    }
    return nextPlanning
  }

  const changeProductMode = async (moduleKey: AttachmentModuleCode, mode: 'SINGLE' | 'MULTI') => {
    if (!project) return
    const current = productCompositions.find((item) => item.module_key === moduleKey)
    if (!current) return
    setPlanningBusy(`composition:${moduleKey}`)
    try {
      const next = await updateAttachmentProductMode(project.id, moduleKey, mode, current.state_version)
      await applyProductComposition(next)
      showToast(mode === 'MULTI' ? '已切换为多件商品。请添加商品后重新分析并策划。' : '已切回单件商品；附加商品记录已保留。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); throw reason } finally { setPlanningBusy('') }
  }

  const addSecondaryProduct = async (moduleKey: AttachmentModuleCode, sourceSessionId: string) => {
    if (!project) return
    const current = productCompositions.find((item) => item.module_key === moduleKey)
    if (!current) return
    setPlanningBusy(`composition:${moduleKey}`)
    try {
      const next = await addAttachmentSecondaryProduct(project.id, moduleKey, sourceSessionId, current.state_version)
      await applyProductComposition(next); showToast('附加商品已加入，请重新分析参考素材。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); throw reason } finally { setPlanningBusy('') }
  }

  const replaceSecondaryProduct = async (moduleKey: AttachmentModuleCode, itemId: string, sourceSessionId: string) => {
    if (!project) return
    const current = productCompositions.find((item) => item.module_key === moduleKey)
    if (!current) return
    setPlanningBusy(`composition:${moduleKey}`)
    try {
      const next = await replaceAttachmentSecondaryProduct(project.id, moduleKey, itemId, sourceSessionId, current.state_version)
      await applyProductComposition(next); showToast('附加商品已更换，请重新分析参考素材。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); throw reason } finally { setPlanningBusy('') }
  }

  const removeSecondaryProduct = async (moduleKey: AttachmentModuleCode, itemId: string) => {
    if (!project) return
    const current = productCompositions.find((item) => item.module_key === moduleKey)
    if (!current) return
    setPlanningBusy(`composition:${moduleKey}`)
    try {
      const next = await removeAttachmentSecondaryProduct(project.id, moduleKey, itemId, current.state_version)
      await applyProductComposition(next); showToast('附加商品已移除，历史素材不会被删除。', 'success')
    } catch (reason) { showToast(errorText(reason), 'error'); throw reason } finally { setPlanningBusy('') }
  }

  const addReference = async (moduleKey: AttachmentModuleCode, slot: AttachmentReferenceSlotType, assetId: string, options: { keywords: string[]; guidance: string; libraryItemId?: string }) => {
    if (!project) return
    setReferenceBusy(`add:${moduleKey}:${slot}`)
    try {
      setReferenceState(await addAttachmentReference(project.id, moduleKey, { slot_type: slot, asset_id: assetId, keywords: options.keywords, guidance: options.guidance, library_item_id: options.libraryItemId }))
      showToast('参考素材已添加，后台正在自动理解图片。', 'success')
    } finally {
      setReferenceBusy('')
    }
  }

  const removeReference = async (moduleKey: AttachmentModuleCode, referenceId: string) => {
    if (!project) return
    setReferenceBusy(`remove:${referenceId}`)
    try {
      setReferenceState(await removeAttachmentReference(project.id, moduleKey, referenceId))
      showToast('已从当前模块移除参考素材，原始图片仍保留。', 'success')
    } finally {
      setReferenceBusy('')
    }
  }

  const analyzeReferences = async (moduleKey: AttachmentModuleCode) => {
    if (!project) return
    setReferenceBusy(`analyze:${moduleKey}`)
    try {
      setReferenceState(await analyzeAttachmentReferences(project.id, moduleKey, `attachment-reference:${moduleKey}:${randomUuid()}`))
      showToast('参考素材分析已提交，完成后会自动显示理解摘要。', 'success')
    } finally {
      setReferenceBusy('')
    }
  }

  const productPreprocessGarments = useMemo<BatchTryOnGarment[]>(() => assets.slice(0, 1).map((asset, index) => ({
    id: asset.id,
    batchId: project?.id || '',
    garmentImageId: asset.id,
    serverAssetId: asset.id,
    garmentFileName: asset.filename,
    index,
    selected: true,
    createdAt: Date.now(),
  })), [assets, project?.id])
  const productPreprocessUrls = useMemo(() => Object.fromEntries(assets.flatMap((asset) => asset.url ? [[asset.id, asset.url]] : [])), [assets])

  const saveProductReferences = async (previews: GarmentReferencePreview[]) => {
    if (!project) return
    setProductPreprocessSaving(true)
    try {
      let next = referenceState
      for (const preview of previews) {
        const source = assets.find((asset) => asset.id === preview.garmentId)
        if (!source) continue
        const transformMetadata = { ...garmentTransformMetadata(preview.transform), transform: preview.transform }
        const derived = await uploadGarmentReferenceDataUrl(preview.dataUrl, source.filename, {
          sourceAssetId: source.id,
          garmentView: preview.garmentView,
          transformType: preview.transform.eraseStrokes.length ? 'crop_mask' : preview.transform.mode,
          transformMetadata,
        })
        next = await putAttachmentProductReference(project.id, {
          asset_id: derived.id, source_asset_id: source.id,
          view_role: preview.garmentView, transform_metadata: transformMetadata,
        })
      }
      if (next) setReferenceState(next)
      setProductPreprocessOpen(false)
      showToast('商品正反面参考已保存；原始商品图没有被覆盖。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
    } finally {
      setProductPreprocessSaving(false)
    }
  }

  const saveProductIdentity = async (structured: Record<string, unknown>) => {
    if (!project) return
    setProductIdentityBusy(true)
    try {
      setProductIdentityLock(await updateAttachmentProductIdentityLock(project.id, structured))
      await refreshPlanning()
      showToast('商品事实已保存；依赖这些事实的模块已标记为需要重新策划。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      throw reason
    } finally {
      setProductIdentityBusy(false)
    }
  }

  const reextractProductIdentity = async () => {
    if (!project) return
    setProductIdentityBusy(true)
    try {
      setProductIdentityLock(await reextractAttachmentProductIdentityLock(project.id))
      showToast('商品事实重新提取已提交，完成后会自动刷新。', 'success')
    } catch (reason) {
      showToast(errorText(reason), 'error')
      throw reason
    } finally {
      setProductIdentityBusy(false)
    }
  }

  if (loading) return <div className={`${panel} mt-6`}>正在恢复附图项目与任务状态…</div>
  if (error && (!session || !project)) return <div className="space-y-4 pt-6"><div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div><Link className={button} to="/workspaces/attachment-images">返回商品列表</Link></div>
  if (!session || !project) return null

  return <div className="space-y-5 pb-28 pt-6">
    <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">Attachment Image Workbench</div><h1 className="mt-2 text-2xl font-bold text-gray-950 dark:text-white">附图生成工作台</h1><p className="mt-2 text-sm text-gray-500">{session.category_name} · {session.skill_name} V{session.skill_version_number || '-'} · Listing V{session.listing_version_number}</p></div><div className="flex flex-wrap gap-2"><Link className={button} to="/materials">个人素材库</Link><button className={button} disabled={!resultState?.final_module_count || materialSaving} onClick={() => void openMaterialSave()}>保存整套</button><Link className={button} to="/workspaces/attachment-images">切换商品</Link></div></div>
    </header>

    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}<button className="ml-3 font-semibold underline" onClick={() => setError('')}>关闭</button></div>}
    {!phaseOneSupported && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">首期仅开放橄榄球衣模块。当前商品仍可查看，但不能保存模块生产配置。</div>}

    <section className={panel}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,.65fr)]">
        <div><div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">当前商品</h2><p className="mt-1 text-xs text-gray-500">产品图来自当前 Session，原 Asset 不会被新工作台复制或删除。</p></div><div className="flex gap-2"><button type="button" disabled={!assets.length} onClick={() => setProductPreprocessOpen(true)} className={button}>区分正面 / 背面</button><span className="rounded-full bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700">{session.category_name}</span></div></div>
          <div className="mt-4 flex gap-3 overflow-x-auto pb-1">{(referenceState?.product_references || []).map((item) => <div key={item.id} className="relative w-24 shrink-0 overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-white/[0.08]"><AuthenticatedImage url={item.asset.url} alt={item.asset.filename} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" /><span className="absolute bottom-1.5 left-1.5 rounded-full bg-gray-950/70 px-2 py-0.5 text-[10px] font-semibold text-white">{item.view_role === 'front' ? '正面' : item.view_role === 'back' ? '背面' : '细节'}{item.source === 'override' ? '参考' : ''}</span>{item.asset.id === session.primary_asset_id && <span className="absolute left-1.5 top-1.5 rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold text-white">主图</span>}</div>)}</div>
          {!assets.length && <div className="mt-4 rounded-xl bg-amber-50 p-4 text-xs text-amber-800">产品图片暂时无法读取，请返回商品选择页重新创建或切换商品。</div>}
        </div>
        <div><h2 className="truncate text-lg font-semibold text-gray-950 dark:text-white">{productTitle(session)}</h2><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">产品图</div><div className="mt-1 font-semibold">{assets.length} 张</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">已选模块</div><div className="mt-1 font-semibold">{selectedModules.length} / 6</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">已有结果模块</div><div className="mt-1 font-semibold">{resultModuleCount} 个</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">最终采用</div><div className="mt-1 font-semibold">{resultState?.final_module_count || 0} 个模块</div></div></div><div className="mt-3 text-xs text-gray-400">已审核 {resultState?.reviewed_outputs || 0} / {resultState?.total_outputs || 0} 张；审核通过与最终采用是两个独立状态。</div></div>
      </div>
    </section>

    {creativeContext && <AttachmentCreativeContextPanel
      context={creativeContext}
      visuals={visualPresets}
      themes={themePresets}
      models={modelPresets}
      supportsModel={selectedModules.some((definition) => planning?.modules.find((item) => item.module_key === definition.code)?.supports_model)}
      busy={creativeContextBusy || Boolean(planningActive)}
      onChange={(value) => void changeCreativeContext(value)}
    />}

    <AttachmentProductIdentityPanel
      value={productIdentityLock}
      busy={productIdentityBusy}
      onSave={saveProductIdentity}
      onReextract={reextractProductIdentity}
    />

    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">整套视觉方向</h2><p className="mt-1 text-xs text-gray-500">统一约束当前已选标准模块；AI整套策划一次返回视觉方向、模块方案和中文Prompt。</p></div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-3 py-1 text-xs font-semibold ${planning?.planning_status === 'failed' ? 'bg-red-50 text-red-700' : planning?.planning_status === 'planning' ? 'bg-violet-50 text-violet-700' : 'bg-gray-100 text-gray-600'}`}>{planning?.planning_status === 'planning' ? 'AI策划中' : planning?.visual_direction_version ? `方向 V${planning.visual_direction_version}` : '尚未策划'}</span><button className={button} disabled={!planning} onClick={() => void refreshPlanning()}>刷新策划</button></div></div>
      <textarea disabled={!phaseOneSupported} className="mt-4 min-h-28 w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm leading-6 disabled:bg-gray-100 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" value={visualDirection} placeholder="尚未策划。可以直接填写，也可以点击AI策划生成2～4行统一视觉方向。" onChange={(event) => { setVisualDirection(event.target.value); setVisualDirty(true); visualDirtyRef.current = true }} />
      {planning?.error_message && <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{planning.error_message}</div>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button className={primary} disabled={!phaseOneSupported || !planning || !creativeContext?.visual_preset || planningBusy !== '' || planningActive || creativeContextBusy || !selectedModules.length} onClick={() => void runSuitePlanning()}>{planning?.visual_direction_version ? 'AI重新分析整套' : 'AI策划整套'}</button>
        <button className={button} disabled={!planning || !visualDirty || planningBusy !== ''} onClick={() => void saveVisualDirection()}>保存视觉方向</button>
        <button className={button} disabled={!planning} onClick={() => { const next = !suiteHistoryOpen; setSuiteHistoryOpen(next); if (next && project) void listAttachmentPlanVersions(project.id).then(setSuiteVersions).catch((reason) => showToast(errorText(reason), 'error')) }}>{suiteHistoryOpen ? '收起方向版本' : '查看方向版本'}</button>
        <span className="text-xs text-gray-400">{planning?.visual_direction_source ? `来源：${planning.visual_direction_source}` : ''}</span>
      </div>
      {suiteHistoryOpen && <div className="mt-4 grid gap-2 md:grid-cols-2">{suiteVersions.length ? suiteVersions.map((item) => <details key={item.id} className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><summary className="cursor-pointer text-xs font-semibold text-gray-700 dark:text-gray-200">方向 V{item.version_number} · {item.action} · {new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-gray-500">{item.visual_direction_cn}</p></details>) : <p className="text-xs text-gray-500">暂无历史方向版本。</p>}</div>}
    </section>

    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-semibold text-gray-950 dark:text-white">任务状态</h2><p className="mt-1 text-xs text-gray-500">直接读取现有 Listing 图片 TaskGroup；生成状态与后续审核状态分开。</p></div><div className="flex gap-2"><button className={button} onClick={() => { setPollingPaused(false); void refreshGroups(project.id) }}>刷新状态</button>{pollingPaused && <span className="self-center text-xs text-amber-700">自动刷新已暂停</span>}</div></div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-9">{[
        ['总任务', taskSummary.total], ['运行中', taskSummary.running], ['排队', taskSummary.queued], ['成功', taskSummary.succeeded], ['失败', taskSummary.failed], ['已中止', taskSummary.cancelled], ['已审核', `${resultState?.reviewed_outputs || 0}/${resultState?.total_outputs || 0}`], ['最终采用', resultState?.final_module_count || 0], ['活动批次', taskSummary.activeGroups],
      ].map(([label, value]) => <div key={label} className="rounded-xl bg-gray-50 p-3 text-center dark:bg-white/[0.03]"><div className="text-xs text-gray-500">{label}</div><div className="mt-1 text-lg font-semibold text-gray-950 dark:text-white">{value}</div></div>)}</div>
      {attachmentGroups.length > 0 && <div className="mt-4 space-y-2">{attachmentGroups.slice(0, 5).map((group) => <div key={group.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-100 px-3 py-2.5 text-xs dark:border-white/[0.06]">
        <div><span className="font-semibold text-gray-800 dark:text-gray-100">{group.group_name}</span><span className="ml-2 text-gray-500">{group.tasks.some((task) => task.product_mode === 'MULTI') ? '多商品' : '单商品'} · {group.tasks.some((task) => task.generation_mode === 'creative') ? '创意/混合' : '标准'} · {group.statistics.succeeded + group.statistics.failed + group.statistics.cancelled}/{group.statistics.total} · {statusLabels[group.status] || group.status}</span></div>
        <div className="flex gap-2">
          {!terminalGroupStatuses.has(group.status) && <button className="font-semibold text-red-600 disabled:opacity-50" disabled={generationBusy !== ''} onClick={() => void cancelGroup(group.id)}>中止</button>}
          {(group.statistics.failed > 0 || group.statistics.cancelled > 0) && <button className="font-semibold text-blue-600 disabled:opacity-50" disabled={generationBusy !== ''} onClick={() => void retryGroup(group.id)}>重试失败项</button>}
        </div>
      </div>)}</div>}
    </section>

    <section>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">附图模块</h2><p className="mt-1 text-xs text-gray-500">首期固定六个模块；模块参数独立保存，不为每个模块创建新 Project。</p></div><div className="flex flex-wrap gap-2"><button className={button} disabled={!phaseOneSupported} onClick={() => selectAvailable(true)}>全选可用模块</button><button className={button} disabled={!phaseOneSupported} onClick={() => selectAvailable(false)}>清空选择</button><button className={button} disabled={!selectedModules.length || generationBusy !== ''} onClick={() => void clearResults(selectedModules.map((item) => item.code))}>清空已选模块当前结果</button></div></div>
      <div className="space-y-3">{attachmentModuleDefinitions.map((definition, index) => {
        const backend = moduleBackend[definition.code] || {}
        const latestGroup = [...attachmentGroups]
          .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime())
          .find((group) => group.selected_image_types.includes(definition.code))
        const tasks = (latestGroup?.tasks || []).filter((task) => task.image_type === definition.code)
        const available = phaseOneSupported && backend.available !== false
        const modulePlanning = planning?.modules.find((item) => item.module_key === definition.code)
        return <AttachmentImageModuleCard
          key={definition.code} index={index + 1} definition={definition}
          draft={draft.modules[definition.code]} expanded={expanded.has(definition.code)}
          available={available} unavailableReason={phaseOneSupported ? String(backend.unavailable_reason || '') : '首期仅支持橄榄球衣。'}
          objective={String(backend.objective || '')} projectId={project.id} planning={modulePlanning}
          planningBusy={planningBusy !== '' || planningActive || referenceBusy !== ''}
          referenceState={referenceState?.modules.find((item) => item.module_key === definition.code)}
          productReferences={referenceState?.product_references || []}
          productComposition={productCompositions.find((item) => item.module_key === definition.code)}
          productCandidates={productCandidates} productCandidateAssets={productCandidateAssets}
          modelPresets={modelPresets}
          tasks={tasks} groups={attachmentGroups}
          resultState={resultState?.modules.find((item) => item.module_key === definition.code)}
          onToggleExpanded={() => setExpanded((current) => { const next = new Set(current); next.has(definition.code) ? next.delete(definition.code) : next.add(definition.code); return next })}
          onChange={(next) => updateModule(definition.code, next)}
          onSavePlanning={(input) => saveModulePlanning(definition.code, input)}
          onReplan={(requirement) => runModulePlanning(definition.code, requirement, false)}
          onOptimizePrompt={(requirement) => runModulePlanning(definition.code, requirement, true)}
          onProductModeChange={(mode) => changeProductMode(definition.code, mode)}
          onAddSecondaryProduct={(sourceSessionId) => addSecondaryProduct(definition.code, sourceSessionId)}
          onReplaceSecondaryProduct={(itemId, sourceSessionId) => replaceSecondaryProduct(definition.code, itemId, sourceSessionId)}
          onRemoveSecondaryProduct={(itemId) => removeSecondaryProduct(definition.code, itemId)}
          onAddReference={(slot, assetId, options) => addReference(definition.code, slot, assetId, options)}
          onRemoveReference={(referenceId) => removeReference(definition.code, referenceId)}
          onAnalyzeReferences={() => analyzeReferences(definition.code)} onReferenceError={(message) => showToast(message, 'error')}
          onGenerate={() => prepareGeneration([definition.code])} generationBusy={generationBusy !== ''}
          onApproveResult={approveResult} onRejectResult={rejectResult} onRetryTask={retryTask}
          onClearResults={() => clearResults([definition.code])} onResetModule={() => resetModuleState(definition.code)}
          onAdoptDirection={adoptCreativeDirection}
          onSaveSingle={(entry) => openMaterialSave(entry.output.id)}
        />
      })}</div>
    </section>

    <div className="sticky bottom-20 z-20 border border-gray-200 bg-white/95 px-4 py-3 shadow-[0_-10px_30px_rgba(15,23,42,0.08)] backdrop-blur dark:border-white/[0.08] dark:bg-gray-950/95 lg:bottom-4">
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold text-gray-950 dark:text-white">已选 {selectedModules.length} 个模块 · 计划 {requestedImages} 张图片</div><div className="mt-1 text-xs text-gray-500">{saveStatus === 'saving' ? '正在保存工作台设置…' : saveStatus === 'dirty' ? '有未保存修改' : saveStatus === 'failed' ? '保存失败，请重试' : '工作台设置已保存'} · 已设为最终的 {resultState?.final_module_count || 0} 个模块可随时保存为版本</div></div><div className="flex flex-wrap gap-2"><button className={button} disabled={!resultState?.final_module_count || materialSaving} onClick={() => void openMaterialSave()}>保存整套</button><button className={button} disabled={saveStatus === 'saving' || !phaseOneSupported} onClick={() => void saveDraft(true)}>{saveStatus === 'saving' ? '保存中…' : '立即保存'}</button><button className={primary} disabled={!phaseOneSupported || !selectedModules.length || generationBusy !== '' || saveStatus === 'saving'} onClick={() => void prepareGeneration(selectedModules.map((item) => item.code))}>{generationBusy === 'all' ? '正在核对…' : '生成选中模块'}</button></div></div>
    </div>
    {generationPreview && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="确认正式生成">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900">
        <div className="flex items-start justify-between gap-4"><div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">确认生成附图</h2><p className="mt-1 text-xs leading-5 text-gray-500">这是点击确认时的只读快照。标准模式创建同方向候选；创意模式每个方向绑定自己的方案与Prompt。</p></div><button className="text-xl text-gray-400" disabled={generationBusy === 'submit'} onClick={() => { setGenerationPreview(null); setGenerationCreativePlanningJobId(null) }}>×</button></div>
        <div className="mt-4 space-y-2">{generationPreview.modules.map((item) => <div key={item.module_key} className="rounded-xl border border-gray-200 p-3 text-sm dark:border-white/[0.08]"><div className="grid grid-cols-[1fr_auto] gap-3"><div><div className="flex items-center gap-2 font-semibold text-gray-900 dark:text-white">{item.module_name}<span className={`rounded-full px-2 py-0.5 text-[10px] ${item.generation_mode === 'creative' ? 'bg-violet-50 text-violet-700' : 'bg-blue-50 text-blue-700'}`}>{item.generation_mode === 'creative' ? '创意生成' : '标准生成'}</span><span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">{item.product_mode === 'MULTI' ? '多商品' : '单商品'}</span></div><div className="mt-1 text-xs text-gray-500">参考理解 V{item.reference_understanding_version} · {item.reference_count} 张参考图</div></div><div className="text-right"><div className="font-semibold">{item.image_count} {item.generation_mode === 'creative' ? '个方向 / 张' : '张候选'}</div><div className="mt-1 text-xs text-gray-500">{item.aspect_ratio} · {item.delivery_width}×{item.delivery_height}</div></div></div>{item.product_mode === 'MULTI' && <div className="mt-3 rounded-lg bg-blue-50 p-3 text-xs text-blue-800"><div className="font-semibold">商品模式：多件商品 · 商品 {item.product_count} 件 · 模特 {item.model_count} 人</div><div className="mt-2 flex flex-wrap gap-2">{item.products.map((product, productIndex) => <span key={String(product.product_entry_id || productIndex)} className="rounded-full bg-white px-2 py-1">{product.product_role === 'PRIMARY' ? '主商品' : `附加商品 ${product.display_order}`}：{String(product.display_name || '未命名商品')}</span>)}</div></div>}{item.directions.length > 0 && <div className="mt-3 space-y-2 border-t border-gray-100 pt-3 dark:border-white/[0.06]">{item.directions.map((direction) => <details key={direction.plan_version_id} className="rounded-lg bg-violet-50/60 px-3 py-2 dark:bg-violet-500/5"><summary className="cursor-pointer text-xs font-semibold text-violet-700">创意方向 {direction.direction_index} · {direction.plan_summary_cn}</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-gray-600 dark:text-gray-300">{direction.prompt_cn}</p></details>)}</div>}</div>)}</div>
        <div className="mt-4 rounded-xl bg-blue-50 p-3 text-sm text-blue-800">本次共生成 <strong>{generationPreview.total_images}</strong> 张，使用模型 <strong>{generationPreview.model_code}</strong>。任务提交后离开页面仍会继续执行。</div>
        <div className="mt-5 flex justify-end gap-2"><button className={button} disabled={generationBusy === 'submit'} onClick={() => { setGenerationPreview(null); setGenerationCreativePlanningJobId(null) }}>返回修改</button><button className={primary} disabled={generationBusy === 'submit'} onClick={() => void confirmGeneration()}>{generationBusy === 'submit' ? '正在提交…' : '确认并开始生成'}</button></div>
      </div>
    </div>}
    <BatchTryOnGarmentPreprocessDialog
      open={productPreprocessOpen}
      garments={productPreprocessGarments}
      sourceUrls={productPreprocessUrls}
      saving={productPreprocessSaving}
      title="商品正反面参考处理"
      description="复用批量套图的裁剪与擦除画布；原始商品图永久保留，保存后只新增带来源关系的正面/背面参考。"
      onClose={() => setProductPreprocessOpen(false)}
      onSave={saveProductReferences}
    />
    <AttachmentMaterialSaveDialog
      open={materialSaveOpen}
      context={materialSaveContext}
      title={materialSaveOutputId ? '保存单张到个人素材库' : '保存整套到个人素材库'}
      saving={materialSaving}
      onClose={() => setMaterialSaveOpen(false)}
      onSubmit={submitMaterialSave}
    />
  </div>
}

export default function AttachmentImageWorkbenchPage() {
  const { sessionId = '' } = useParams()
  return sessionId ? <WorkbenchDetail sessionId={sessionId} /> : <SessionHub />
}
