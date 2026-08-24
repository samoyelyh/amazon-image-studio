import { useEffect, useRef, useState } from 'react'
import {
  applyHermesProposal,
  cancelHermesProposal,
  createHermesConversation,
  getHermesStatus,
  listHermesConversations,
  sendHermesMessage,
  type HermesConversation,
  type HermesStatus,
} from '../../lib/hermesAgentApi'

const actionLabels: Record<string, string> = {
  set_visual_preset: '切换视觉预设', set_theme: '切换主题', set_module_model: '设置模块模特',
  attach_reference_library_item: '添加公共参考图', plan_modules: '运行AI策划',
  generate_modules: '提交图片生成', edit_generated_output: '修改生成结果', record_feedback: '记录反馈',
}

const quickPrompts = [
  '帮我检查当前六个模块还有哪些没有准备好',
  '根据当前商品给我一套视觉方向建议，先不要修改',
  '帮我策划当前已准备好的模块',
  '解释一下当前任务和结果状态',
]

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请稍后重试'
}

interface Props {
  open: boolean
  projectId: string
  productName: string
  categoryName: string
  selectedModuleCount: number
  planningStatus: string
  onClose: () => void
  onApplied: () => Promise<void> | void
  onNotice: (message: string, type?: 'success' | 'error' | 'info') => void
}

