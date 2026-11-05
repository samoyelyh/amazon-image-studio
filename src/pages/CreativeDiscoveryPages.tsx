import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { CloseIcon, DownloadIcon, ExternalLinkIcon, FavoriteIcon, PhotoIcon, PlusIcon } from '../components/icons'
import { ArrowUpIcon, SearchIcon, SparklesIcon } from '../components/agent-control/AgentControlIcons'
import { inspirationAsset, inspirationItems, type InspirationItem } from '../lib/creationInspiration'
import { submitCreativeTool } from '../lib/creativeToolApi'

const agentLink = (prompt: string) => `/workspaces/agent-control?prompt=${encodeURIComponent(prompt)}`

function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <header><p className="text-xs font-medium tracking-[0.14em] text-gray-500">{eyebrow}</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white">{title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">{description}</p></header>
}

const skills = [
  { name: 'Amazon 商品主图', category: '电商', image: 'creative-assets/product-main.png', description: '从商品参考图生成主体清晰、卖点明确的电商主图。', prompt: '使用 Amazon 商品主图 Skill，分析我上传的商品并制作一张高转化主图。' },
  { name: 'Amazon A+ 内容页', category: '电商', image: 'creative-assets/aplus-visual.png', description: '规划 A+ 内容结构，保持品牌视觉与模块风格统一。', prompt: '使用 Amazon A+ 内容 Skill，为我的商品规划一套 A+ 图片模块。' },
  { name: '服装套图生产', category: '电商', image: 'creative-assets/batch-tryon.png', description: '保持服装细节，将模板与服装组合为统一套图。', prompt: '使用服装套图 Skill，理解我的模板和服装素材，准备批量套图生产。' },
  { name: '品牌视觉系统', category: '品牌', image: 'style-presets/premium-contrast.png', description: '建立统一配色、材质、光影和构图方向。', prompt: '使用品牌视觉系统 Skill，为我的产品设计一套统一的品牌视觉方向。' },
  { name: '社媒营销图组', category: '营销', image: 'style-presets/bright-retail.png', description: '把商品卖点转化为适合社媒传播的营销图片。', prompt: '使用社媒营销 Skill，为我的商品创作一组社交媒体营销图片。' },
  { name: '产品创意海报', category: '创意', image: 'creative-assets/abstract-creative.png', description: '用艺术构图和视觉创意提升产品表现力。', prompt: '使用产品创意海报 Skill，为我的商品创作一张有视觉冲击力的海报。' },
] as const

type Skill = (typeof skills)[number]

export function CreativeSkillsPage() {
  const [category, setCategory] = useState('全部')
  const [selected, setSelected] = useState<Skill | null>(null)
  const visible = skills.filter((skill) => category === '全部' || skill.category === category)
  return <div className="mx-auto max-w-[1500px] pb-10 pt-7 sm:pt-9">
    <PageHeading eyebrow="SKILL LIBRARY" title="用 Skill 快速开始" description="把成熟的电商创作流程交给 Agent。选择 Skill 后仍可修改需求、素材和生成方式。" />
    <div className="mt-7 flex flex-wrap gap-2">{['全部', '电商', '品牌', '营销', '创意'].map((item) => <button key={item} onClick={() => setCategory(item)} className={`rounded-full px-4 py-2 text-xs transition ${category === item ? 'bg-white text-gray-950' : 'border border-white/10 text-gray-500 hover:text-white'}`}>{item}</button>)}</div>
    <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{visible.map((skill) => <button key={skill.name} onClick={() => setSelected(skill)} className="lovart-image-card group text-left">
      <div className="aspect-[1.55] overflow-hidden bg-[#eeeeeb]"><img src={inspirationAsset(skill.image)} alt={`${skill.name}示例`} className="h-full w-full object-cover" /></div>
      <div className="p-4"><div className="flex items-center justify-between"><span className="text-[10px] text-gray-500">{skill.category} SKILL</span><ArrowUpIcon className="h-4 w-4 rotate-45 text-gray-600 group-hover:text-white" /></div><h2 className="mt-2 text-sm font-semibold text-gray-100">{skill.name}</h2><p className="mt-1.5 text-xs leading-5 text-gray-500">{skill.description}</p></div>
    </button>)}</div>
    {selected && <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={() => setSelected(null)}><aside className="absolute inset-y-0 right-0 w-full max-w-md overflow-y-auto border-l border-white/10 bg-[#1b1b1b] p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
      <div className="flex justify-end"><button aria-label="关闭 Skill 详情" onClick={() => setSelected(null)} className="rounded-full p-2 text-gray-400 hover:bg-white/[0.06]"><CloseIcon className="h-5 w-5" /></button></div>
      <img src={inspirationAsset(selected.image)} alt={`${selected.name}示例`} className="mt-2 aspect-[1.35] w-full rounded-2xl object-cover" />
      <p className="mt-6 text-xs text-gray-500">{selected.category} SKILL</p><h2 className="mt-2 text-2xl font-semibold">{selected.name}</h2><p className="mt-3 text-sm leading-6 text-gray-400">{selected.description}</p>
      <div className="mt-6 rounded-2xl bg-white/[0.04] p-4"><h3 className="text-xs font-semibold">Agent 将协助完成</h3><ul className="mt-3 space-y-2 text-xs leading-5 text-gray-500"><li>理解商品、参考图与创作目标</li><li>按现有能力选择图片生成或专业工作台</li><li>返回可继续编辑、查看和下载的结果</li></ul></div>
      <Link to={agentLink(selected.prompt)} className="mt-6 flex min-h-11 items-center justify-center gap-2 rounded-full bg-white text-sm font-semibold text-gray-950"><SparklesIcon className="h-4 w-4" />在 AI 总控中使用</Link>
    </aside></div>}
  </div>
}

