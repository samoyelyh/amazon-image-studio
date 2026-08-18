import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import WorkflowSteps from '../components/category-listing/WorkflowSteps'
import { canEnterCategoryOutput } from '../lib/categoryListingRoutes'
import { fetchAssetBlob, getAsset, type Asset } from '../lib/contentApi'
import { confirmListingWorkflowSession, createCategoryOutputProject, getBilingualListingOptimization, getListingOutputOptions, getListingWorkflowSession, optimizeBilingualListing, type ListingOutputOptions, type ListingWorkflowSession } from '../lib/listingWorkflowApi'
import { randomUuid } from '../lib/randomUuid'
import { useStore } from '../store'

const card = 'rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const primary = 'mt-5 w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-50'
function errorText(error: unknown) { return error instanceof Error ? error.message : '请求失败' }
function statusLabel(value: string | null) { return !value ? '未创建' : ({ editing: '编辑中', queued: '生成中', running: '生成中', partially_succeeded: '部分完成', succeeded: '已完成', failed: '生成失败' }[value] || value) }
const localized = (value: string | undefined) => value?.trim() || '暂未生成中文对照'

export default function ListingOutputSelectionPage() {
  const { sessionId = '' } = useParams(); const navigate = useNavigate(); const showToast = useStore((state) => state.showToast)
  const [session, setSession] = useState<ListingWorkflowSession | null>(null); const [options, setOptions] = useState<ListingOutputOptions | null>(null)
  const [mainAsset, setMainAsset] = useState<Asset | null>(null); const [mainPreviewUrl, setMainPreviewUrl] = useState(''); const [busy, setBusy] = useState('')

  useEffect(() => { let objectUrl = ''; void (async () => { try {
    const current = await getListingWorkflowSession(sessionId)
    if (!canEnterCategoryOutput(current)) { showToast('请先完成并确认Listing内容。', 'error'); navigate(`/listing-workbench/${sessionId}`, { replace: true }); return }
    setSession(current); setOptions(await getListingOutputOptions(sessionId))
    if (current.primary_asset_id) { const asset = await getAsset(current.primary_asset_id); setMainAsset(asset); if (asset.url) { objectUrl = URL.createObjectURL(await fetchAssetBlob(asset.url)); setMainPreviewUrl(objectUrl) } }
  } catch (error) { showToast(errorText(error), 'error') } })(); return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) } }, [navigate, sessionId, showToast])

  const enter = async (kind: 'listing-image' | 'a-plus') => { setBusy(kind); try { await createCategoryOutputProject(kind, sessionId); navigate(kind === 'listing-image' ? `/listing-image-workbench/${sessionId}` : `/a-plus-workbench/${sessionId}`) } catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') } }
  const needsChinese = Boolean(options && (!options.listing_snapshot.title.zh?.trim() || options.listing_snapshot.bullet_points.some((item) => !item.zh?.trim())))
  const completeChinese = async () => {
    if (!options) return
    setBusy('complete-chinese')
    try {
      const started = await optimizeBilingualListing(sessionId, {
        direction: 'en_to_zh', listing_content: options.listing_snapshot,
        idempotency_key: `listing-complete-chinese:${randomUuid()}`,
      })
      for (;;) {
        const result = await getBilingualListingOptimization(sessionId, started.job_id)
        if (result.status === 'failed') throw new Error(result.error_message || '中文对照生成失败')
        if (result.status === 'succeeded' && result.listing_content) {
          const confirmed = await confirmListingWorkflowSession(sessionId, { listing_content: result.listing_content })
          setSession(confirmed); setOptions(await getListingOutputOptions(sessionId)); break
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1200))
      }
      showToast('中文对照已生成并保存为新的 Listing 版本。', 'success')
    } catch (error) { showToast(errorText(error), 'error') } finally { setBusy('') }
  }
  if (!session || !options) return <div className={card}>正在加载已确认的 Listing…</div>

  return <div className="pb-10"><WorkflowSteps current={3} sessionId={sessionId} />
    <section className={card}><div className="flex flex-wrap items-center gap-4">
      {mainPreviewUrl ? <img src={mainPreviewUrl} className="h-24 w-24 rounded-xl border object-contain" alt={mainAsset?.filename || '产品主图'} /> : <div className="flex h-24 w-24 items-center justify-center rounded-xl bg-gray-100 text-xs text-gray-500">产品主图</div>}
      <div className="min-w-0 flex-1"><h1 className="truncate text-xl font-bold dark:text-white">{options.listing_snapshot.title.en || '未命名商品'}</h1><div className="mt-2 flex flex-wrap gap-2 text-xs text-gray-500"><span>{options.category_name}</span><span>·</span><span>{options.skill_name}</span><span>·</span><span>Skill V{options.skill_version_number || '-'}</span><span>·</span><span>Listing V{options.listing_version_number}</span><span className="rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700">已确认</span></div></div>
    </div></section>
    <section className={`${card} mt-5`}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-bold dark:text-white">已确认 Listing 中英文对照</h2><p className="mt-1 text-xs text-gray-500">读取当前确认版本 V{options.listing_version_number} 的不可变快照，不会在此页面重新生成或覆盖内容。</p></div>{needsChinese && <button className="rounded-xl border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-700 disabled:opacity-50" disabled={Boolean(busy)} onClick={() => void completeChinese()}>{busy === 'complete-chinese' ? '正在补充…' : '补充生成中文对照'}</button>}</div>
      <div className="mt-5 rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]"><h3 className="font-bold dark:text-white">Listing 标题</h3><div className="mt-3 grid gap-3 lg:grid-cols-2"><div><div className="text-xs font-semibold text-gray-500">英文</div><p className="mt-1 text-sm dark:text-gray-100">{options.listing_snapshot.title.en || '暂未填写英文标题'}</p></div><div><div className="text-xs font-semibold text-gray-500">中文</div><p className="mt-1 text-sm dark:text-gray-100">{localized(options.listing_snapshot.title.zh)}</p></div></div></div>
      <div className="mt-4 space-y-3">{options.listing_snapshot.bullet_points.map((item, index) => <article key={item.id || `bullet-${index + 1}`} className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]"><h3 className="font-bold dark:text-white">卖点 {index + 1}</h3><div className="mt-3 grid gap-3 lg:grid-cols-2"><div><div className="text-xs font-semibold text-gray-500">英文</div><p className="mt-1 text-sm dark:text-gray-100">{item.en || '暂未填写英文卖点'}</p></div><div><div className="text-xs font-semibold text-gray-500">中文</div><p className="mt-1 text-sm dark:text-gray-100">{localized(item.zh)}</p></div></div></article>)}</div>
    </section>
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <section className={card}><div className="text-3xl">🖼️</div><h2 className="mt-3 text-lg font-bold dark:text-white">Listing 图片生成</h2><p className="mt-2 text-sm text-gray-600 dark:text-gray-300">生成主图、模特图、场景图、细节图、卖点图、尺寸图及定制说明图。</p><div className="mt-4 text-xs font-semibold text-gray-500">状态：{statusLabel(options.listing_image_project.status)}{options.listing_image_project.outdated ? ' · 使用旧版Listing' : ''}</div><button className={primary} disabled={Boolean(busy)} onClick={() => void enter('listing-image')}>{busy === 'listing-image' ? '进入中…' : options.listing_image_project.exists ? '继续编辑Listing图片' : '进入Listing图片工作台'}</button></section>
      <section className={card}><div className="text-3xl">✨</div><h2 className="mt-3 text-lg font-bold dark:text-white">A+ 图片生成</h2><p className="mt-2 text-sm text-gray-600 dark:text-gray-300">根据已确认的Listing内容，制作品牌展示、产品卖点、细节说明及场景模块。</p><div className="mt-4 text-xs font-semibold text-gray-500">状态：{statusLabel(options.a_plus_project.status)}{options.a_plus_project.outdated ? ' · 使用旧版Listing' : ''}</div><button className={primary} disabled={Boolean(busy)} onClick={() => void enter('a-plus')}>{busy === 'a-plus' ? '进入中…' : options.a_plus_project.exists ? '继续编辑A+内容' : '进入A+图片工作台'}</button></section>
    </div>
  </div>
}
