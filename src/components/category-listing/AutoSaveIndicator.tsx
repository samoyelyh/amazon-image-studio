export type AutoSaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'failed'

const labels: Record<AutoSaveState, string> = {
  idle: '等待编辑', dirty: '有未保存修改', saving: '正在保存…', saved: '已保存', failed: '保存失败',
}

const colors: Record<AutoSaveState, string> = {
  idle: 'bg-gray-100 text-gray-500 dark:bg-white/[0.08] dark:text-gray-300',
  dirty: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  saving: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300',
  saved: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300',
  failed: 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300',
}

export default function AutoSaveIndicator({ state, savedAt, onRetry }: {
  state: AutoSaveState
  savedAt?: string | null
  onRetry?: () => void
}) {
  const time = savedAt ? new Date(savedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''
  return <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${colors[state]}`}>
    {labels[state]}{state === 'saved' && time ? ` ${time}` : ''}
    {state === 'failed' && onRetry && <button type="button" className="underline" onClick={onRetry}>重试</button>}
  </span>
}
