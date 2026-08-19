import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import AttachmentImageModuleCard from '../components/attachment-image/AttachmentImageModuleCard'
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
import {
  createCategoryOutputProject,
  getCategoryOutputProject,
  getListingOutputOptions,
  getListingWorkflowSession,
  listListingImageTaskGroups,
  listListingWorkflowSessions,
  updateCategoryOutputProject,
  type CategoryOutputProject,
  type ListingImageTaskGroup,
  type ListingWorkflowSession,
  type ListingWorkflowSessionSummary,
} from '../lib/listingWorkflowApi'
import { useStore } from '../store'
import { AuthApiError } from '../lib/authApi'
import {
  getAttachmentPlanning,
  listAttachmentPlanVersions,
  optimizeAttachmentModulePrompt,
  planAttachmentSuite,
  replanAttachmentModule,
  updateAttachmentModule,
  updateAttachmentVisualDirection,
  type AttachmentPlanningState,
  type AttachmentPlanVersion,
} from '../lib/attachmentPlanningApi'
import { randomUuid } from '../lib/randomUuid'

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
  return <div className="space-y-5 pb-12 pt-6">
    <header className="overflow-hidden rounded-2xl bg-gradient-to-r from-blue-700 via-blue-600 to-indigo-600 p-6 text-white shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-100">Listing Visual Production</div>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="text-2xl font-bold">附图生成工作台</h1><p className="mt-2 max-w-3xl text-sm text-blue-50">选择已确认的商品，统一编排六类附图模块、视觉方向和生成参数。旧品类 Listing 工作流继续保留。</p></div>
        <Link className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-blue-700 shadow-sm" to="/workspaces/listing">新建或继续商品</Link>
      </div>
    </header>

    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}
    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">选择商品</h2><p className="mt-1 text-xs text-gray-500">这里只显示已经确认并保存 Listing 版本的 Session；状态进入生成中后仍可继续打开。</p></div><span className="text-xs text-gray-500">可用 {readySessions.length} 个</span></div>
      {loading && <div className="mt-5 rounded-xl bg-gray-50 p-5 text-center text-sm text-gray-500 dark:bg-white/[0.03]">正在读取商品 Session…</div>}
      {!loading && readySessions.length > 0 && <div className="mt-4 grid gap-3 lg:grid-cols-2">{readySessions.map((session) => <button key={session.id} type="button" onClick={() => navigate(`/attachment-image-workbench/${session.id}`)} className="rounded-2xl border border-gray-200 p-4 text-left transition hover:border-blue-300 hover:bg-blue-50/40 hover:shadow-sm dark:border-white/[0.08] dark:hover:bg-blue-500/5">
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-950 dark:text-white">{summaryTitle(session)}</div><div className="mt-1 text-xs text-gray-500">{session.category_name} · {session.skill_name} V{session.skill_version_number || '-'}</div></div><span className="shrink-0 rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">Listing V{session.listing_version_number}</span></div>
        <div className="mt-4 flex items-center justify-between text-xs text-gray-500"><span>{session.source_asset_ids.length} 张产品图</span><span>{new Date(session.updated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</span></div>
      </button>)}</div>}
      {!loading && !readySessions.length && <div className="mt-5 rounded-xl border border-dashed border-gray-200 p-8 text-center dark:border-white/[0.08]"><div className="text-sm font-semibold text-gray-800 dark:text-gray-100">还没有可用的已确认商品</div><p className="mt-2 text-xs text-gray-500">先在品类 Listing 中完成商品分析和 Listing 确认，再回到这里制作附图。</p><Link className={`${primary} mt-4 inline-block`} to="/workspaces/listing">进入品类 Listing</Link></div>}
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
  const [planningBusy, setPlanningBusy] = useState('')
  const [visualDirection, setVisualDirection] = useState('')
  const [visualDirty, setVisualDirty] = useState(false)
  const [suiteVersions, setSuiteVersions] = useState<AttachmentPlanVersion[]>([])
  const [suiteHistoryOpen, setSuiteHistoryOpen] = useState(false)
  const visualDirtyRef = useRef(false)
  const suitePlanningAwaitingResultRef = useRef(false)

  const refreshGroups = async (projectId: string) => {
    const response = await listListingImageTaskGroups(projectId)
    setGroups(response.items)
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
        const nextDraft = normalizeAttachmentWorkbenchDraft(stored, availableCodes)
        const [loadedAssets, taskGroups, planningValue] = await Promise.all([
          Promise.all(projectValue.source_asset_ids.map((id) => getAsset(id).catch(() => null))),
          listListingImageTaskGroups(projectValue.id),
          getAttachmentPlanning(projectValue.id),
        ])
        if (!active) return
        setSession(sessionValue); setProject(projectValue); projectRef.current = projectValue
        setAssets(loadedAssets.filter((item): item is Asset => Boolean(item)))
        setGroups(taskGroups.items); setDraft(nextDraft); draftRef.current = nextDraft
        setPlanning(planningValue); setVisualDirection(planningValue.visual_direction_cn)
        setVisualDirty(false); visualDirtyRef.current = false
        lastSavedSignature.current = JSON.stringify(nextDraft)
        setSaveStatus('saved'); hydrated.current = true
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

  const taskSummary = useMemo(() => summarizeAttachmentTaskGroups(groups), [groups])
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

  const moduleBackend = useMemo(() => Object.fromEntries((project?.modules || []).map((item) => [String(item.code || ''), item])), [project?.modules])
  const selectedModules = selectedAttachmentModules(draft)
  const requestedImages = countRequestedAttachmentImages(draft)
  const attachmentModuleCodes = new Set<string>(attachmentModuleDefinitions.map((definition) => definition.code))
  const resultModuleCount = new Set(groups.flatMap((group) => group.tasks
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

  if (loading) return <div className={`${panel} mt-6`}>正在恢复附图项目与任务状态…</div>
  if (error && (!session || !project)) return <div className="space-y-4 pt-6"><div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</div><Link className={button} to="/workspaces/attachment-images">返回商品列表</Link></div>
  if (!session || !project) return null

  return <div className="space-y-5 pb-28 pt-6">
    <header className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">Attachment Image Workbench</div><h1 className="mt-2 text-2xl font-bold text-gray-950 dark:text-white">附图生成工作台</h1><p className="mt-2 text-sm text-gray-500">{session.category_name} · {session.skill_name} V{session.skill_version_number || '-'} · Listing V{session.listing_version_number}</p></div><div className="flex flex-wrap gap-2"><Link className={button} to="/workspaces/attachment-images">切换商品</Link><Link className={button} to={`/listing-image-workbench/${session.id}`}>打开旧图片工作台</Link></div></div>
    </header>

    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}<button className="ml-3 font-semibold underline" onClick={() => setError('')}>关闭</button></div>}
    {!phaseOneSupported && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">首期仅开放橄榄球衣模块。当前商品仍可查看，但不能保存模块生产配置。</div>}

    <section className={panel}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,.65fr)]">
        <div><div className="flex items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">当前商品</h2><p className="mt-1 text-xs text-gray-500">产品图来自当前 Session，原 Asset 不会被新工作台复制或删除。</p></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">{session.category_name}</span></div>
          <div className="mt-4 flex gap-3 overflow-x-auto pb-1">{assets.map((asset) => <div key={asset.id} className="relative w-24 shrink-0 overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-white/[0.08]"><AuthenticatedImage url={asset.url} alt={asset.filename} className="aspect-square w-full object-contain" placeholderClassName="aspect-square" />{asset.id === session.primary_asset_id && <span className="absolute left-1.5 top-1.5 rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold text-white">主图</span>}</div>)}</div>
          {!assets.length && <div className="mt-4 rounded-xl bg-amber-50 p-4 text-xs text-amber-800">产品 Asset 暂时无法读取，请回到品类 Listing 检查源图片。</div>}
        </div>
        <div><h2 className="truncate text-lg font-semibold text-gray-950 dark:text-white">{productTitle(session)}</h2><div className="mt-4 grid grid-cols-2 gap-3 text-sm"><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">产品图</div><div className="mt-1 font-semibold">{assets.length} 张</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">已选模块</div><div className="mt-1 font-semibold">{selectedModules.length} / 6</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">已有结果模块</div><div className="mt-1 font-semibold">{resultModuleCount} 个</div></div><div className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><div className="text-xs text-gray-500">当前状态</div><div className="mt-1 font-semibold">{statusLabels[project.status] || project.status}</div></div></div><div className="mt-3 text-xs text-gray-400">最终采用模块将在 Phase 5 接入 Output 级审核后显示。</div></div>
      </div>
    </section>

    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold text-gray-950 dark:text-white">整套视觉方向</h2><p className="mt-1 text-xs text-gray-500">统一约束当前已选标准模块；AI整套策划一次返回视觉方向、模块方案和中文Prompt。</p></div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full px-3 py-1 text-xs font-semibold ${planning?.planning_status === 'failed' ? 'bg-red-50 text-red-700' : planning?.planning_status === 'planning' ? 'bg-violet-50 text-violet-700' : 'bg-gray-100 text-gray-600'}`}>{planning?.planning_status === 'planning' ? 'AI策划中' : planning?.visual_direction_version ? `方向 V${planning.visual_direction_version}` : '尚未策划'}</span><button className={button} disabled={!planning} onClick={() => void refreshPlanning()}>刷新策划</button></div></div>
      <textarea disabled={!phaseOneSupported} className="mt-4 min-h-28 w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm leading-6 disabled:bg-gray-100 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" value={visualDirection} placeholder="尚未策划。可以直接填写，也可以点击AI策划生成2～4行统一视觉方向。" onChange={(event) => { setVisualDirection(event.target.value); setVisualDirty(true); visualDirtyRef.current = true }} />
      {planning?.error_message && <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{planning.error_message}</div>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button className={primary} disabled={!phaseOneSupported || !planning || planningBusy !== '' || planningActive || !selectedModules.length} onClick={() => void runSuitePlanning()}>{planning?.visual_direction_version ? 'AI重新分析整套' : 'AI策划整套'}</button>
        <button className={button} disabled={!planning || !visualDirty || planningBusy !== ''} onClick={() => void saveVisualDirection()}>保存视觉方向</button>
        <button className={button} disabled={!planning} onClick={() => { const next = !suiteHistoryOpen; setSuiteHistoryOpen(next); if (next && project) void listAttachmentPlanVersions(project.id).then(setSuiteVersions).catch((reason) => showToast(errorText(reason), 'error')) }}>{suiteHistoryOpen ? '收起方向版本' : '查看方向版本'}</button>
        <span className="text-xs text-gray-400">{planning?.visual_direction_source ? `来源：${planning.visual_direction_source}` : ''}</span>
      </div>
      {suiteHistoryOpen && <div className="mt-4 grid gap-2 md:grid-cols-2">{suiteVersions.length ? suiteVersions.map((item) => <details key={item.id} className="rounded-xl bg-gray-50 p-3 dark:bg-white/[0.03]"><summary className="cursor-pointer text-xs font-semibold text-gray-700 dark:text-gray-200">方向 V{item.version_number} · {item.action} · {new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</summary><p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-gray-500">{item.visual_direction_cn}</p></details>) : <p className="text-xs text-gray-500">暂无历史方向版本。</p>}</div>}
    </section>

    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-semibold text-gray-950 dark:text-white">任务状态</h2><p className="mt-1 text-xs text-gray-500">直接读取现有 Listing 图片 TaskGroup；生成状态与后续审核状态分开。</p></div><div className="flex gap-2"><button className={button} onClick={() => { setPollingPaused(false); void refreshGroups(project.id) }}>刷新状态</button>{pollingPaused && <span className="self-center text-xs text-amber-700">自动刷新已暂停</span>}</div></div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">{[
        ['总任务', taskSummary.total], ['运行中', taskSummary.running], ['排队', taskSummary.queued], ['成功', taskSummary.succeeded], ['失败', taskSummary.failed], ['已中止', taskSummary.cancelled], ['活动批次', taskSummary.activeGroups],
      ].map(([label, value]) => <div key={label} className="rounded-xl bg-gray-50 p-3 text-center dark:bg-white/[0.03]"><div className="text-xs text-gray-500">{label}</div><div className="mt-1 text-lg font-semibold text-gray-950 dark:text-white">{value}</div></div>)}</div>
    </section>

    <section>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold text-gray-950 dark:text-white">附图模块</h2><p className="mt-1 text-xs text-gray-500">首期固定六个模块；模块参数独立保存，不为每个模块创建新 Project。</p></div><div className="flex gap-2"><button className={button} disabled={!phaseOneSupported} onClick={() => selectAvailable(true)}>全选可用模块</button><button className={button} disabled={!phaseOneSupported} onClick={() => selectAvailable(false)}>清空选择</button></div></div>
      <div className="space-y-3">{attachmentModuleDefinitions.map((definition, index) => {
        const backend = moduleBackend[definition.code] || {}
        const tasks = groups.flatMap((group) => group.tasks).filter((task) => task.image_type === definition.code)
        const available = phaseOneSupported && backend.available !== false
        const modulePlanning = planning?.modules.find((item) => item.module_key === definition.code)
        return <AttachmentImageModuleCard key={definition.code} index={index + 1} definition={definition} draft={draft.modules[definition.code]} expanded={expanded.has(definition.code)} available={available} unavailableReason={phaseOneSupported ? String(backend.unavailable_reason || '') : '首期仅支持橄榄球衣。'} objective={String(backend.objective || '')} projectId={project.id} planning={modulePlanning} planningBusy={planningBusy !== '' || planningActive} tasks={tasks} onToggleExpanded={() => setExpanded((current) => { const next = new Set(current); next.has(definition.code) ? next.delete(definition.code) : next.add(definition.code); return next })} onChange={(next) => updateModule(definition.code, next)} onSavePlanning={(input) => saveModulePlanning(definition.code, input)} onReplan={(requirement) => runModulePlanning(definition.code, requirement, false)} onOptimizePrompt={(requirement) => runModulePlanning(definition.code, requirement, true)} />
      })}</div>
    </section>

    <div className="sticky bottom-20 z-20 border border-gray-200 bg-white/95 px-4 py-3 shadow-[0_-10px_30px_rgba(15,23,42,0.08)] backdrop-blur dark:border-white/[0.08] dark:bg-gray-950/95 lg:bottom-4">
      <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-3"><div><div className="text-sm font-semibold text-gray-950 dark:text-white">已选 {selectedModules.length} 个模块 · 计划 {requestedImages} 张图片</div><div className="mt-1 text-xs text-gray-500">{saveStatus === 'saving' ? '正在保存工作台设置…' : saveStatus === 'dirty' ? '有未保存修改' : saveStatus === 'failed' ? '保存失败，请重试' : '工作台设置已保存'} · 正式生成将在 Phase 4 接入</div></div><div className="flex gap-2"><button className={button} disabled={saveStatus === 'saving' || !phaseOneSupported} onClick={() => void saveDraft(true)}>{saveStatus === 'saving' ? '保存中…' : '立即保存'}</button><button className={primary} disabled title="Phase 4 接入现有任务系统后开放">生成选中模块</button></div></div>
    </div>
  </div>
}

export default function AttachmentImageWorkbenchPage() {
  const { sessionId = '' } = useParams()
  return sessionId ? <WorkbenchDetail sessionId={sessionId} /> : <SessionHub />
}
