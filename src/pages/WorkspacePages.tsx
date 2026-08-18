import { useEffect } from 'react'
import AmazonPlanner from '../components/AmazonPlanner'
import CategoryListingWorkflow from '../components/CategoryListingWorkflow'
import BatchTryOnWorkspace from '../components/BatchTryOnWorkspace'
import InputBar from '../components/InputBar'
import SearchBar from '../components/SearchBar'
import TaskGrid from '../components/TaskGrid'
import { useStore } from '../store'
import type { GalleryWorkspace } from '../types'
import { Link } from 'react-router-dom'

function useActiveGalleryWorkspace(workspace: GalleryWorkspace) {
  const activateGalleryWorkspace = useStore((state) => state.activateGalleryWorkspace)
  useEffect(() => activateGalleryWorkspace(workspace), [activateGalleryWorkspace, workspace])
}

function PlannerWorkspacePage({ workspace }: { workspace: GalleryWorkspace }) {
  useActiveGalleryWorkspace(workspace)
  return (
    <div className={workspace === 'aplus' ? 'pb-10' : 'home-main-with-dock pb-40 lg:pb-10'}>
      {workspace === 'listing' && <div className="mb-4 flex justify-end"><Link to="/workspaces/listing" className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-blue-700 shadow-sm dark:border-white/[0.1] dark:bg-gray-900 dark:text-blue-300">进入品类 Listing 工作流</Link></div>}
      <AmazonPlanner key={workspace} mode={workspace} />
      {workspace !== 'aplus' && <SearchBar />}
      <TaskGrid />
      {workspace !== 'aplus' && <InputBar />}
    </div>
  )
}

export function ListingWorkspacePage({ legacy = false }: { legacy?: boolean }) {
  useActiveGalleryWorkspace('listing')
  if (legacy) return <PlannerWorkspacePage workspace="listing" />
  return <CategoryListingWorkflow />
}

export function APlusWorkspacePage() {
  return <PlannerWorkspacePage workspace="aplus" />
}

export function BatchTryOnWorkspacePage() {
  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <div className="border-b border-gray-200 px-4 py-4 dark:border-white/[0.08] sm:px-5">
        <h1 className="text-lg font-bold tracking-tight text-gray-900 dark:text-gray-50">批量套图工作台</h1>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">固定模特模板，批量上传服装；多人模式由服务端任务队列生成并支持刷新恢复。</p>
      </div>
      <BatchTryOnWorkspace />
    </section>
  )
}
