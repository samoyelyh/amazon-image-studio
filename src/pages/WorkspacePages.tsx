import { useEffect } from 'react'
import AmazonPlanner from '../components/AmazonPlanner'
import BatchTryOnWorkspace from '../components/BatchTryOnWorkspace'
import InputBar from '../components/InputBar'
import SearchBar from '../components/SearchBar'
import TaskGrid from '../components/TaskGrid'
import { useStore } from '../store'
import type { GalleryWorkspace } from '../types'

function useActiveGalleryWorkspace(workspace: GalleryWorkspace) {
  const activateGalleryWorkspace = useStore((state) => state.activateGalleryWorkspace)
  useEffect(() => activateGalleryWorkspace(workspace), [activateGalleryWorkspace, workspace])
}

function PlannerWorkspacePage({ workspace }: { workspace: GalleryWorkspace }) {
  useActiveGalleryWorkspace(workspace)
  return (
    <div className="home-main-with-dock pb-40 lg:pb-10">
      <AmazonPlanner key={workspace} mode={workspace} />
      <SearchBar />
      <TaskGrid />
      <InputBar />
    </div>
  )
}

export function ListingWorkspacePage() {
  return <PlannerWorkspacePage workspace="listing" />
}

export function APlusWorkspacePage() {
  return <PlannerWorkspacePage workspace="aplus" />
}

export function BatchTryOnWorkspacePage() {
  return (
    <section className="mt-6 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
      <div className="border-b border-gray-200 px-4 py-4 dark:border-white/[0.08] sm:px-5">
        <h1 className="text-lg font-bold tracking-tight text-gray-900 dark:text-gray-50">批量套图工作台</h1>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">固定模特模板，批量上传服装并通过本地异步队列生成套图。</p>
      </div>
      <BatchTryOnWorkspace />
    </section>
  )
}
