import { useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react'
import type { AmazonPromptDraft } from '../lib/amazonPrompt'
import { AMAZON_MARKETPLACES, type AmazonMarketplaceId } from '../lib/amazonMarketplaces'
import type { AmazonAPlusModuleSpec, AmazonAPlusPlan } from '../lib/listingPlanner'
import {
  A_PLUS_MODE_CONFIG,
  A_PLUS_WORKBENCH_SIZE_OPTIONS,
  buildAPlusWorkbenchSpecs,
  getAPlusModeModules,
  getAPlusModuleBaseId,
  getAPlusWorkbenchModule,
  getDefaultAPlusModuleSizes,
  resolveAPlusModeTransition,
  type APlusMode,
  type APlusProjectState,
} from '../lib/aPlusWorkbenchModules'
import type { AmazonPlannerSession, InputImage } from '../types'
import { useImagePaste } from '../hooks/useImagePaste'
import {
  ChevronDownIcon,
  CloseIcon,
  CopyIcon,
  DragHandleIcon,
  EyeIcon,
  HistoryIcon,
  PhotoIcon,
  PlusIcon,
  SettingsIcon,
  TrashIcon,
} from './icons'

type DraftField = Exclude<keyof AmazonPromptDraft, 'kind'>
type ModuleTab = 'select' | 'arrange'

interface APlusModernWorkspaceProps {
  draft: AmazonPromptDraft
  onDraftChange: (field: DraftField, value: string) => void
  listingText: string
  onListingTextChange: (value: string) => void
  inputImages: InputImage[]
  onUploadFiles: (files: File[]) => Promise<void>
  onRemoveImage: (id: string) => void
  onClearImages: () => void
  onPreviewImage: (id: string) => void
  marketplaceId: AmazonMarketplaceId
  onMarketplaceChange: (value: string) => void
  resolution: '2k' | '4k'
  onResolutionChange: (value: '2k' | '4k') => void
  projectState: APlusProjectState
  onProjectStateChange: (state: APlusProjectState) => void
  onModeChange: (mode: APlusMode, state: APlusProjectState) => void
  selectedStyleLabel: string
  onOpenApiSettings: () => void
  plans: AmazonAPlusPlan[]
  onUpdatePlanPrompt: (index: number, prompt: string) => void
  onAiPlan: (specs: AmazonAPlusModuleSpec[], instanceIds: string[]) => Promise<boolean>
  onAiHelpWrite: (specs: AmazonAPlusModuleSpec[], instanceIds: string[]) => Promise<boolean>
  onGenerateSet: (specs: AmazonAPlusModuleSpec[], instanceIds: string[]) => Promise<void>
  isPlanning: boolean
  isGenerating: boolean
  generationProgress: { current: number; total: number }
  plannerError: string
  sessions: AmazonPlannerSession[]
  onRestoreSession: (session: AmazonPlannerSession) => Promise<void>
  onDeleteSession: (id: string) => Promise<void>
  debugPayload: object
}

const CARD = 'rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:border-white/[0.08] dark:bg-gray-900'
const INPUT = 'w-full rounded-lg border border-[#E5E7EB] bg-white px-3 py-2.5 text-sm text-[#111827] outline-none transition placeholder:text-gray-400 focus:border-[#2563EB] focus:ring-2 focus:ring-blue-500/10 dark:border-white/[0.08] dark:bg-gray-950 dark:text-gray-100'
const LABEL = 'mb-1.5 block text-xs font-medium text-[#6B7280] dark:text-gray-400'
const MAX_MODULES = 16

export default function APlusModernWorkspace(props: APlusModernWorkspaceProps) {
  const {
    draft, onDraftChange, listingText, onListingTextChange, inputImages, onUploadFiles,
    onRemoveImage, onClearImages, onPreviewImage, marketplaceId, onMarketplaceChange,
    resolution, onResolutionChange, projectState, onProjectStateChange, onModeChange,
    selectedStyleLabel, onOpenApiSettings, plans, onUpdatePlanPrompt, onAiPlan,
    onAiHelpWrite, onGenerateSet, isPlanning, isGenerating, generationProgress,
    plannerError, sessions, onRestoreSession, onDeleteSession, debugPayload,
  } = props
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<ModuleTab>('select')
  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [showMoreProductInfo, setShowMoreProductInfo] = useState(false)
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const [showDebugPayload, setShowDebugPayload] = useState(false)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [pendingMode, setPendingMode] = useState<APlusMode | null>(null)
  const imagePasteZoneProps = useImagePaste({
    disabled: inputImages.length >= 16 || isGenerating,
    maxFiles: Math.max(0, 16 - inputImages.length),
    onPasteFiles: onUploadFiles,
  })

  const selectedIds = projectState.selectedModuleIds
  const sizes = projectState.moduleSizes
  const extraRequirements = projectState.moduleExtraRequirements
  const modeConfig = A_PLUS_MODE_CONFIG[projectState.mode]
  const availableModules = useMemo(() => getAPlusModeModules(projectState.mode), [projectState.mode])
  const selectedSpecs = useMemo(
    () => buildAPlusWorkbenchSpecs(selectedIds, sizes, modeConfig.contentType, extraRequirements),
    [extraRequirements, modeConfig.contentType, selectedIds, sizes],
  )
  const drawerIndex = drawerId ? selectedIds.indexOf(drawerId) : -1
  const drawerModule = drawerId ? getAPlusWorkbenchModule(drawerId) : null
  const drawerPlan = drawerIndex >= 0 ? plans[drawerIndex] ?? null : null
  const history = sessions.filter((session) => session.mode === 'aplus')
  const pendingIncompatibleIds = pendingMode
    ? selectedIds.filter((id) => !A_PLUS_MODE_CONFIG[pendingMode].availableModules.includes(getAPlusModuleBaseId(id)))
    : []

  const updateProject = (patch: Partial<APlusProjectState>, manual = false) => {
    onProjectStateChange({
      ...projectState,
      ...patch,
      hasManualComposition: manual ? true : projectState.hasManualComposition,
    })
  }

  const applyMode = (mode: APlusMode) => {
    const { nextState } = resolveAPlusModeTransition(projectState, mode)
    setDrawerId(null)
    setPendingMode(null)
    onModeChange(mode, nextState)
  }

  const requestModeChange = (mode: APlusMode) => {
    if (mode === projectState.mode) return
    const { incompatibleModuleIds } = resolveAPlusModeTransition(projectState, mode)
    if (incompatibleModuleIds.length) setPendingMode(mode)
    else applyMode(mode)
  }

  const toggleModule = (baseId: string) => {
    const existing = selectedIds.find((id) => getAPlusModuleBaseId(id) === baseId)
    if (existing) {
      updateProject({ selectedModuleIds: selectedIds.filter((id) => getAPlusModuleBaseId(id) !== baseId) }, true)
      if (drawerId && getAPlusModuleBaseId(drawerId) === baseId) setDrawerId(null)
      return
    }
    if (selectedIds.length >= MAX_MODULES) return
    const nextIds = [...selectedIds, baseId]
    updateProject({ selectedModuleIds: nextIds, moduleSizes: { ...sizes, [baseId]: getAPlusWorkbenchModule(baseId).defaultSize } }, true)
  }

  const selectAll = () => {
    if (selectedIds.length === availableModules.length) {
      updateProject({ selectedModuleIds: [] }, true)
      setDrawerId(null)
      return
    }
    const ids = availableModules.map((item) => item.id).slice(0, MAX_MODULES)
    updateProject({ selectedModuleIds: ids, moduleSizes: { ...sizes, ...getDefaultAPlusModuleSizes(ids) } }, true)
  }

  const removeModule = (instanceId: string) => {
    updateProject({ selectedModuleIds: selectedIds.filter((id) => id !== instanceId) }, true)
    if (drawerId === instanceId) setDrawerId(null)
  }

  const copyModule = (instanceId: string) => {
    if (selectedIds.length >= MAX_MODULES) return
    const copyId = `${getAPlusModuleBaseId(instanceId)}::copy::${Date.now()}`
    const index = selectedIds.indexOf(instanceId)
    const nextIds = [...selectedIds.slice(0, index + 1), copyId, ...selectedIds.slice(index + 1)]
    updateProject({
      selectedModuleIds: nextIds,
      moduleSizes: { ...sizes, [copyId]: sizes[instanceId] || getAPlusWorkbenchModule(instanceId).defaultSize },
      moduleExtraRequirements: { ...extraRequirements, [copyId]: extraRequirements[instanceId] || '' },
    }, true)
  }

  const moveModule = (targetId: string) => {
    if (!draggedId || draggedId === targetId) return
    const from = selectedIds.indexOf(draggedId)
    const to = selectedIds.indexOf(targetId)
    if (from < 0 || to < 0) return
    const next = [...selectedIds]
    next.splice(from, 1)
    next.splice(to, 0, draggedId)
    updateProject({ selectedModuleIds: next }, true)
    setDraggedId(null)
  }

  const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const files = Array.from(event.dataTransfer.files).filter((file) => file.type.startsWith('image/'))
    if (files.length) await onUploadFiles(files)
  }

  return (
    <section data-no-drag-select className="relative -mx-2 mt-4 min-h-[720px] rounded-2xl bg-[#F6F7F9] px-3 pb-24 pt-1 dark:bg-gray-950 sm:-mx-3 sm:px-4">
      <header className="flex flex-col gap-4 border-b border-[#E5E7EB] py-5 lg:flex-row lg:items-center lg:justify-between dark:border-white/[0.08]">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-[#111827] dark:text-white">A+ 图工作台</h1>
          <p className="mt-1 text-[13px] text-[#6B7280] dark:text-gray-400">上传商品素材，选择 A+ 模块，AI 一次生成完整 A+ 内容。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setShowHistory(true)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-[#E5E7EB] bg-white px-3 text-sm font-medium text-[#374151] transition hover:border-gray-300 hover:bg-gray-50 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-200"><HistoryIcon className="h-4 w-4" />生成历史{history.length ? <span className="rounded-full bg-gray-100 px-1.5 text-[10px] dark:bg-white/[0.08]">{history.length}</span> : null}</button>
        </div>
      </header>

      <div className="grid gap-4 py-4 lg:grid-cols-[minmax(300px,340px)_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div {...imagePasteZoneProps} className={`${CARD} outline-none focus:ring-2 focus:ring-blue-500/20`}>
            <div className="mb-3 flex items-center justify-between"><h2 className="text-[15px] font-semibold text-[#111827] dark:text-white">产品原图</h2><span className="text-xs text-[#6B7280]">{inputImages.length} / 16</span></div>
            <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" multiple className="hidden" onChange={(event) => { void onUploadFiles(Array.from(event.target.files || [])); event.target.value = '' }} />
            {inputImages.length === 0 ? (
              <div onDragOver={(event) => event.preventDefault()} onDrop={(event) => void handleDrop(event)} onClick={() => fileInputRef.current?.click()} className="flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-[#FAFAFB] px-4 text-center transition hover:border-blue-400 hover:bg-blue-50/40 dark:border-white/[0.12] dark:bg-white/[0.025]">
                <span className="mb-3 grid h-10 w-10 place-items-center rounded-full bg-white text-[#2563EB] shadow-sm dark:bg-white/[0.08]"><PhotoIcon className="h-5 w-5" /></span><span className="text-sm font-semibold text-[#111827] dark:text-gray-100">上传产品图</span><span className="mt-1 text-xs text-[#6B7280]">JPG / PNG / WEBP · 最多16张</span><span className="mt-2 text-[11px] font-medium text-blue-600">点击此区域后可 Ctrl/⌘+V 粘贴</span><span className="mt-2 text-[11px] leading-relaxed text-gray-400">建议上传正面、背面、侧面及产品细节图。</span>
              </div>
            ) : (
              <div><div className="grid grid-cols-4 gap-2">{inputImages.map((image, index) => <div key={image.id} className="group relative aspect-square overflow-hidden rounded-lg border border-[#E5E7EB] bg-gray-50"><button type="button" onClick={() => onPreviewImage(image.id)} className="h-full w-full"><img src={image.dataUrl} alt={`产品图 ${index + 1}`} className="h-full w-full object-cover" /></button><button type="button" onClick={() => onRemoveImage(image.id)} aria-label={`删除产品图 ${index + 1}`} className="absolute right-1 top-1 grid h-6 w-6 place-items-center rounded-md bg-black/60 text-white opacity-0 transition group-hover:opacity-100"><CloseIcon className="h-3.5 w-3.5" /></button></div>)}{inputImages.length < 16 && <button type="button" onClick={() => fileInputRef.current?.click()} className="grid aspect-square place-items-center rounded-lg border border-dashed border-gray-300 text-gray-400 transition hover:border-blue-400 hover:text-blue-600"><PlusIcon className="h-5 w-5" /></button>}</div><div className="mt-3 flex items-center justify-between gap-2"><span className="text-[11px] text-blue-600">点击卡片后可 Ctrl/⌘+V 继续粘贴</span><button type="button" onClick={onClearImages} className="text-xs font-medium text-[#6B7280] hover:text-red-600">清空产品图</button></div></div>
            )}
          </div>

          <div className={CARD}>
            <div className="mb-3 flex items-center justify-between"><h2 className="text-[15px] font-semibold text-[#111827] dark:text-white">产品信息</h2><button type="button" disabled={isPlanning} onClick={() => void onAiHelpWrite(selectedSpecs, selectedIds)} className="text-xs font-semibold text-[#2563EB] disabled:opacity-50">✨ AI 分析商品</button></div>
            <div className="space-y-3">
              <label><span className={LABEL}>产品名称</span><input value={draft.productTitle} onChange={(event) => onDraftChange('productTitle', event.target.value)} className={INPUT} placeholder="例如：男士橄榄球比赛球衣" /></label>
              <label><span className={LABEL}>核心卖点</span><textarea value={draft.sellingPoints} onChange={(event) => onDraftChange('sellingPoints', event.target.value)} className={`${INPUT} min-h-24 resize-y`} placeholder="每行一个卖点，AI 将据此规划模块" /></label>
              <label><span className={LABEL}>目标人群</span><input value={draft.audience} onChange={(event) => onDraftChange('audience', event.target.value)} className={INPUT} /></label>
              <label><span className={LABEL}>使用场景</span><input value={draft.scene} onChange={(event) => onDraftChange('scene', event.target.value)} className={INPUT} /></label>
              <label><span className={LABEL}>其他要求</span><textarea value={draft.forbidden} onChange={(event) => onDraftChange('forbidden', event.target.value)} className={`${INPUT} min-h-20 resize-y`} /></label>
            </div>
            <button type="button" onClick={() => setShowMoreProductInfo((value) => !value)} className="mt-3 flex w-full items-center justify-between border-t border-[#E5E7EB] pt-3 text-xs font-medium text-[#6B7280] dark:border-white/[0.08]"><span>更多产品信息</span><ChevronDownIcon className={`h-4 w-4 transition ${showMoreProductInfo ? 'rotate-180' : ''}`} /></button>
            {showMoreProductInfo && <div className="mt-3 space-y-3"><label><span className={LABEL}>商品标题 / Listing 内容</span><textarea value={listingText} onChange={(event) => onListingTextChange(event.target.value)} className={`${INPUT} min-h-24 resize-y`} /></label><label><span className={LABEL}>类目</span><input value={draft.category} onChange={(event) => onDraftChange('category', event.target.value)} className={INPUT} /></label><label><span className={LABEL}>品牌 / 型号</span><input value={draft.brand} onChange={(event) => onDraftChange('brand', event.target.value)} className={INPUT} /></label><label><span className={LABEL}>颜色</span><input value={draft.color} onChange={(event) => onDraftChange('color', event.target.value)} className={INPUT} /></label><label><span className={LABEL}>材质 / 工艺</span><input value={draft.material} onChange={(event) => onDraftChange('material', event.target.value)} className={INPUT} /></label><label><span className={LABEL}>包装清单</span><textarea value={draft.packageIncludes} onChange={(event) => onDraftChange('packageIncludes', event.target.value)} className={`${INPUT} min-h-20 resize-y`} /></label></div>}
          </div>

          <div className={CARD}>
            <h2 className="mb-3 text-[15px] font-semibold text-[#111827] dark:text-white">生成设置</h2>
            <div className="space-y-3"><div><span className={LABEL}>当前模型</span><div className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm font-medium text-[#111827] dark:bg-white/[0.04] dark:text-gray-100">平台资源池图片模型</div></div><label><span className={LABEL}>目标站点</span><select value={marketplaceId} onChange={(event) => onMarketplaceChange(event.target.value)} className={INPUT}>{AMAZON_MARKETPLACES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label><span className={LABEL}>文案语言</span><input value={AMAZON_MARKETPLACES.find((item) => item.id === marketplaceId)?.copyLanguage || 'English'} readOnly className={`${INPUT} bg-gray-50`} /></label><label><span className={LABEL}>交付质量</span><select value={resolution} onChange={(event) => onResolutionChange(event.target.value as '2k' | '4k')} className={INPUT}><option value="2k">2K</option><option value="4k">4K</option></select></label></div>
            <button type="button" onClick={() => setShowAdvancedSettings((value) => !value)} className="mt-3 flex w-full items-center justify-between border-t border-[#E5E7EB] pt-3 text-xs font-medium text-[#6B7280] dark:border-white/[0.08]"><span>高级设置</span><ChevronDownIcon className={`h-4 w-4 transition ${showAdvancedSettings ? 'rotate-180' : ''}`} /></button>
            {showAdvancedSettings && <div className="mt-3 space-y-3">
              <label><span className={LABEL}>A+ 类型</span><select value={projectState.mode} onChange={(event) => requestModeChange(event.target.value as APlusMode)} className={INPUT}>{Object.values(A_PLUS_MODE_CONFIG).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><span className="mt-1.5 block text-[11px] leading-relaxed text-gray-400">{modeConfig.description}</span></label>
              <label><span className={LABEL}>输出格式</span><select value={projectState.outputFormat} onChange={(event) => updateProject({ outputFormat: event.target.value as APlusProjectState['outputFormat'] })} className={INPUT}><option value="jpeg">JPEG</option><option value="png">PNG</option><option value="webp">WEBP</option></select></label>
              {projectState.outputFormat !== 'png' && <label><span className={LABEL}>输出压缩质量</span><input type="number" min="1" max="100" value={projectState.outputCompression ?? 90} onChange={(event) => updateProject({ outputCompression: Math.min(100, Math.max(1, Number(event.target.value) || 90)) })} className={INPUT} /><span className="mt-1.5 block text-[11px] text-gray-400">真实用于服务端 JPEG / WEBP 交付编码。</span></label>}
              <div><span className={LABEL}>风格参考</span><div className="rounded-lg bg-gray-50 px-3 py-2.5 text-sm text-[#374151] dark:bg-white/[0.04] dark:text-gray-200">{selectedStyleLabel || '默认风格参考'}</div></div>
              <button type="button" onClick={onOpenApiSettings} className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-xs font-semibold text-[#374151] hover:bg-gray-50 dark:border-white/[0.08] dark:text-gray-200">API 配置</button>
              {import.meta.env.DEV && <button type="button" onClick={() => setShowDebugPayload(true)} className="w-full rounded-lg border border-dashed border-blue-300 px-3 py-2 text-xs font-semibold text-[#2563EB]">查看生成参数</button>}
            </div>}
          </div>
        </aside>

        <main className={`${CARD} min-w-0 self-start`}>
          <div className="flex flex-col gap-3 border-b border-[#E5E7EB] pb-4 sm:flex-row sm:items-center sm:justify-between dark:border-white/[0.08]"><div><h2 className="text-base font-semibold text-[#111827] dark:text-white">包含模块</h2><p className="mt-1 text-xs text-[#6B7280]">{modeConfig.name} · 已选 {selectedIds.length} / {Math.min(MAX_MODULES, availableModules.length)}</p></div><div className="flex flex-wrap gap-2"><button type="button" disabled={isPlanning || !selectedIds.length} onClick={() => void onAiPlan(selectedSpecs, selectedIds)} className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-[#2563EB] transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-blue-400/20 dark:bg-blue-400/10">✨ AI 策划已选模块</button><button type="button" onClick={selectAll} className="rounded-lg border border-[#E5E7EB] px-3 py-2 text-xs font-semibold text-[#374151] hover:bg-gray-50 dark:border-white/[0.08] dark:text-gray-200">{selectedIds.length === availableModules.length ? '取消全选' : '全选可用模块'}</button></div></div>
          <div className="mt-4 flex gap-1 border-b border-[#E5E7EB] dark:border-white/[0.08]">{([{ id: 'select', label: '模块选择' }, { id: 'arrange', label: 'A+编排' }] as const).map((item) => <button key={item.id} type="button" onClick={() => setTab(item.id)} className={`relative px-4 pb-3 text-sm font-medium ${tab === item.id ? 'text-[#2563EB] after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-[#2563EB]' : 'text-[#6B7280] hover:text-[#111827]'}`}>{item.label}</button>)}</div>
          {tab === 'select' ? <div className="mt-4 grid gap-3 xl:grid-cols-2">{availableModules.map((module) => { const instanceId = selectedIds.find((id) => getAPlusModuleBaseId(id) === module.id); const selected = Boolean(instanceId); return <article key={module.id} className={`rounded-xl border p-4 transition ${selected ? 'border-[#2563EB] bg-blue-50/60 dark:bg-blue-400/[0.08]' : 'border-[#E5E7EB] bg-white hover:border-gray-300 hover:shadow-sm dark:border-white/[0.08] dark:bg-gray-900'}`}><div className="flex items-start gap-3"><button type="button" onClick={() => toggleModule(module.id)} aria-label={`${selected ? '取消选择' : '选择'}${module.name}`} className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border text-[12px] font-bold ${selected ? 'border-[#2563EB] bg-[#2563EB] text-white' : 'border-gray-300 bg-white dark:bg-gray-950'}`}>{selected ? '✓' : ''}</button><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-semibold text-[#111827] dark:text-gray-100">{module.name}</h3><span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-[#6B7280] dark:bg-white/[0.06]">{module.badge}</span></div><p className="mt-1.5 text-xs leading-relaxed text-[#6B7280]">{module.description}</p><div className="mt-3 flex items-center justify-between gap-2"><select disabled={!selected} value={instanceId ? sizes[instanceId] || module.defaultSize : module.defaultSize} onChange={(event) => instanceId && updateProject({ moduleSizes: { ...sizes, [instanceId]: event.target.value } }, true)} className="h-8 rounded-lg border border-[#E5E7EB] bg-white px-2 text-xs text-[#374151] outline-none disabled:bg-gray-50 disabled:text-gray-400 dark:border-white/[0.08] dark:bg-gray-950">{A_PLUS_WORKBENCH_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size.replace('x', ' × ')}</option>)}</select>{selected && <button type="button" onClick={() => setDrawerId(instanceId!)} className="inline-flex items-center gap-1 text-xs font-semibold text-[#2563EB]"><SettingsIcon className="h-3.5 w-3.5" />设置</button>}</div></div></div></article> })}</div> : selectedIds.length ? <div className="mt-4 space-y-2">{selectedIds.map((instanceId, index) => { const module = getAPlusWorkbenchModule(instanceId); return <div key={instanceId} draggable onDragStart={() => setDraggedId(instanceId)} onDragOver={(event) => event.preventDefault()} onDrop={() => moveModule(instanceId)} className="flex items-center gap-3 rounded-xl border border-[#E5E7EB] bg-white p-3 transition hover:border-gray-300 hover:shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><DragHandleIcon className="h-5 w-5 cursor-grab text-gray-300"/><span className="w-7 text-xs font-semibold tabular-nums text-gray-400">{String(index + 1).padStart(2, '0')}</span><div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold text-[#111827] dark:text-gray-100">{module.name}</div><div className="mt-0.5 text-xs text-[#6B7280]">{sizes[instanceId] || module.defaultSize}</div></div><button type="button" onClick={() => copyModule(instanceId)} className="grid h-8 w-8 place-items-center rounded-lg text-gray-400 hover:bg-gray-100" title="复制模块"><CopyIcon className="h-4 w-4"/></button><button type="button" onClick={() => setDrawerId(instanceId)} className="grid h-8 w-8 place-items-center rounded-lg text-gray-400 hover:bg-gray-100" title="模块设置"><SettingsIcon className="h-4 w-4"/></button><button type="button" onClick={() => removeModule(instanceId)} className="grid h-8 w-8 place-items-center rounded-lg text-gray-400 hover:bg-red-50 hover:text-red-600" title="删除模块"><TrashIcon className="h-4 w-4"/></button></div>})}<p className="pt-2 text-center text-xs text-gray-400">拖动左侧手柄调整 A+ 模块顺序</p></div> : <div className="grid min-h-80 place-items-center text-center"><div><PhotoIcon className="mx-auto h-6 w-6 text-gray-300"/><h3 className="mt-3 text-sm font-semibold">尚未选择模块</h3><button type="button" onClick={() => setTab('select')} className="mt-4 rounded-lg bg-[#111827] px-4 py-2 text-xs font-semibold text-white">选择模块</button></div></div>}
          {(plannerError || isPlanning) && <div className={`mt-4 rounded-lg border px-3 py-2.5 text-xs leading-relaxed ${plannerError ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-blue-50 text-blue-700'}`}>{plannerError || 'AI 正在分析商品并策划已选 A+ 模块…'}</div>}
        </main>
      </div>

      <div className="sticky bottom-3 z-20 mx-auto flex max-w-5xl flex-col gap-3 rounded-xl border border-[#E5E7EB] bg-white/95 p-3 shadow-[0_12px_40px_rgba(15,23,42,0.14)] backdrop-blur sm:flex-row sm:items-center sm:justify-between dark:border-white/[0.1] dark:bg-gray-900/95"><div><div className="text-sm font-semibold text-[#111827] dark:text-white">已选择 {selectedIds.length} 个模块</div><div className="mt-0.5 text-xs text-[#6B7280]">预计生成 {selectedIds.length} 张图片{isGenerating ? ` · 正在提交 ${generationProgress.current}/${generationProgress.total}` : ''}</div></div><div className="flex flex-wrap items-center justify-end gap-2"><button type="button" onClick={() => updateProject({ selectedModuleIds: [] }, true)} className="h-10 rounded-lg px-3 text-sm font-medium text-[#6B7280] hover:bg-gray-50">清空</button><button type="button" disabled={!selectedIds.length} onClick={() => setShowPreview(true)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-[#E5E7EB] px-4 text-sm font-semibold text-[#374151] disabled:opacity-40 dark:border-white/[0.08] dark:text-gray-200"><EyeIcon className="h-4 w-4"/>预览方案</button><button type="button" disabled={!selectedIds.length || isPlanning || isGenerating || plans.length !== selectedIds.length} onClick={() => void onGenerateSet(selectedSpecs, selectedIds)} title={plans.length !== selectedIds.length ? '请先使用“AI 策划已选模块”生成对应 Prompt' : ''} className="h-10 rounded-lg bg-[#2563EB] px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50">{isGenerating ? `生成中 ${generationProgress.current}/${generationProgress.total}` : '生成整套 A+'}</button></div></div>

      {drawerModule && drawerId && <div className="fixed inset-0 z-[80] flex justify-end bg-black/25" onMouseDown={(event) => { if (event.target === event.currentTarget) setDrawerId(null) }}><aside className="h-full w-full max-w-[460px] overflow-y-auto bg-white p-5 shadow-2xl dark:bg-gray-900"><div className="flex items-start justify-between"><div><div className="text-xs font-medium text-[#2563EB]">模块设置</div><h2 className="mt-1 text-lg font-semibold text-[#111827] dark:text-white">{drawerModule.name}</h2><p className="mt-1 text-xs leading-relaxed text-[#6B7280]">{drawerModule.description}</p></div><button type="button" onClick={() => setDrawerId(null)} className="grid h-9 w-9 place-items-center rounded-lg text-gray-400 hover:bg-gray-100"><CloseIcon className="h-4 w-4"/></button></div><div className="mt-6 space-y-5"><label><span className={LABEL}>模块尺寸</span><select value={sizes[drawerId] || drawerModule.defaultSize} onChange={(event) => updateProject({ moduleSizes: { ...sizes, [drawerId]: event.target.value } }, true)} className={INPUT}>{A_PLUS_WORKBENCH_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size.replace('x', ' × ')}</option>)}</select></label><div><span className={LABEL}>参考图片</span><div className="grid grid-cols-5 gap-2">{inputImages.slice(0, 10).map((image, index) => <button key={image.id} type="button" onClick={() => onPreviewImage(image.id)} className="aspect-square overflow-hidden rounded-lg border border-[#E5E7EB]"><img src={image.dataUrl} alt={`参考图 ${index + 1}`} className="h-full w-full object-cover"/></button>)}{!inputImages.length && <div className="col-span-5 rounded-lg bg-gray-50 px-3 py-5 text-center text-xs text-gray-400">请先在左侧上传产品图</div>}</div></div><label><span className={LABEL}>额外要求</span><textarea value={extraRequirements[drawerId] || ''} onChange={(event) => updateProject({ moduleExtraRequirements: { ...extraRequirements, [drawerId]: event.target.value } }, true)} className={`${INPUT} min-h-28 resize-y`} /></label><details className="rounded-xl border border-[#E5E7EB] dark:border-white/[0.08]"><summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-[#374151] dark:text-gray-200">高级 Prompt 设置</summary><div className="border-t border-[#E5E7EB] p-4 dark:border-white/[0.08]"><textarea value={drawerPlan?.prompt || ''} onChange={(event) => drawerIndex >= 0 && onUpdatePlanPrompt(drawerIndex, event.target.value)} disabled={!drawerPlan} className={`${INPUT} min-h-64 resize-y font-mono text-xs leading-relaxed disabled:bg-gray-50 disabled:text-gray-400`} placeholder="请先完成 AI 策划，之后可编辑当前模块 Prompt。"/><p className="mt-2 text-[11px] text-gray-400">Prompt 修改会直接用于当前模块的下一次生成。</p></div></details></div></aside></div>}

      {pendingMode && <Modal title="确认切换 A+ 类型" onClose={() => setPendingMode(null)}><p className="text-sm leading-relaxed text-[#374151]">当前方案包含 {pendingIncompatibleIds.length} 个目标类型不支持的模块，确认切换后将移除：</p><div className="mt-3 space-y-2">{pendingIncompatibleIds.map((id) => <div key={id} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{getAPlusWorkbenchModule(id).name}</div>)}</div><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setPendingMode(null)} className="rounded-lg border border-[#E5E7EB] px-4 py-2 text-sm font-semibold">取消</button><button type="button" onClick={() => applyMode(pendingMode)} className="rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white">确认切换</button></div></Modal>}
      {showPreview && <Modal title="A+ 方案预览" onClose={() => setShowPreview(false)}><div className="mb-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-[#6B7280]">{modeConfig.name} · {resolution.toUpperCase()} · {projectState.outputFormat.toUpperCase()}</div><div className="space-y-2">{selectedIds.map((id, index) => { const module = getAPlusWorkbenchModule(id); return <div key={id} className="flex items-center gap-3 rounded-lg border border-[#E5E7EB] p-3 dark:border-white/[0.08]"><span className="w-7 text-xs font-semibold text-gray-400">{String(index + 1).padStart(2, '0')}</span><div className="flex-1"><div className="text-sm font-semibold text-[#111827] dark:text-gray-100">{module.name}</div><div className="mt-0.5 text-xs text-[#6B7280]">{sizes[id] || module.defaultSize}</div></div></div>})}</div></Modal>}
      {showHistory && <Modal title="生成历史" onClose={() => setShowHistory(false)} wide><div className="space-y-2">{history.length ? history.map((session) => <div key={session.id} className="flex flex-col gap-3 rounded-xl border border-[#E5E7EB] p-3 sm:flex-row sm:items-center dark:border-white/[0.08]"><div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold text-[#111827] dark:text-gray-100">{session.title}</div><div className="mt-1 text-xs text-[#6B7280]">{session.aPlusMode ? A_PLUS_MODE_CONFIG[session.aPlusMode].name : '旧版 A+'} · {session.aPlusPlans.length} 个模块 · {new Date(session.updatedAt).toLocaleString()}</div></div><div className="flex gap-2"><button type="button" onClick={() => void onRestoreSession(session).then(() => setShowHistory(false))} className="rounded-lg bg-[#111827] px-3 py-2 text-xs font-semibold text-white dark:bg-white dark:text-gray-950">恢复</button><button type="button" onClick={() => void onDeleteSession(session.id)} className="rounded-lg border border-[#E5E7EB] px-3 py-2 text-xs font-semibold text-red-600 dark:border-white/[0.08]">删除</button></div></div>) : <div className="py-14 text-center text-sm text-gray-400">暂无 A+ 策划历史</div>}</div></Modal>}
      {showDebugPayload && <Modal title="最终生成参数" onClose={() => setShowDebugPayload(false)} wide><pre className="overflow-auto rounded-xl bg-gray-950 p-4 text-xs leading-relaxed text-emerald-300">{JSON.stringify(debugPayload, null, 2)}</pre></Modal>}
    </section>
  )
}

function Modal({ title, onClose, wide = false, children }: { title: string; onClose: () => void; wide?: boolean; children: ReactNode }) {
  return <div className="fixed inset-0 z-[90] grid place-items-center bg-black/35 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className={`max-h-[85vh] w-full overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl dark:bg-gray-900 ${wide ? 'max-w-2xl' : 'max-w-md'}`}><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold text-[#111827] dark:text-white">{title}</h2><button type="button" onClick={onClose} className="grid h-9 w-9 place-items-center rounded-lg text-gray-400 hover:bg-gray-100"><CloseIcon className="h-4 w-4"/></button></div>{children}</div></div>
}
