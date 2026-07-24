import { Link } from 'react-router-dom'
import { runtimeConfig } from '../app/runtimeConfig'
import { appRoutes } from '../app/routes'

const pageCopy = {
  tasks: ['任务中心', 'Phase 6 已完成统一任务 API、Celery 队列、状态恢复和多 Key 资源池；Phase 7 将接入三个工作台并提供可视化任务列表。'],
  assets: ['素材中心', 'Phase 4 接入对象存储、素材归档、标签与项目复用。'],
  projects: ['项目系统', 'Phase 4 在多人模式下提供三类项目草稿、不可变版本和素材关联。'],
  history: ['生成历史', 'Phase 4 接入统一生成历史；当前 standalone 历史继续保存在浏览器 IndexedDB。'],
  quota: ['额度中心', '多人模式已接入服务端额度账户、流水、预占、结算、退款和费用预估。'],
  profile: ['个人中心', 'Phase 3 接入账号资料、团队与角色权限。'],
  admin: ['管理后台', 'Phase 8 接入用户、团队、套餐、额度、Key 池、任务与审计管理。'],
} as const

export function DashboardPage() {
  const workspaces = [
    ['Listing 图', '主图、附图策划与生成', appRoutes.listing],
    ['批量套图', '固定模特批量替换服装', appRoutes.batchTryOn],
    ['A+ 图', 'A+ 模块编排、文案与生成', appRoutes.aplus],
  ] as const
  return (
    <div className="mt-6 space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <div className="text-xs font-semibold text-blue-600 dark:text-blue-300">{runtimeConfig.isStandalone ? 'STANDALONE' : 'MULTIUSER'}</div>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-gray-950 dark:text-white">电商视觉工作台</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500 dark:text-gray-400">三个业务工作台已拆分为独立路由，多人模式已接入统一账号、团队、角色权限、私有素材、项目版本、额度计费、异步任务与多 Key 资源池。工作台任务提交和任务中心界面将在 Phase 7 接入。</p>
      </section>
      <div className="grid gap-4 md:grid-cols-3">
        {workspaces.map(([title, description, path]) => (
          <Link key={path} to={path} className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md dark:border-white/[0.08] dark:bg-gray-900 dark:hover:border-blue-400/30">
            <h2 className="font-bold text-gray-900 dark:text-gray-100">{title}</h2>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">{description}</p>
            <div className="mt-5 text-sm font-semibold text-blue-600 dark:text-blue-300">进入工作台 →</div>
          </Link>
        ))}
      </div>
    </div>
  )
}

export function PlatformPage({ page }: { page: keyof typeof pageCopy }) {
  const [title, description] = pageCopy[page]
  return (
    <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <h1 className="text-xl font-bold text-gray-950 dark:text-white">{title}</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500 dark:text-gray-400">{description}</p>
      <div className="mt-5 rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-sm text-gray-500 dark:border-white/[0.08] dark:bg-gray-950 dark:text-gray-400">本页只建立正式路由和信息架构，不创建虚假任务、额度或用户数据。</div>
    </section>
  )
}

export function NotFoundPage() {
  return (
    <section className="mt-6 rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <h1 className="text-xl font-bold text-gray-950 dark:text-white">页面不存在</h1>
      <Link to={appRoutes.dashboard} className="mt-4 inline-flex rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white">返回概览</Link>
    </section>
  )
}
