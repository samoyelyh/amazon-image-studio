import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import Header from '../components/Header'
import { runtimeConfig } from './runtimeConfig'
import { navigationSections, appRoutes } from './routes'
import { useAuth } from './AuthContext'
import { SparklesIcon } from '../components/agent-control/AgentControlIcons'
import { CopyIcon, EditIcon, ExternalLinkIcon, HistoryIcon, PhotoIcon, PlusIcon, SettingsIcon, SidebarLeftIcon } from '../components/icons'

function NavigationIcon({ path }: { path: string }) {
  if (path === appRoutes.agentControl) return <SparklesIcon className="h-5 w-5" />
  if (path === appRoutes.dashboard) return <SidebarLeftIcon className="h-5 w-5" />
  if (path === appRoutes.assets || path === appRoutes.attachmentMaterials) return <PhotoIcon className="h-5 w-5" />
  if (path === appRoutes.tasks || path === appRoutes.history || path === appRoutes.projects) return <HistoryIcon className="h-5 w-5" />
  if (path === appRoutes.profile || path === appRoutes.admin || path === appRoutes.quota) return <SettingsIcon className="h-5 w-5" />
  return <EditIcon className="h-5 w-5" />
}

export default function AppShell() {
  const auth = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const isAgent = location.pathname === appRoutes.agentControl
  const sections = navigationSections.map((section) => ({
    ...section,
    items: section.items.filter((item) =>
      (!item.multiuserOnly || !runtimeConfig.isStandalone)
      && (item.path !== '/admin' || auth.hasPermission('platform.admin')),
    ),
  })).filter((section) => section.items.length > 0)

  const mobileItems = sections.flatMap((section) => section.items)
  const mobilePrimary = [appRoutes.dashboard, appRoutes.agentControl, appRoutes.assets, appRoutes.tasks]
    .map((path) => mobileItems.find((item) => item.path === path))
    .filter((item) => item !== undefined)

  function renderFullNavigation() {
    return <div className="grid gap-8 p-5 sm:grid-cols-2 lg:grid-cols-4 lg:p-8">
      {sections.map((section) => <section key={section.label}>
        <h2 className="mb-3 px-2 text-[11px] font-medium uppercase tracking-[0.16em] text-gray-500">{section.label}</h2>
        <div className="space-y-1">{section.items.map((item) => <NavLink key={item.path} to={item.path} onClick={() => setMenuOpen(false)} className={({ isActive }) => `flex min-h-12 items-center gap-3 rounded-xl px-3 text-sm transition ${isActive ? 'bg-white text-gray-950' : 'text-gray-400 hover:bg-white/[0.06] hover:text-white'}`}>
          <NavigationIcon path={item.path} /><span>{item.label}</span><ExternalLinkIcon className="ml-auto h-3.5 w-3.5 opacity-35" />
        </NavLink>)}</div>
      </section>)}
    </div>
  }

  return (
    <div className={`lovart-shell ${isAgent ? 'flex h-dvh flex-col overflow-hidden' : 'min-h-screen'} bg-[#f7f7f5] text-gray-900`}>
      <Header />
      <div className={isAgent
        ? 'mx-auto flex min-h-0 w-full max-w-none flex-1 items-stretch pb-20 lg:pb-0'
        : 'mx-auto flex w-full max-w-none items-start'}>
        {!isAgent && <aside className="sticky top-0 hidden h-[calc(100dvh-3.5rem)] w-16 shrink-0 flex-col items-center border-r border-white/[0.07] bg-[#f1f1ee] px-2 py-4 lg:flex">
          <NavLink aria-label="AI 创作首页" title="AI 创作首页" to={appRoutes.agentControl} className="mb-5 flex h-9 w-9 items-center justify-center rounded-xl bg-white text-gray-950"><SparklesIcon className="h-5 w-5" /></NavLink>
          <NavLink aria-label="新建创作" title="新建创作" to={appRoutes.agentControl} className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 text-gray-300 transition hover:bg-white/[0.07] hover:text-white"><PlusIcon className="h-5 w-5" /></NavLink>
          <NavLink aria-label="概览" title="概览" to={appRoutes.dashboard} className={({ isActive }) => `flex h-10 w-10 items-center justify-center rounded-xl transition ${isActive ? 'bg-white/[0.1] text-white' : 'text-gray-500 hover:text-white'}`}><SidebarLeftIcon className="h-5 w-5" /></NavLink>
          <button aria-label="打开全部创作工具" title="全部创作工具" className={`mt-1 flex h-10 w-10 items-center justify-center rounded-xl transition ${menuOpen ? 'bg-white/[0.1] text-white' : 'text-gray-500 hover:text-white'}`} onClick={() => setMenuOpen(true)}><CopyIcon className="h-5 w-5" /></button>
          <NavLink aria-label="素材中心" title="素材中心" to={appRoutes.assets} className={({ isActive }) => `mt-1 flex h-10 w-10 items-center justify-center rounded-xl transition ${isActive ? 'bg-white/[0.1] text-white' : 'text-gray-500 hover:text-white'}`}><PhotoIcon className="h-5 w-5" /></NavLink>
          <NavLink aria-label="任务中心" title="任务中心" to={appRoutes.tasks} className={({ isActive }) => `mt-1 flex h-10 w-10 items-center justify-center rounded-xl transition ${isActive ? 'bg-white/[0.1] text-white' : 'text-gray-500 hover:text-white'}`}><HistoryIcon className="h-5 w-5" /></NavLink>
          <NavLink aria-label="个人中心" title="个人中心" to={appRoutes.profile} className="mt-auto flex h-10 w-10 items-center justify-center rounded-xl text-gray-500 transition hover:text-white"><SettingsIcon className="h-5 w-5" /></NavLink>
        </aside>}
        <main data-home-main data-drag-select-surface className={`min-w-0 flex-1 ${isAgent ? 'h-full min-h-0' : 'px-3 pb-28 sm:px-5 lg:px-8 lg:pb-10'}`}>
          <Outlet />
        </main>
      </div>
      <nav aria-label="移动端主导航" className="safe-area-x fixed inset-x-0 bottom-0 z-30 border-t border-white/[0.08] bg-[#f1f1ee]/95 px-2 pb-[max(.5rem,var(--safe-area-bottom))] pt-2 shadow-[0_-12px_36px_rgba(0,0,0,0.28)] backdrop-blur lg:hidden">
        <div className="grid grid-cols-5 gap-1">
          {mobilePrimary.map((item) => <NavLink key={item.path} to={item.path} className={({ isActive }) => `flex min-w-0 flex-col items-center gap-1 rounded-xl px-1 py-2 text-[10px] font-medium transition ${isActive ? 'bg-white text-gray-950' : 'text-gray-500'}`}>
            <NavigationIcon path={item.path} /><span className="max-w-full truncate">{item.shortLabel ?? item.label}</span>
          </NavLink>)}
          <button aria-label="打开全部导航" className="flex min-w-0 flex-col items-center gap-1 rounded-xl px-1 py-2 text-[10px] font-medium text-gray-500" onClick={() => setMenuOpen(true)}><CopyIcon className="h-5 w-5" /><span>全部</span></button>
        </div>
      </nav>
      {menuOpen && <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={() => setMenuOpen(false)}>
        <section aria-label="全部创作导航" className="absolute inset-y-0 left-0 w-[92%] max-w-4xl overflow-y-auto border-r border-white/10 bg-[#181818] shadow-2xl lg:left-16" onClick={(event) => event.stopPropagation()}>
          <div className="flex h-16 items-center justify-between border-b border-white/[0.07] px-5 lg:px-8"><div><p className="text-sm font-semibold">创作与团队工作区</p><p className="mt-1 text-[11px] text-gray-500">选择工具，继续当前的图片生产工作</p></div><button className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-gray-400 hover:text-white" onClick={() => setMenuOpen(false)}>关闭</button></div>
          {renderFullNavigation()}
        </section>
      </div>}
    </div>
  )
}
