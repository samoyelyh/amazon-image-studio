import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { removeAsset, uploadAsset, type Asset } from '../lib/contentApi'
import {
  getQuickListingOptions,
  getQuickListingStatus,
  listProductCategories,
  startQuickListingGeneration,
  type ProductCategory,
  type QuickListingOptions,
  type QuickListingStatus,
} from '../lib/listingWorkflowApi'
import { randomUuid } from '../lib/randomUuid'
import { useImagePaste } from '../hooks/useImagePaste'


const panel = 'rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const input = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50'
const imageTypeLabels: Record<string, string> = {
  main: '主图', model: '模特图', detail: '细节图', selling_point: '卖点图',
  scene: '场景图', size_chart: '尺寸图', customization: '定制说明图',
}
const stageLabels: Record<string, string> = {
  analyzing: '正在分析商品并生成中英文 Listing',
  preparing_images: '正在确认 Listing、构建图片提示词和任务组',
  queued: '图片任务已进入生成队列', running: '正在生成图片',
  waiting_for_resource: '图片任务正在等待可用资源', retry_waiting: '图片任务正在等待重试',
  succeeded: '快速生成已完成', partially_succeeded: '部分图片已生成', failed: '快速生成失败',
  cancelled: '快速生成已中止',
}

interface UploadedReference {
  id: string
  file: File
  previewUrl: string
  asset: Asset | null
  uploading: boolean
  error: string
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

export default function QuickListingGenerationPage() {
  const { quickSessionId = '' } = useParams<{ quickSessionId?: string }>()
  const navigate = useNavigate()
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [categoryId, setCategoryId] = useState('')
  const [options, setOptions] = useState<QuickListingOptions | null>(null)
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [includeVariations, setIncludeVariations] = useState(false)
  const [references, setReferences] = useState<UploadedReference[]>([])
  const [status, setStatus] = useState<QuickListingStatus | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    void listProductCategories().then((items) => {
      if (!active) return
      setCategories(items)
      if (!quickSessionId && items.length === 1) setCategoryId(items[0].id)
    }).catch((reason) => { if (active) setError(errorText(reason)) })
    return () => { active = false }
  }, [quickSessionId])

  useEffect(() => {
    if (!categoryId || quickSessionId) { setOptions(null); setSelectedTypes([]); return }
    let active = true
    setError(''); setBusy('options')
    void getQuickListingOptions(categoryId).then((value) => {
      if (!active) return
      setOptions(value); setSelectedTypes(value.default_image_types); setIncludeVariations(false)
    }).catch((reason) => {
      if (!active) return
      setOptions(null); setSelectedTypes([]); setError(errorText(reason))
    }).finally(() => { if (active) setBusy('') })
    return () => { active = false }
  }, [categoryId, quickSessionId])

  useEffect(() => {
    if (!quickSessionId) return
    let active = true
    let timer = 0
    const poll = async () => {
      try {
        const value = await getQuickListingStatus(quickSessionId)
        if (!active) return
        setStatus(value); setError(value.error_message || '')
        if (value.task_group_id && value.target_url) {
          navigate(value.target_url, { replace: true })
          return
        }
        if (value.stage !== 'failed') timer = window.setTimeout(() => { void poll() }, 1500)
      } catch (reason) {
        if (!active) return
        setError(errorText(reason)); timer = window.setTimeout(() => { void poll() }, 2500)
      }
    }
    void poll()
    return () => { active = false; window.clearTimeout(timer) }
  }, [navigate, quickSessionId])

  const assets = useMemo(() => references.flatMap((item) => item.asset ? [item.asset] : []), [references])
  const uploadsPending = references.some((item) => item.uploading)

  const uploadFiles = async (files: FileList | File[] | null) => {
    if (!files?.length) return
    const room = Math.max(0, 10 - references.length)
    const additions = Array.from(files).filter((file) => file.type.startsWith('image/')).slice(0, room).map((file) => ({
      id: randomUuid(), file, previewUrl: URL.createObjectURL(file), asset: null, uploading: true, error: '',
    }))
    setReferences((current) => [...current, ...additions])
    await Promise.all(additions.map(async (item) => {
      try {
        const asset = await uploadAsset(item.file, 'product_reference')
        setReferences((current) => current.map((value) => value.id === item.id ? { ...value, asset, uploading: false } : value))
      } catch (reason) {
        setReferences((current) => current.map((value) => value.id === item.id ? { ...value, uploading: false, error: errorText(reason) } : value))
      }
    }))
  }

  const productPasteZoneProps = useImagePaste({
    disabled: references.length >= 10 || uploadsPending,
    maxFiles: Math.max(0, 10 - references.length),
    onPasteFiles: uploadFiles,
  })

  const removeReference = async (item: UploadedReference) => {
    if (item.asset) await removeAsset(item.asset.id).catch(() => undefined)
    URL.revokeObjectURL(item.previewUrl)
    setReferences((current) => current.filter((value) => value.id !== item.id))
  }

  const submit = async () => {
    if (!assets.length || !categoryId || !options || !selectedTypes.length) return
    setBusy('submit'); setError('')
    try {
      const value = await startQuickListingGeneration({
        product_image_asset_ids: assets.map((item) => item.id),
        primary_asset_id: assets[0].id,
        selected_category_id: categoryId,
        selected_image_types: selectedTypes,
        idempotency_key: `listing-quick:${randomUuid()}`,
        concurrency: Math.min(3, selectedTypes.length),
        size: '2048x2048', aspect_ratio: '1:1', requested_width: 2048, requested_height: 2048,
        quality: 'high', output_format: 'png',
        include_default_variations: includeVariations,
      })
      navigate(`/workspaces/listing/quick/${value.session_id}`, { replace: true })
    } catch (reason) {
      setError(errorText(reason)); setBusy('')
    }
  }

  if (quickSessionId) {
    return <div className="mx-auto max-w-4xl space-y-5 pb-10">
      <header className={panel}><div className="flex items-start justify-between gap-4"><div><div className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-600">Listing 快速模式</div><h1 className="mt-2 text-2xl font-bold dark:text-white">正在自动完成 Listing 与图片生成</h1><p className="mt-2 text-sm text-gray-500">页面可以关闭，服务端会继续分析、确认、创建任务组并进入生成队列。</p></div><Link className={button} to="/workspaces/listing">返回标准模式</Link></div></header>
      <section className={panel}><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50 text-lg text-blue-700">✨</span><div><h2 className="font-bold dark:text-white">{stageLabels[status?.stage || 'analyzing'] || status?.stage || '正在准备'}</h2><p className="mt-1 text-xs text-gray-500">{status ? `${status.category_name} · ${status.skill_name} · Skill V${status.skill_version_number || '-'}` : '正在读取任务状态…'}</p></div></div><div className="mt-5 h-2 overflow-hidden rounded-full bg-gray-100"><div className={`h-full rounded-full bg-blue-600 ${status?.stage === 'failed' ? 'w-full bg-red-500' : 'w-2/3 animate-pulse'}`} /></div>{status?.listing_version_number && <div className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-700">中英文 Listing V{status.listing_version_number} 已自动保存，正在创建图片任务。</div>}{error && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div>}{status?.stage === 'failed' && <div className="mt-4 flex gap-2"><Link className={button} to={`/listing-workbench/${quickSessionId}`}>进入标准模式检查和继续编辑</Link><Link className={primary} to="/workspaces/listing/quick">重新快速生成</Link></div>}</section>
    </div>
  }

  return <div className="mx-auto max-w-5xl space-y-5 pb-10">
    <header className="overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-r from-blue-600 to-indigo-600 p-6 text-white shadow-sm"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-100">Listing 快速模式</div><h1 className="mt-2 text-2xl font-bold">上传、选品类，一键生成 Listing 图片</h1><p className="mt-2 max-w-2xl text-sm text-blue-50">直接使用该品类默认已发布 Skill，自动完成商品分析、中英文 Listing、图片提示词和独立任务组。</p></div><Link to="/workspaces/listing" className="rounded-xl border border-white/30 bg-white/10 px-4 py-2.5 text-sm font-semibold text-white">切换到标准模式</Link></div></header>
    <section {...productPasteZoneProps} className={`${panel} outline-none focus:ring-2 focus:ring-blue-500/20`}><h2 className="font-bold dark:text-white">1. 上传产品图</h2><p className="mt-1 text-xs text-gray-500">支持 1–10 张，第一张作为主产品图；点击本卡片后可 Ctrl/⌘+V 粘贴。</p><label className="mt-4 flex cursor-pointer justify-center rounded-xl border border-dashed border-blue-300 bg-blue-50/50 p-6 text-sm font-semibold text-blue-700"><span>{uploadsPending ? '正在上传…' : '选择文件或粘贴产品图片'}</span><input className="hidden" type="file" accept="image/*" multiple onChange={(event) => { void uploadFiles(event.target.files); event.currentTarget.value = '' }} /></label>{references.length > 0 && <div className="mt-4 grid gap-3 grid-cols-2 sm:grid-cols-4 lg:grid-cols-5">{references.map((item, index) => <article key={item.id} className="overflow-hidden rounded-xl border border-gray-200"><div className="relative"><img src={item.previewUrl} alt={item.file.name} className="aspect-square w-full object-contain bg-gray-50" /><span className="absolute left-2 top-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white">{index === 0 ? '主图' : `参考 ${index + 1}`}</span><button type="button" className="absolute right-2 top-2 rounded bg-black/60 px-2 py-1 text-[10px] text-white" onClick={() => void removeReference(item)}>删除</button></div><div className="truncate p-2 text-xs">{item.error || (item.uploading ? '上传中…' : item.file.name)}</div></article>)}</div>}</section>
    <section className={panel}><h2 className="font-bold dark:text-white">2. 选择品类和默认 Skill</h2><select aria-label="产品品类" className={`${input} mt-4`} value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="">请选择品类</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.category_name}</option>)}</select>{busy === 'options' && <p className="mt-3 text-sm text-gray-500">正在读取默认 Skill…</p>}{options && <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"><div className="font-bold">当前默认 Skill：{options.skill_name}</div><div className="mt-1 text-xs">已发布版本 V{options.skill_version_number} · 本次会固定使用该版本快照</div></div>}{error && !options && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div>}</section>
    <section className={panel}><h2 className="font-bold dark:text-white">3. 选择生成内容</h2><p className="mt-1 text-xs text-gray-500">选项直接来自默认已发布 Skill，不使用前端硬编码业务规则。</p><div className="mt-4 flex flex-wrap gap-2">{options?.default_image_types.map((imageType) => <label key={imageType} className={`cursor-pointer rounded-xl border px-3 py-2 text-sm ${selectedTypes.includes(imageType) ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600'}`}><input className="mr-2" type="checkbox" checked={selectedTypes.includes(imageType)} onChange={(event) => setSelectedTypes((current) => event.target.checked ? [...current, imageType] : current.filter((item) => item !== imageType))} />{imageTypeLabels[imageType] || imageType}</label>)}</div>{Boolean(options?.default_variation_plan_count) && <label className={`mt-4 flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${includeVariations ? 'border-violet-400 bg-violet-50' : 'border-gray-200'}`}><input className="mt-1" type="checkbox" checked={includeVariations} onChange={(event) => setIncludeVariations(event.target.checked)} /><span><span className="font-bold text-violet-800">同时启用 Skill 默认智能图片裂变</span><span className="mt-1 block text-xs text-gray-500">{options?.default_variation_plan_count} 个默认方案，共 {options?.default_variation_image_count} 张；会创建独立裂变任务组。</span></span></label>}</section>
    <section className={panel}><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-bold dark:text-white">一键快速生成</h2><p className="mt-1 text-xs text-gray-500">将生成 {selectedTypes.length} 张 Listing 图片{includeVariations ? `，并额外提交 ${options?.default_variation_image_count || 0} 张智能裂变图` : ''}；每次提交创建独立任务组。</p></div><button className={primary} disabled={!assets.length || uploadsPending || !options || !selectedTypes.length || busy === 'submit'} onClick={() => void submit()}>{busy === 'submit' ? '正在提交…' : '一键快速生成'}</button></div>{error && options && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</div>}</section>
  </div>
}
