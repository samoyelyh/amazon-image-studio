import { NavLink, Outlet } from 'react-router-dom'
import Header from '../components/Header'
import { runtimeConfig } from './runtimeConfig'
import { navigationSections } from './routes'
import { useAuth } from './AuthContext'

function getNavClassName({ isActive }: { isActive: boolean }) {
  return `flex min-h-10 items-center rounded-xl px-3 text-sm font-medium transition ${isActive
    ? 'bg-blue-600 text-white shadow-sm shadow-blue-600/20'
    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-950 dark:text-gray-300 dark:hover:bg-white/[0.06] dark:hover:text-white'}`
}

export default function AppShell() {
  const auth = useAuth()
  const sections = navigationSections.map((section) => ({
    ...section,
    items: section.items.filter((item) =>
      (!item.multiuserOnly || !runtimeConfig.isStandalone)
      && (item.path !== '/admin' || auth.hasPermission('platform.admin')),
    ),
  })).filter((section) => section.items.length > 0)

  const mobileItems = sections.flatMap((section) => section.items)

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      <Header />
      <div className="safe-area-x mx-auto flex max-w-[1600px] items-start gap-5 px-3 pb-28 sm:px-5 lg:px-6 lg:pb-8">
        <aside className="sticky top-5 hidden w-56 shrink-0 rounded-2xl border border-gray-200 bg-white p-3 shadow-sm dark:border-white/[0.08] dark:bg-gray-900 lg:block">
          <div className="mb-3 rounded-xl bg-gray-50 px-3 py-2 dark:bg-white/[0.04]">
            <div className="text-xs font-semibold text-gray-800 dark:text-gray-100">电商视觉平台</div>
            <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
              {runtimeConfig.isStandalone ? '单机模式 · 本地数据' : '多人模式 · 服务端数据'}
            </div>
          </div>
          <nav aria-label="主导航" className="space-y-4">
            {sections.map((section) => (
              <div key={section.label}>
                <div className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-gray-400">{section.label}</div>
                <div className="space-y-1">
                  {section.items.map((item) => <NavLink key={item.path} to={item.path} className={getNavClassName}>{item.label}</NavLink>)}
                </div>
              </div>
            ))}
          </nav>
        </aside>
        <main data-home-main data-drag-select-surface className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
      <nav aria-label="移动端主导航" className="safe-area-x fixed inset-x-0 bottom-0 z-30 border-t border-gray-200 bg-white/95 px-2 pb-[max(.5rem,var(--safe-area-bottom))] pt-2 shadow-[0_-10px_30px_rgba(15,23,42,0.08)] backdrop-blur dark:border-white/[0.08] dark:bg-gray-950/95 lg:hidden">
        <div className="flex gap-1 overflow-x-auto">
          {mobileItems.map((item) => (
            <NavLink key={item.path} to={item.path} className={({ isActive }) => `shrink-0 rounded-lg px-3 py-2 text-xs font-semibold transition ${isActive ? 'bg-blue-600 text-white' : 'text-gray-500 dark:text-gray-400'}`}>
              {item.shortLabel ?? item.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
