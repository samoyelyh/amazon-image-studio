import { useEffect, useState } from 'react'
import { getRetentionSettings, previewRetention, saveRetention, runRetention,
  type RetentionRule, type RetentionSettings, type RetentionPreview } from '../lib/batchTryOnSharedQueueApi'

const input = 'w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/10 dark:bg-gray-900'
const defaultRule: RetentionRule = { enabled: false, days: 3, age_basis: 'last_activity', action: 'delete' }
const ruleOf = (s: RetentionRule): RetentionRule => ({ enabled: s.enabled, days: s.days, age_basis: s.age_basis, action: s.action })

export default function BatchTryOnQueueSettings({ onClose, onChanged, initialSettings }: { onClose: () => void; onChanged: () => void; initialSettings?: RetentionSettings }) {
  const [settings, setSettings] = useState<RetentionSettings | null>(initialSettings || null)
  const [draft, setDraft] = useState<RetentionRule>(initialSettings ? ruleOf(initialSettings) : defaultRule)
  const [preview, setPreview] = useState<RetentionPreview | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (!initialSettings) void getRetentionSettings().then((s) => { setSettings(s); setDraft(ruleOf(s)) }).catch((e) => setMessage(e.message)) }, [initialSettings])
  const changed = (patch: Partial<RetentionRule>) => { setDraft((d) => ({ ...d, ...patch })); setPreview(null); setMessage('') }
  const saved = settings && JSON.stringify(ruleOf(settings)) === JSON.stringify(draft)
  const destructive = draft.action === 'delete' && draft.enabled
  const confirmed = !destructive || confirmation.trim() === '永久删除'
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setMessage('')
    try { await action() } catch (e) { setMessage(e instanceof Error ? e.message : '操作失败，请重试') } finally { setBusy(false) }
  }
  return <div role="dialog" aria-modal="true" aria-label="队列自动清理设置" className="fixed inset-0 z-[120] flex items-center justify-center bg-black/35 p-4" onClick={onClose}>
    <section className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl dark:bg-gray-950" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold text-gray-900 dark:text-white">队列自动清理设置</h2><button onClick={onClose} aria-label="关闭清理设置" className="rounded-lg px-3 py-1 text-gray-500">✕</button></div>
      <p className="mt-2 text-xs leading-6 text-gray-500">作用于当前团队所有人的批量套图标签。每5分钟检查一次，每轮最多处理20组；跳过运行中、分发中及未达到期限的批次，不调用生图模型。</p>
      <p className="mt-1 text-xs leading-5 text-gray-500">默认3天，首次启用前请预览。关闭开关可停止后续自动处理；已经删除数据库记录的存储对象清理仍会重试完成。</p>
      {!settings ? <p className="py-8 text-sm text-gray-500">{message || '正在读取服务端设置…'}</p> : <>
        {!settings.can_manage && <p className="mt-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-500 dark:bg-white/5">你可以查看规则；只有团队管理员可以修改和执行清理。</p>}
        <fieldset disabled={!settings.can_manage || busy} className="mt-5 space-y-4 disabled:opacity-60">
          <label className="flex items-center gap-3 text-sm text-gray-800 dark:text-gray-200"><input type="checkbox" checked={draft.enabled} onChange={(e) => changed({ enabled: e.target.checked })} />启用团队自动清理</label>
          <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs text-gray-500">超过多少天<div className="mt-1 flex items-center gap-2"><input aria-label="清理期限天数" type="number" min={1} max={365} value={draft.days} onChange={(e) => changed({ days: Number(e.target.value) })} className={input} /><span>天</span></div></label>
            <label className="text-xs text-gray-500">计时基准<select value={draft.age_basis} onChange={(e) => changed({ age_basis: e.target.value as RetentionRule['age_basis'] })} className={`${input} mt-1`}>
              <option value="last_activity">最后活动时间（推荐）</option><option value="created_at">批次创建时间</option></select></label></div>
          <label className="block text-xs text-gray-500">过期处理方式<select aria-label="过期处理方式" value={draft.action} onChange={(e) => changed({ action: e.target.value as RetentionRule['action'] })} className={`${input} mt-1`}>
            <option value="delete">取消未开始任务，永久删除批次与结果图</option><option value="pause_archive">暂停未开始的图片任务并归档（可恢复）</option><option value="archive">仅归档已结束批次（可恢复）</option></select></label>
          {draft.action === 'delete' && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-xs leading-6 text-red-700 dark:border-red-500/20 dark:bg-red-500/5">
            永久清理不可撤销。会取消过期未开始任务并释放预占额度，再删除批次、审核版本和结果图片；保留上传原图及被其他业务引用的共享素材。需要保留的结果请先下载。
            <label className="mt-2 block">启用或立即执行前，请输入“永久删除”<input aria-label="永久删除确认文字" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} className={`${input} mt-1`} placeholder="永久删除" /></label></div>}
          <div className="flex flex-wrap gap-2"><button type="button" disabled={!draft.days || draft.days < 1 || draft.days > 365} onClick={() => void run(async () => { setPreview(await previewRetention(draft)); setMessage('预览不会修改任何任务或图片。') })} className="rounded-lg border border-gray-200 px-4 py-2 text-sm">预览影响范围</button>
            <button type="button" disabled={!confirmed || !draft.days || draft.days < 1 || draft.days > 365} onClick={() => void run(async () => {
              if (destructive && !window.confirm(`确认启用超过 ${draft.days} 天的自动永久清理吗？\n批次与结果图删除后无法恢复，请先下载需要的结果。`)) return
              const s = await saveRetention(draft, settings.revision, confirmed && destructive ? 'PERMANENT_DELETE' : '')
              setSettings(s); setDraft(ruleOf(s)); setPreview(null); onChanged(); setMessage(s.enabled ? '已保存，后台每5分钟按此规则检查。' : '已保存，自动清理已关闭。')
            })} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">保存设置</button></div>
        </fieldset>
        {preview && <div className="mt-5 rounded-xl border border-gray-200 p-4 text-xs leading-6 dark:border-white/10"><h3 className="font-semibold">本次预览</h3>
          <p>符合条件 {preview.eligible_count} 组，包含 {preview.batch_count} 个批次、{preview.job_count} 个任务。</p>
          <p className="text-gray-500">运行/分发中跳过 {preview.skipped.active || 0} 组；未完成而不适合当前操作 { (preview.skipped.unfinished || 0) + (preview.skipped.pending_analysis || 0) } 组。</p>
          {preview.samples.map((s) => <div key={s.id} className="truncate text-gray-500">{s.name} · {new Date(s.reference_at).toLocaleString('zh-CN')}</div>)}
          {settings.can_manage && <button type="button" disabled={busy || !saved || !settings.enabled || !confirmed || !preview.eligible_count} className="mt-3 rounded-lg border border-red-200 px-4 py-2 font-semibold text-red-600 disabled:opacity-40" onClick={() => void run(async () => {
            if (!window.confirm(`确认现在处理预览中的过期批次？${draft.action === 'delete' ? '\n永久删除不可恢复。' : '\n已有图片会保留。'}`)) return
            await runRetention(settings.revision, preview.preview_token, draft.action === 'delete' ? 'PERMANENT_DELETE' : '')
            setSettings(await getRetentionSettings()); setPreview(null); onChanged(); setMessage('已提交后台维护队列，不占生图槽位。稍后可重新打开设置查看处理结果。')
          })}>立即执行本轮清理</button>}
          {!saved && <p className="mt-2 text-gray-500">请先保存规则，再重新预览后执行。</p>}
        </div>}
        <div className="mt-5 border-t border-gray-100 pt-4 text-xs leading-6 text-gray-500 dark:border-white/10">最近自动检查：{settings.last_run_at ? new Date(settings.last_run_at).toLocaleString('zh-CN') : '尚未执行'}
          {settings.enabled && Boolean(settings.last_run_summary.queued) && <p>清理请求已进入后台维护队列。</p>}
          {settings.last_run_at && <p>归档 {settings.last_run_summary.archived || 0} · 删除批次 {settings.last_run_summary.deleted_batches || 0} · 删除结果 {settings.last_run_summary.deleted_results || 0} · 保留共享图片 {settings.last_run_summary.retained_shared_assets || 0} · 错误 {settings.last_run_summary.errors || 0} · 待清理存储 {settings.pending_storage_count}</p>}</div>
        {message && <p role="status" className="mt-3 text-sm text-gray-700 dark:text-gray-300">{message}</p>}
      </>}
    </section>
  </div>
}