export default function HermesAssistantDrawer({
  open, projectId, productName, categoryName, selectedModuleCount, planningStatus,
  onClose, onApplied, onNotice,
}: Props) {
  const [status, setStatus] = useState<HermesStatus | null>(null)
  const [conversation, setConversation] = useState<HermesConversation | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open || !projectId) return
    let active = true
    setInitializing(true); setError('')
    void Promise.all([getHermesStatus(projectId), listHermesConversations(projectId)])
      .then(async ([nextStatus, rows]) => {
        if (!active) return
        setStatus(nextStatus)
        const row = rows[0] || (nextStatus.available ? await createHermesConversation(projectId) : null)
        if (active) setConversation(row)
      })
      .catch((reason) => { if (active) setError(errorMessage(reason)) })
      .finally(() => { if (active) setInitializing(false) })
    return () => { active = false }
  }, [open, projectId])

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [conversation?.messages.length, loading])

  const submit = async (content = input) => {
    const text = content.trim()
    if (!text || !conversation || loading || !status?.available) return
    setLoading(true); setError(''); setInput('')
    try {
      setConversation(await sendHermesMessage(projectId, conversation.id, text))
    } catch (reason) {
      setInput(text); setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }

  const apply = async (proposalId: string) => {
    if (!conversation || loading) return
    setLoading(true); setError('')
    try {
      await applyHermesProposal(projectId, proposalId)
      const rows = await listHermesConversations(projectId)
      setConversation(rows.find((item) => item.id === conversation.id) || rows[0] || conversation)
      await onApplied()
      onNotice('提案已应用，工作台已经按最新状态刷新。', 'success')
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }

  const cancel = async (proposalId: string) => {
    if (!conversation || loading) return
    setLoading(true); setError('')
    try {
      await cancelHermesProposal(projectId, proposalId)
      const rows = await listHermesConversations(projectId)
      setConversation(rows.find((item) => item.id === conversation.id) || rows[0] || conversation)
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setLoading(false)
    }
  }

  if (!open) return null
  return <div className="fixed inset-0 z-[95] flex justify-end bg-gray-950/25 backdrop-blur-[1px]" role="dialog" aria-modal="true" aria-label="Hermes 智能助理">
    <button type="button" className="min-w-0 flex-1 cursor-default" aria-label="关闭 Hermes" onClick={onClose} />
    <aside className="flex h-full w-full max-w-[520px] flex-col border-l border-gray-200 bg-[#F7F8FA] shadow-2xl dark:border-white/[0.08] dark:bg-gray-950">
      <header className="border-b border-gray-200 bg-white px-5 py-4 dark:border-white/[0.08] dark:bg-gray-900">
        <div className="flex items-start justify-between gap-4">
          <div><div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-violet-600 text-sm font-bold text-white">H</span><h2 className="text-base font-semibold text-gray-950 dark:text-white">Hermes 智能助理</h2><span className="rounded-full bg-violet-50 px-2 py-1 text-[10px] font-semibold text-violet-700">建议确认模式</span></div><p className="mt-2 text-xs text-gray-500">先给建议和变更清单；只有你点击应用后才会改动工作台。</p></div>
          <button type="button" onClick={onClose} className="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-white/[0.08]">✕</button>
        </div>
      </header>

      <div className="border-b border-gray-200 bg-white px-5 py-3 dark:border-white/[0.08] dark:bg-gray-900">
        <div className="rounded-xl border border-gray-100 bg-gray-50 p-3 text-xs dark:border-white/[0.06] dark:bg-white/[0.03]"><div className="font-semibold text-gray-800 dark:text-gray-100">当前上下文</div><div className="mt-1 truncate text-gray-500">{productName} · {categoryName}</div><div className="mt-1 text-gray-400">已选 {selectedModuleCount} 个模块 · 策划状态 {planningStatus || 'idle'}</div></div>
        {status && <div className={`mt-2 rounded-lg px-3 py-2 text-xs ${status.available ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'}`}>{status.message}</div>}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {initializing && <div className="py-10 text-center text-sm text-gray-500">正在连接 Hermes 并恢复对话…</div>}
        {!initializing && !conversation?.messages.length && <div className="rounded-2xl border border-dashed border-gray-200 bg-white p-5 text-sm text-gray-600 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-300"><div className="font-semibold text-gray-900 dark:text-white">可以从一句自然语言开始</div><p className="mt-2 text-xs leading-5 text-gray-500">例如：检查哪些模块没准备好、给一套视觉建议、策划指定模块，或在你确认后提交生成。</p></div>}
        <div className="space-y-3">{conversation?.messages.map((message) => <div key={message.id} className={message.role === 'user' ? 'ml-12' : 'mr-5'}>
          <div className={`rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'bg-blue-600 text-white' : 'border border-gray-200 bg-white text-gray-700 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-200'}`}>{message.content}</div>
          {message.proposal && <div className="mt-2 rounded-2xl border border-violet-200 bg-violet-50/70 p-4 dark:border-violet-400/20 dark:bg-violet-500/10">
            <div className="flex items-center justify-between gap-2"><div className="text-xs font-semibold text-violet-800 dark:text-violet-200">Hermes 变更提案</div><span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold text-violet-700">{message.proposal.status === 'pending' ? '等待确认' : message.proposal.status === 'applied' ? '已应用' : message.proposal.status === 'cancelled' ? '已取消' : message.proposal.status === 'stale' ? '已过期' : '执行失败'}</span></div>
            <p className="mt-2 text-sm text-gray-700 dark:text-gray-200">{message.proposal.summary}</p>
            <div className="mt-3 space-y-1.5">{message.proposal.actions.map((action, index) => <div key={`${action.tool}-${index}`} className="rounded-lg bg-white px-3 py-2 text-xs text-gray-600 dark:bg-gray-900 dark:text-gray-300"><span className="font-semibold">{index + 1}. {actionLabels[action.tool] || action.tool}</span><span className="ml-2 text-gray-400">{Object.keys(action.arguments).length ? JSON.stringify(action.arguments) : '使用当前设置'}</span></div>)}</div>
            {message.proposal.error_message && <div className="mt-2 text-xs text-red-600">{message.proposal.error_message}</div>}
            {message.proposal.status === 'pending' && <div className="mt-4 flex justify-end gap-2"><button type="button" disabled={loading} onClick={() => void cancel(message.proposal!.id)} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-600 disabled:opacity-50">暂不采用</button><button type="button" disabled={loading} onClick={() => void apply(message.proposal!.id)} className="rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">确认并应用</button></div>}
          </div>}
        </div>)}</div>
        {loading && <div className="mt-3 mr-20 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500 dark:border-white/[0.08] dark:bg-gray-900">Hermes 正在结合当前工作台思考…</div>}
        <div ref={endRef} />
      </div>

      <footer className="border-t border-gray-200 bg-white p-4 dark:border-white/[0.08] dark:bg-gray-900">
        {error && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        <div className="mb-3 flex gap-2 overflow-x-auto pb-1">{quickPrompts.map((item) => <button type="button" key={item} disabled={!status?.available || loading} onClick={() => void submit(item)} className="shrink-0 rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 disabled:opacity-40 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-300">{item}</button>)}</div>
        <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-gray-50 p-2 focus-within:border-violet-300 dark:border-white/[0.1] dark:bg-gray-950">
          <textarea value={input} disabled={!status?.available || loading} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } }} placeholder={status?.available ? '说说你想策划、调整或生成什么…' : 'Hermes 未连接，手工工作台仍可正常使用'} className="max-h-36 min-h-12 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-gray-800 outline-none disabled:cursor-not-allowed dark:text-gray-100" />
          <button type="button" disabled={!input.trim() || !status?.available || loading} onClick={() => void submit()} className="rounded-xl bg-violet-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-40">发送</button>
        </div>
        <div className="mt-2 text-center text-[10px] text-gray-400">Hermes 不会直接访问数据库、队列、对象存储或平台密钥。</div>
      </footer>
    </aside>
  </div>
}
