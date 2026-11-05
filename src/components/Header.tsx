import { Link } from 'react-router-dom'
import { SparklesIcon } from './agent-control/AgentControlIcons'

export default function Header() {
  return (
    <>
      <header data-no-drag-select className="safe-area-top fixed top-0 left-0 right-0 z-40 border-b border-white/[0.07] bg-[#f7f7f5]/90 backdrop-blur-xl">
        <div className="safe-area-x safe-header-inner mx-auto flex max-w-none items-center justify-between px-1 sm:px-3">
          <Link to="/workspaces/agent-control" className="flex min-w-0 items-center gap-2.5 pr-3">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-gray-950 lg:hidden"><SparklesIcon className="h-4 w-4" /></span>
            <span className="truncate text-[15px] font-semibold tracking-[-0.02em] text-gray-100 sm:text-base">Amazon Image Studio</span>
          </Link>
          <div className="hidden items-center gap-2 text-[11px] text-gray-500 sm:flex"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />AI 图片创作平台</div>
        </div>
      </header>
      <div className="safe-area-top invisible pointer-events-none" aria-hidden="true"><div className="safe-header-inner" /></div>
    </>
  )
}
