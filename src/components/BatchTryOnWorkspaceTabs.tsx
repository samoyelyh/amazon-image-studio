import { useEffect, useState } from 'react'
import type { BatchTryOnWorkspaceTab } from '../lib/batchTryOnWorkspaceApi'

const statusLabel: Record<string, string> = {
  draft: '待配置',
  validating: '样图验证中',
  ready: '可批量生成',
  queued: '排队中',
  running: '生成中',
  review: '待审核',
  completed: '已完成',
  failed: '有异常',
}

const statusDot: Record<string, string> = {
  validating: 'bg-blue-500',
  queued: 'bg-blue-500',
  running: 'bg-blue-500',
  ready: 'bg-emerald-500',
  completed: 'bg-emerald-500',
  review: 'bg-violet-500',
  failed: 'bg-red-500',
}

function EditIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-4 w-4">
    <path d="M13.8 3.7a1.8 1.8 0 0 1 2.5 2.5L7.2 15.3l-3.4.9.9-3.4 9.1-9.1Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
}

function TrashIcon() {
  return <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-4 w-4">
    <path d="M4 6h12M8 3.5h4M6 6l.6 10h6.8L14 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

export default function BatchTryOnWorkspaceTabs({
  tabs, activeId, busy, canHardDelete, onSelect, onCreate, onRename, onDeleteDraft, onHardDelete,
}: {
  tabs: BatchTryOnWorkspaceTab[]
  activeId?: string
  busy?: boolean
  canHardDelete?: boolean
  onSelect: (tab: BatchTryOnWorkspaceTab) => void
  onCreate: () => void
  onRename: (tab: BatchTryOnWorkspaceTab, name: string) => void | Promise<void>
  onDeleteDraft: (tab: BatchTryOnWorkspaceTab) => void
  onHardDelete: (tab: BatchTryOnWorkspaceTab) => void
}) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState('')
  const [renaming, setRenaming] = useState(false)

  useEffect(() => {
    if (editingId && !tabs.some((tab) => tab.id === editingId)) setEditingId(null)
  }, [editingId, tabs])

  const beginRename = (tab: BatchTryOnWorkspaceTab) => {
    setEditingId(tab.id)
    setEditingName(tab.name)
  }

  const finishRename = async (tab: BatchTryOnWorkspaceTab) => {
    const name = editingName.trim()
    if (!name || name === tab.name) {
      setEditingId(null)
      return
    }
    setRenaming(true)
    try {
      await onRename(tab, name)
      setEditingId(null)
    } finally {
      setRenaming(false)
    }
  }

  return <section className="mb-4 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-3 py-2.5 dark:border-white/[0.06] sm:px-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-gray-100">批次工作区</h2>
          <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500 dark:bg-white/[0.06] dark:text-gray-400">{tabs.length} 个批次</span>
        </div>
        <p className="mt-0.5 text-[11px] text-gray-500 dark:text-gray-400">每个标签独立保存模板、服装、提示词和生成进度，切换不会清空其他批次。</p>
      </div>
      <button
        type="button"
        disabled={busy}
        onClick={onCreate}
        className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 text-xs font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="text-base font-normal leading-none">＋</span>
        {busy ? '正在创建…' : '新建批次'}
      </button>
    </div>

    <div className="overflow-x-auto px-3 py-3 sm:px-4">
      <div className="flex min-w-max items-stretch gap-2.5">
        {tabs.map((tab) => {
          const active = activeId === tab.id
          const canDelete = tabs.length > 1 && tab.status === 'draft' && !tab.validation_batch_ids.length && !tab.production_batch_ids.length
          const progress = tab.total_jobs ? Math.min(100, Math.round((tab.completed_jobs / tab.total_jobs) * 100)) : 0
          return <div
            key={tab.id}
            className={`group relative w-[224px] overflow-hidden rounded-xl border transition ${active
              ? 'border-blue-300 bg-blue-50/80 shadow-[0_3px_12px_rgba(37,99,235,0.10)] ring-1 ring-blue-100 dark:border-blue-500/50 dark:bg-blue-500/[0.10] dark:ring-blue-500/10'
              : 'border-gray-200 bg-gray-50/80 hover:border-gray-300 hover:bg-white hover:shadow-sm dark:border-white/[0.08] dark:bg-white/[0.035] dark:hover:border-white/[0.16] dark:hover:bg-white/[0.06]'
            }`}
          >
            {editingId === tab.id ? <div className="p-2.5">
              <label htmlFor={`batch-name-${tab.id}`} className="mb-1.5 block text-[11px] font-medium text-gray-500 dark:text-gray-400">批次名称</label>
              <div className="flex items-center gap-1.5">
                <input
                  id={`batch-name-${tab.id}`}
                  autoFocus
                  value={editingName}
                  maxLength={160}
                  onChange={(event) => setEditingName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.nativeEvent.isComposing) void finishRename(tab)
                    if (event.key === 'Escape') setEditingId(null)
                  }}
                  className="h-8 min-w-0 flex-1 rounded-lg border border-blue-300 bg-white px-2 text-xs font-semibold text-gray-900 outline-none ring-2 ring-blue-100 dark:border-blue-500/50 dark:bg-gray-900 dark:text-gray-100 dark:ring-blue-500/10"
                />
                <button type="button" disabled={renaming} onClick={() => void finishRename(tab)} className="h-8 rounded-lg bg-blue-600 px-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50" aria-label="保存批次名称">保存</button>
                <button type="button" disabled={renaming} onClick={() => setEditingId(null)} className="h-8 rounded-lg px-2 text-xs text-gray-500 hover:bg-gray-100 dark:hover:bg-white/[0.08]" aria-label="取消重命名">取消</button>
              </div>
            </div> : <>
              <button type="button" className="block w-full px-3 pb-2.5 pt-3 pr-[76px] text-left" onClick={() => onSelect(tab)} aria-current={active ? 'page' : undefined}>
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-xs font-semibold text-gray-900 dark:text-gray-100">{tab.name}</span>
                  {active && <span className="shrink-0 rounded bg-blue-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">当前</span>}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusDot[tab.status] || 'bg-amber-400'}`} />
                  <span>{statusLabel[tab.status] || tab.status}</span>
                  {tab.total_jobs > 0 && <span className="text-gray-400">· {tab.completed_jobs}/{tab.total_jobs}</span>}
                </div>
              </button>
              <div className={`absolute right-2 top-2 flex items-center gap-1 transition ${active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-within:opacity-100'}`}>
                <button type="button" onClick={() => beginRename(tab)} className="grid h-7 w-7 place-items-center rounded-lg border border-gray-200 bg-white/90 text-gray-500 shadow-sm hover:border-blue-200 hover:text-blue-600 dark:border-white/[0.1] dark:bg-gray-900 dark:text-gray-400" title="重命名批次" aria-label={`重命名 ${tab.name}`}><EditIcon /></button>
                {canDelete
                  ? <button type="button" onClick={() => onDeleteDraft(tab)} className="grid h-7 w-7 place-items-center rounded-lg border border-gray-200 bg-white/90 text-gray-400 shadow-sm hover:border-red-200 hover:bg-red-50 hover:text-red-600 dark:border-white/[0.1] dark:bg-gray-900" title="删除空白批次" aria-label={`删除空白批次 ${tab.name}`}><TrashIcon /></button>
                  : canHardDelete && <button type="button" onClick={() => onHardDelete(tab)} className="grid h-7 w-7 place-items-center rounded-lg border border-red-200 bg-white/90 text-red-500 shadow-sm hover:bg-red-50 hover:text-red-700 dark:border-red-400/20 dark:bg-gray-900 dark:text-red-300" title="永久删除批次及其数据" aria-label={`永久删除批次 ${tab.name}`}><TrashIcon /></button>}
              </div>
              {tab.total_jobs > 0 && <div className="h-0.5 bg-gray-100 dark:bg-white/[0.05]"><div className={`h-full transition-all ${tab.status === 'failed' ? 'bg-red-500' : 'bg-blue-500'}`} style={{ width: `${progress}%` }} /></div>}
            </>}
          </div>
        })}
      </div>
    </div>
  </section>
}
