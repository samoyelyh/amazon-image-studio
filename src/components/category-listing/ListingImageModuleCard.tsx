import ImagePromptEditorCard from './ImagePromptEditorCard'
import AuthenticatedImage from './AuthenticatedImage'
import type { Asset } from '../../lib/contentApi'
import type { ImagePromptItem, ListingImageModule } from '../../lib/listingWorkflowApi'
import { useStore } from '../../store'

const button = 'rounded-xl border border-gray-200 px-3 py-2 text-sm font-semibold disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50'
const field = 'w-full rounded-lg border border-gray-200 bg-white px-2.5 py-2 text-xs dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'

function render(value: unknown) {
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value && typeof value === 'object') return Object.values(value).join('、')
  return String(value ?? '')
}

export default function ListingImageModuleCard({
  index, module, selected, projectId, sessionId, categoryId, referenceAssets,
  basePrompt, promptItem, promptStatus, attributeOverrides, busy,
  onToggle, onAttributeChange, onBuild, onGenerate, onPromptUpdate, onPromptStatusChange,
}: {
  index: number; module: ListingImageModule; selected: boolean
  projectId: string; sessionId: string; categoryId: string; referenceAssets: Asset[]
  basePrompt: string; promptItem?: ImagePromptItem; promptStatus?: string
  attributeOverrides: Record<string, unknown>; busy: boolean
  onToggle: (selected: boolean) => void
  onAttributeChange: (code: string, value: string) => void
  onBuild: () => void; onGenerate: () => void
  onPromptUpdate: (item: ImagePromptItem) => void
  onPromptStatusChange: (code: string, status: string) => void
}) {
  const showToast = useStore((state) => state.showToast)
  const copyPrompt = async () => {
    const value = promptItem?.optimized_english_prompt || basePrompt
    if (!value.trim()) return
    await navigator.clipboard.writeText(value)
    showToast('Prompt 已复制。', 'success')
  }
  return <article className={`overflow-hidden rounded-2xl border bg-white shadow-sm transition dark:bg-gray-900 ${selected ? 'border-blue-300 ring-1 ring-blue-100 dark:border-blue-500/40' : 'border-gray-200 opacity-80 dark:border-white/[0.08]'}`}>
    <header className="border-b border-gray-100 p-5 dark:border-white/[0.06]">
      <div className="flex items-start gap-3">
        <input type="checkbox" className="mt-1 h-4 w-4" checked={selected} disabled={!module.available} onChange={(event) => onToggle(event.target.checked)} />
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold text-blue-600">{String(index).padStart(2, '0')}</span><h2 className="font-bold dark:text-white">{module.name}</h2><span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600 dark:bg-white/[0.08] dark:text-gray-300">构图建议 {module.recommended_aspect_ratio}</span><span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">{promptStatus || (basePrompt.trim() ? '基础 Prompt 已就绪' : '未生成 Prompt')}</span></div><p className="mt-1 text-xs leading-5 text-gray-500">{module.objective}</p></div>
      </div>
      {!module.available && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-800">{module.unavailable_reason}</p>}
    </header>
    <div className="space-y-4 p-5">
      <section><div className="text-xs font-bold text-gray-700 dark:text-gray-200">自动推荐内容</div><div className="mt-2 flex flex-wrap gap-1.5">{module.recommendations.map((item) => <span key={item} className="rounded-lg bg-violet-50 px-2 py-1 text-[11px] text-violet-700 dark:bg-violet-500/10 dark:text-violet-200">{item}</span>)}</div></section>
      <details className="rounded-xl border border-gray-200 bg-gray-50/60 p-3 dark:border-white/[0.08] dark:bg-white/[0.02]">
        <summary className="cursor-pointer text-xs font-bold text-gray-700 dark:text-gray-200">本模块使用的数据 · {module.used_attributes.length} 项</summary>
        <p className="mt-2 text-[11px] text-gray-500">这里的修改仅覆盖当前图片项目，不会修改商品主数据。</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">{module.used_attributes.map((item) => <label key={item.code} className="text-[11px] font-semibold text-gray-600 dark:text-gray-300">{item.label}<input className={`${field} mt-1`} value={render(attributeOverrides[item.code] ?? item.value)} placeholder="商品资料未提供，可仅为本次生成补充" onChange={(event) => onAttributeChange(item.code, event.target.value)} /><span className="mt-1 block font-normal text-gray-400">{item.source === 'module_override' || item.code in attributeOverrides ? '本次覆盖' : `产品资料 · ${item.weight === 'high' ? '高权重' : '低权重'}`}</span></label>)}</div>
      </details>
      <section className="rounded-xl bg-blue-50/60 p-3 dark:bg-blue-500/10"><div className="flex items-center justify-between text-xs text-blue-800 dark:text-blue-200"><span className="font-bold">输入参考图</span><span>{referenceAssets.length} 张</span></div><div className="mt-2 flex gap-2 overflow-hidden">{referenceAssets.slice(0, 4).map((asset) => <AuthenticatedImage key={asset.id} url={asset.url} alt={asset.filename} className="h-14 w-14 rounded-lg bg-white object-contain" placeholderClassName="h-14 w-14 rounded-lg" />)}{referenceAssets.length > 4 && <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-white text-xs font-bold text-blue-700">+{referenceAssets.length - 4}</div>}</div></section>
      {selected && <ImagePromptEditorCard projectType="listing_image" projectId={projectId} sessionId={sessionId} categoryId={categoryId} itemCode={module.code} imageType={module.code} label={`${module.name} Prompt`} basePrompt={basePrompt || module.prompt || '请先生成 Prompt'} initialItem={promptItem} onUpdate={onPromptUpdate} onStatusChange={onPromptStatusChange} />}
      <div className="flex flex-wrap justify-end gap-2"><button className={button} disabled={busy} onClick={onBuild}>生成 Prompt</button><button className={button} disabled={!basePrompt.trim()} onClick={() => void copyPrompt()}>复制 Prompt</button><button className={primary} disabled={!selected || busy || !module.available} onClick={onGenerate}>生成图片</button></div>
    </div>
  </article>
}