const tools = [
  { name: '去背景', description: '保留主体，输出透明背景素材', image: 'creative-assets/product-main.png', mode: 'existing', href: '/material-extract', capability: 'material_extract' },
  { name: '精准编辑', description: '用 Mask 控制局部替换与融合', image: 'creative-assets/image-editing.png', mode: 'existing', href: '/workspaces/print-design', capability: 'mask_edit' },
  { name: '产品样机', description: '把产品融入真实的展示样机', image: 'creative-assets/scene-creative.png', mode: 'agent', href: '', capability: 'product_mockup' },
  { name: '扩展画面', description: '延展图片边界并补充自然场景', image: 'creative-assets/aplus-visual.png', mode: 'agent', href: '', capability: 'image_outpaint' },
  { name: '图片放大', description: '提升分辨率并保留产品细节', image: 'style-presets/clean-tech.png', mode: 'placeholder', href: '', capability: 'image_upscale' },
  { name: '延长视频', description: '为现有视频延展自然后续画面', image: 'creative-assets/variation-portrait.png', mode: 'placeholder', href: '', capability: 'video_extend' },
] as const

type Tool = (typeof tools)[number]

function ToolDialog({ tool, onClose }: { tool: Tool; onClose: () => void }) {
  const [fileName, setFileName] = useState('')
  const [instruction, setInstruction] = useState('')
  const [message, setMessage] = useState('')
  const prompt = `使用${tool.name}工具处理我上传的图片。${instruction}`
  const submit = async () => {
    try { await submitCreativeTool({ capability: tool.capability, fileName, instruction }) }
    catch (error) { setMessage(error instanceof Error ? error.message : '工具接口尚未接入') }
  }
  return <div role="dialog" aria-label={`${tool.name}工具`} className="fixed inset-0 z-50 flex items-end justify-center bg-black/65 backdrop-blur-sm sm:items-center sm:p-6" onClick={onClose}><section className="max-h-[92%] w-full max-w-xl overflow-y-auto rounded-t-[24px] border border-white/10 bg-[#1b1b1b] p-5 sm:rounded-[24px] sm:p-6" onClick={(event) => event.stopPropagation()}>
    <div className="flex items-start justify-between"><div><p className="text-xs text-gray-500">AI 智能工具</p><h2 className="mt-1 text-2xl font-semibold">{tool.name}</h2><p className="mt-2 text-sm text-gray-500">{tool.description}</p></div><button aria-label="关闭工具" onClick={onClose} className="rounded-full p-2 text-gray-400 hover:bg-white/[0.06]"><CloseIcon className="h-5 w-5" /></button></div>
    <label className="mt-6 flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-white/15 bg-white/[0.025] p-6 text-center"><PhotoIcon className="h-7 w-7 text-gray-500" /><span className="mt-3 text-sm text-gray-300">{fileName || '选择需要处理的图片或视频'}</span><span className="mt-1 text-xs text-gray-600">文件仅在当前页面选择，不会自动上传</span><input type="file" className="hidden" accept={tool.capability === 'video_extend' ? 'video/*' : 'image/*'} onChange={(event) => setFileName(event.target.files?.[0]?.name || '')} /></label>
    <label className="mt-5 block text-xs font-medium text-gray-400">处理要求<textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={3} placeholder="描述希望保留、修改或延展的内容" className="mt-2 w-full resize-none rounded-xl border border-white/10 bg-[#151515] p-3 text-sm leading-6 text-white outline-none placeholder:text-gray-600" /></label>
    {tool.mode === 'placeholder' ? <div className="mt-5 rounded-xl border border-amber-400/15 bg-amber-400/[0.06] p-3 text-xs leading-5 text-amber-200/80">该工具的界面与参数区已预留，等待 Codex 接入 `{tool.capability}` 能力后开放执行。</div> : <div className="mt-5 rounded-xl bg-white/[0.04] p-3 text-xs leading-5 text-gray-500">将复用现有上传、任务、结果归属和下载流程。</div>}
    {tool.mode === 'existing' && <Link to={tool.href} className="mt-5 flex min-h-11 items-center justify-center gap-2 rounded-full bg-white text-sm font-semibold text-gray-950">进入现有工作台<ExternalLinkIcon className="h-4 w-4" /></Link>}
    {tool.mode === 'agent' && <Link to={agentLink(prompt)} className="mt-5 flex min-h-11 items-center justify-center gap-2 rounded-full bg-white text-sm font-semibold text-gray-950">交给 Agent 处理<SparklesIcon className="h-4 w-4" /></Link>}
    {tool.mode === 'placeholder' && <button onClick={() => void submit()} className="mt-5 min-h-11 w-full rounded-full bg-white/20 text-sm font-semibold text-gray-400">开始处理 · 验证接口状态</button>}
    {message && <p role="status" className="mt-3 text-center text-xs text-amber-300">{message}</p>}
  </section></div>
}

