import { Link } from 'react-router-dom'
import { runtimeConfig } from '../app/runtimeConfig'
import { appRoutes } from '../app/routes'
import { ArrowUpIcon, SparklesIcon } from '../components/agent-control/AgentControlIcons'

const pageCopy = {
  tasks: ['任务中心', '查看图片任务、生成进度和结果下载。'],
  assets: ['素材中心', '管理团队生成素材、图片归档与项目复用。'],
  projects: ['项目系统', '管理多人项目草稿、不可变版本和素材关联。'],
  history: ['生成历史', '浏览和下载团队历史生成结果。'],
  quota: ['额度中心', '查看团队额度账户、流水和费用信息。'],
  profile: ['个人中心', '管理账号资料、团队与角色权限。'],
  admin: ['管理后台', '管理用户、团队、套餐、额度、资源与审计信息。'],
} as const

const workspaceCards = [
  { title: '商品与附图', description: '主图、附图策划与生成', path: appRoutes.attachmentImages, image: 'product-main.png', contain: true },
  { title: '批量套图', description: '固定模特模板，批量替换服装', path: appRoutes.batchTryOn, image: 'batch-tryon.png', contain: true },
  { title: '自由图片裂变', description: '从一张参考图延展更多创意', path: appRoutes.smartImageVariationHub, image: 'variation-portrait.png', contain: false },
  { title: 'A+ 内容设计', description: 'A+ 模块编排、文案与生成', path: appRoutes.aplus, image: 'aplus-visual.png', contain: false },
  { title: '素材提取', description: '涂抹目标，提取透明高清素材', path: appRoutes.materialExtract, image: 'image-editing.png', contain: false },
  { title: '印花编辑', description: '印花图层、Mask 与 AI 局部融合', path: appRoutes.printDesign, image: 'abstract-creative.png', contain: false },
] as const

export function DashboardPage() {
  return <div className="mx-auto max-w-[1400px] pb-8 pt-6 sm:pt-8">
    <section className="relative overflow-hidden rounded-[24px] border border-white/[0.08] bg-[#1b1b1b]">
      <div className="relative z-10 max-w-2xl px-6 py-10 sm:px-10 sm:py-14">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-3 py-1.5 text-xs text-gray-300 backdrop-blur"><SparklesIcon className="h-4 w-4" />AI 电商创作助手</div>
        <h1 className="mt-5 text-3xl font-semibold tracking-[-0.04em] text-white sm:text-4xl">今天想创作什么图片？</h1>
        <p className="mt-3 max-w-xl text-sm leading-6 text-gray-400">从一个想法开始，让 Agent 帮你理解素材、调度工具并完成电商图片生产。</p>
        <Link to={appRoutes.agentControl} className="mt-7 inline-flex min-h-11 items-center gap-2 rounded-full bg-white px-5 text-sm font-semibold text-gray-950 transition hover:bg-gray-200">开始创作<ArrowUpIcon className="h-4 w-4 rotate-45" /></Link>
      </div>
      <img src={`${import.meta.env.BASE_URL}creative-assets/scene-creative.png`} alt="创意场景示例" className="absolute inset-y-0 right-0 hidden h-full w-[46%] object-cover opacity-70 [mask-image:linear-gradient(to_right,transparent,black_45%)] md:block" />
    </section>

    <section className="mt-9">
      <div className="mb-4 flex items-end justify-between"><div><h2 className="text-lg font-semibold tracking-tight">专业创作工具</h2><p className="mt-1 text-xs text-gray-500">选择适合当前任务的工作台，所有项目与生成记录会继续保留。</p></div><span className="hidden text-xs text-gray-500 sm:inline">{runtimeConfig.isStandalone ? '本地创作空间' : '团队协作空间'}</span></div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {workspaceCards.map((card) => <Link key={card.path} to={card.path} className="lovart-image-card group">
          <div className={`aspect-[1.65] overflow-hidden ${card.contain ? 'bg-[#eeeeeb] p-7' : 'bg-[#242424]'}`}><img src={`${import.meta.env.BASE_URL}creative-assets/${card.image}`} alt={`${card.title}示例`} className={`h-full w-full ${card.contain ? 'object-contain' : 'object-cover'}`} /></div>
          <div className="flex items-center justify-between p-4"><div><h3 className="text-sm font-semibold text-gray-100">{card.title}</h3><p className="mt-1 text-xs text-gray-500">{card.description}</p></div><ArrowUpIcon className="h-4 w-4 rotate-45 text-gray-600 transition group-hover:text-white" /></div>
        </Link>)}
      </div>
    </section>
  </div>
}

export function PlatformPage({ page }: { page: keyof typeof pageCopy }) {
  const [title, description] = pageCopy[page]
  return <section className="mt-6 rounded-[22px] border border-white/[0.08] bg-[#1b1b1b] p-6 shadow-sm">
    <h1 className="text-xl font-semibold tracking-tight text-white">{title}</h1>
    <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">{description}</p>
    <div className="mt-5 rounded-2xl border border-dashed border-white/10 bg-white/[0.025] px-4 py-6 text-sm text-gray-500">当前运行模式暂未开放此页面，现有工作台和本地数据不受影响。</div>
  </section>
}

export function NotFoundPage() {
  return <section className="mt-6 rounded-[22px] border border-white/[0.08] bg-[#1b1b1b] p-8 text-center shadow-sm">
    <h1 className="text-xl font-semibold text-white">页面不存在</h1>
    <Link to={appRoutes.dashboard} className="mt-4 inline-flex rounded-full bg-white px-4 py-2 text-sm font-semibold text-gray-950">返回概览</Link>
  </section>
}