export function AIToolsPage() {
  const [selected, setSelected] = useState<Tool | null>(null)
  return <div className="mx-auto max-w-[1500px] pb-10 pt-7 sm:pt-9"><PageHeading eyebrow="AI TOOLS" title="实用工具" description="用更直接的方式处理图片。已有能力现在即可使用，新能力会在接口接入后开放在同一入口。" />
    <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{tools.map((tool) => <button key={tool.name} data-capability={tool.capability} onClick={() => setSelected(tool)} className="lovart-image-card group text-left"><div className="aspect-[1.55] overflow-hidden bg-[#eeeeeb]"><img src={inspirationAsset(tool.image)} alt={`${tool.name}示例`} className="h-full w-full object-cover" /></div><div className="flex items-center justify-between p-4"><div><h2 className="text-sm font-semibold">{tool.name}</h2><p className="mt-1 text-xs text-gray-500">{tool.description}</p></div><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] ${tool.mode === 'placeholder' ? 'bg-white/[0.05] text-gray-500' : 'bg-emerald-400/10 text-emerald-300'}`}>{tool.mode === 'placeholder' ? '待接入' : '可使用'}</span></div></button>)}</div>
    {selected && <ToolDialog tool={selected} onClose={() => setSelected(null)} />}
  </div>
}

function InspirationCard({ item, favorite, onFavorite, onOpen }: { item: InspirationItem; favorite: boolean; onFavorite: () => void; onOpen: () => void }) {
  return <article className="lovart-image-card group relative break-inside-avoid"><button onClick={onOpen} className="block w-full text-left"><img src={inspirationAsset(item.path)} alt={item.title} className="max-h-[430px] min-h-40 w-full bg-[#242424] object-cover" /><div className="p-3.5"><p className="text-xs font-medium text-gray-200">{item.title}</p><p className="mt-1 text-[10px] text-gray-500">{item.category}</p></div></button><button aria-label={favorite ? `取消收藏 ${item.title}` : `收藏 ${item.title}`} onClick={onFavorite} className={`absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full backdrop-blur ${favorite ? 'bg-white text-gray-950' : 'bg-black/45 text-white'}`}><FavoriteIcon filled={favorite} className="h-4 w-4" /></button></article>
}

export function InspirationPage() {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('全部')
  const [favoritesOnly, setFavoritesOnly] = useState(false)
  const [favorites, setFavorites] = useState<string[]>(() => { try { return JSON.parse(localStorage.getItem('creation-inspiration-favorites') || '[]') as string[] } catch { return [] } })
  const [selected, setSelected] = useState<InspirationItem | null>(null)
  const [sourceMessage, setSourceMessage] = useState('')
  const toggleFavorite = (id: string) => setFavorites((current) => {
    const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    localStorage.setItem('creation-inspiration-favorites', JSON.stringify(next))
    return next
  })
  const visible = inspirationItems.filter((item) => (category === '全部' || item.category === category) && (!favoritesOnly || favorites.includes(item.id)) && `${item.title}${item.prompt}`.toLowerCase().includes(search.toLowerCase()))
  return <div className="mx-auto max-w-[1500px] pb-10 pt-7 sm:pt-9"><PageHeading eyebrow="INSPIRATION" title="灵感采集" description="收藏喜欢的视觉方向，并把它变成自己的创作起点。收藏仅保存在当前浏览器。" />
    <div className="mt-5 flex flex-wrap items-center gap-2 border-b border-white/[0.07] pb-4 text-xs"><span className="rounded-full bg-white px-3 py-1.5 text-gray-950">探索</span><Link to="/assets" className="px-3 py-1.5 text-gray-500 hover:text-white">我的素材</Link><button onClick={() => setFavoritesOnly(true)} className="px-3 py-1.5 text-gray-500 hover:text-white">灵感采集</button><button onClick={() => setSourceMessage('Pinterest 账号连接与灵感导入接口待 Codex 接入，当前不会读取外部账号。')} className="px-3 py-1.5 text-gray-500 hover:text-white">Pinterest</button></div>{sourceMessage && <p role="status" className="mt-3 text-xs text-gray-500">{sourceMessage}</p>}
    <div className="mt-7 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between"><div className="flex flex-wrap gap-2">{['全部', '电商', '品牌', '创意', '人物'].map((item) => <button key={item} onClick={() => setCategory(item)} className={`rounded-full px-3.5 py-2 text-xs ${category === item ? 'bg-white text-gray-950' : 'text-gray-500 hover:bg-white/[0.06]'}`}>{item}</button>)}<button onClick={() => setFavoritesOnly(!favoritesOnly)} className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs ${favoritesOnly ? 'bg-white text-gray-950' : 'text-gray-500'}`}><FavoriteIcon filled={favoritesOnly} className="h-3.5 w-3.5" />已收藏</button></div><label className="flex h-10 items-center gap-2 rounded-full border border-white/10 bg-[#1b1b1b] px-3.5 lg:w-72"><SearchIcon className="h-4 w-4 text-gray-500" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索灵感" className="min-w-0 flex-1 bg-transparent text-xs outline-none" /></label></div>
    {!visible.length && <div className="mt-6 rounded-2xl border border-dashed border-white/10 py-20 text-center text-sm text-gray-500">没有匹配的灵感，试试其他分类或搜索词。</div>}
    <div className="mt-6 columns-2 gap-4 lg:columns-3 2xl:columns-4 [&>article]:mb-4">{visible.map((item) => <InspirationCard key={item.id} item={item} favorite={favorites.includes(item.id)} onFavorite={() => toggleFavorite(item.id)} onOpen={() => setSelected(item)} />)}</div>
    {selected && <div role="dialog" aria-label="灵感详情" className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm" onClick={() => setSelected(null)}><section className="grid max-h-[92%] w-full max-w-4xl overflow-y-auto rounded-[24px] border border-white/10 bg-[#1b1b1b] md:grid-cols-[1.3fr_1fr]" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-center bg-[#242424] p-4"><img src={inspirationAsset(selected.path)} alt={selected.title} className="max-h-[75vh] max-w-full object-contain" /></div><div className="p-6"><div className="flex justify-end"><button aria-label="关闭灵感详情" onClick={() => setSelected(null)} className="rounded-full p-2 text-gray-400 hover:bg-white/[0.06]"><CloseIcon className="h-5 w-5" /></button></div><p className="text-xs text-gray-500">{selected.category}灵感</p><h2 className="mt-2 text-2xl font-semibold">{selected.title}</h2><p className="mt-4 text-sm leading-6 text-gray-400">{selected.prompt}</p><button onClick={() => toggleFavorite(selected.id)} className="mt-6 inline-flex min-h-10 items-center gap-2 rounded-full border border-white/10 px-4 text-xs"><FavoriteIcon filled={favorites.includes(selected.id)} className="h-4 w-4" />{favorites.includes(selected.id) ? '取消收藏' : '收藏灵感'}</button><Link to={agentLink(selected.prompt)} className="mt-4 flex min-h-11 items-center justify-center gap-2 rounded-full bg-white text-sm font-semibold text-gray-950">用此灵感创作<SparklesIcon className="h-4 w-4" /></Link><a href={inspirationAsset(selected.path)} download className="mt-3 flex min-h-10 items-center justify-center gap-2 text-xs text-gray-500"><DownloadIcon className="h-4 w-4" />下载示例图</a></div></section></div>}
  </div>
}

export function DesignBriefPage() {
  const [form, setForm] = useState({ name: '', objective: '电商商品图', style: '简约高级', size: '1:1', notes: '', reference: '' })
  const [message, setMessage] = useState('')
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }))
  const saveDraft = (event: FormEvent) => {
    event.preventDefault()
    localStorage.setItem('creation-design-brief-draft', JSON.stringify(form))
    setMessage('委托草稿已保存在当前浏览器。在线提交与团队协作接口待 Codex 接入。')
  }
  return <div className="mx-auto max-w-5xl pb-10 pt-7 sm:pt-9"><PageHeading eyebrow="DESIGN BRIEF" title="设计委托" description="把复杂的视觉需求整理成清晰brief。当前先提供需求整理与本地草稿，后续接入团队审核和协作流程。" />
    <form onSubmit={saveDraft} className="mt-7 grid gap-5 lg:grid-cols-[1fr_320px]"><section className="rounded-[22px] border border-white/[0.08] bg-[#1b1b1b] p-5 sm:p-6"><h2 className="text-sm font-semibold">委托信息</h2><label className="mt-5 block text-xs text-gray-400">委托名称<input required value={form.name} onChange={(event) => update('name', event.target.value)} placeholder="例如：春季新品电商视觉" className="mt-2 h-11 w-full rounded-xl border border-white/10 bg-[#151515] px-3 text-sm outline-none" /></label><div className="mt-4 grid gap-4 sm:grid-cols-2"><label className="text-xs text-gray-400">设计目标<select value={form.objective} onChange={(event) => update('objective', event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-white/10 bg-[#151515] px-3 text-sm"><option>电商商品图</option><option>品牌视觉</option><option>社媒营销</option><option>A+ 内容</option><option>印花与样机</option></select></label><label className="text-xs text-gray-400">期望风格<select value={form.style} onChange={(event) => update('style', event.target.value)} className="mt-2 h-11 w-full rounded-xl border border-white/10 bg-[#151515] px-3 text-sm"><option>简约高级</option><option>自然暖调</option><option>明亮零售</option><option>高级对比</option><option>创意艺术</option></select></label></div><label className="mt-4 block text-xs text-gray-400">详细需求<textarea required value={form.notes} onChange={(event) => update('notes', event.target.value)} rows={7} placeholder="说明产品、目标用户、必须保留的元素、文案和交付要求" className="mt-2 w-full resize-none rounded-xl border border-white/10 bg-[#151515] p-3 text-sm leading-6 outline-none" /></label><label className="mt-4 flex cursor-pointer items-center justify-between rounded-xl border border-dashed border-white/15 p-4 text-xs text-gray-500"><span>{form.reference || '选择参考文件（仅在本地记录文件名）'}</span><PlusIcon className="h-4 w-4" /><input type="file" className="hidden" accept="image/*,.pdf" onChange={(event) => update('reference', event.target.files?.[0]?.name || '')} /></label></section>
      <aside className="space-y-5"><section className="rounded-[22px] border border-white/[0.08] bg-[#1b1b1b] p-5"><h2 className="text-sm font-semibold">画布与交付</h2><p className="mt-2 text-xs text-gray-500">选择主要输出比例，后续可继续补充。</p><div className="mt-4 grid grid-cols-3 gap-2">{['1:1', '3:4', '4:3', '16:9', '9:16', '2:3'].map((size) => <button type="button" key={size} onClick={() => update('size', size)} className={`rounded-xl border px-2 py-3 text-xs ${form.size === size ? 'border-white bg-white text-gray-950' : 'border-white/10 text-gray-500'}`}>{size}</button>)}</div></section><button type="submit" className="min-h-11 w-full rounded-full bg-white text-sm font-semibold text-gray-950">保存委托草稿</button>{message && <p role="status" className="rounded-xl bg-white/[0.04] p-3 text-xs leading-5 text-gray-400">{message}</p>}</aside>
    </form>
  </div>
}
