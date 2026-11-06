import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import AuthenticatedImage from '../AuthenticatedImage'
import { CloseIcon, DownloadIcon, EditIcon, ExternalLinkIcon } from '../icons'
import { canConfirmAgentRun, type AgentRun, type AgentStatus, type AgentOutput } from '../../lib/agentControlApi'
import { downloadAuthenticatedFile, downloadServerOutputZip } from '../../lib/serverDownloads'
import { SparklesIcon, StopIcon } from './AgentControlIcons'
import { actionStates, actionStateLabels } from '../../lib/agentActionState'
import AgentImageProgress from './AgentImageProgress'

export const chatButton = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full border border-black/[0.08] px-3.5 py-2 text-xs font-medium transition hover:bg-black/[0.04] disabled:cursor-not-allowed disabled:opacity-40 dark:border-white/10 dark:hover:bg-white/5'
const statusLabels: Record<string, string> = { planning: '理解中', awaiting_confirmation: '历史待执行方案',awaiting_clarification:'需要补充必要信息',awaiting_review:'方案待审核',ready_to_submit:'准备提交',submitted:'任务已提交', waiting_jobs: '生成中', completed: '已完成', failed: '失败', cancelled: '已停止', stale: '计划需更新', needs_input: '请补充信息', blocked: '当前不可执行', remote_unknown: '上游状态未知，请核对，勿重复提交' }
const workflowLabels: Record<string, string> = { fast: '快速生图', edit: '图片编辑', production: '批量生产', research: 'A+ 调研', aplus: 'A+ 模块生成', query: '状态查询', clarify: '需求理解', dynamic: '动态工具协作',suggestions:'AI 创作建议' }

function RunErrors({ run }: { run: AgentRun }) {
  const labels:Record<string,string>={asset_roles:'确认素材角色',reference_mapping:'确认正背面和字体参考对应关系',parent_output_id:'选择要修改的图片',suggestion_references:'减少本次建议参考图',sample_review:'请在样图卡中审核结果',reference_limit:'减少单次引用图片数量'}
  const needs=(run.plan?.needs_input||[]).filter(v=>v!=='clarification').map(v=>labels[v]||'补充创作要求')
  return <>
    {run.error_code && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{run.result.execution_error||(run.status === 'remote_unknown' ? '上游状态未知，请勿重复生成。' : `任务未完成：${run.error_code}`)}</p>}
    {run.plan?.blocked_reason && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">{run.plan.blocked_reason}</p>}
    {!!needs.length && <p role="status" className="mt-3 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">还需要补充：{needs.join('；')}</p>}
    {!!run.plan?.risks?.length && <div role="alert" className="mt-3 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">{run.plan.risks.map((risk) => <p key={risk}>{risk}</p>)}</div>}
  </>
}

const toolLabels: Record<string, string> = {
  suggest_creative_directions:'AI 创作建议',
  plan_intent: '需求分析', analyze_chat_assets: '素材理解', analyze_tryon_references: '套图素材分析',
  read_business_context: '读取项目素材', read_shared_queue: '读取协作队列', generate_chat_images: '图片生成',
  generate_chat_tryon: '服装套图', submit_tryon_batch: '批量套图', prepare_tryon_workspace: '准备套图工作区',
  configure_batch_inputs:'整理素材关系',followup_batch_results:'定向调整结果',review_tryon_samples:'审核与修改样图',guide_batch_inputs:'准备批次素材',
  recall_user_experience:'读取个人经验',manage_user_preference:'更新个人偏好',
  save_aplus_plan: 'A+ 方案设计', revise_aplus_module: 'A+ 模块优化', generate_aplus: 'A+ 图片生成',
  research_amazon: 'Amazon 调研', review_output: '结果审核', text_generation: '内容生成',
}

function ToolSchedule({ run, planning }: { run: AgentRun; planning: boolean }) {
  const actions = run.plan?.actions || []
  if (!actions.length) return planning ? <div className="mt-3 flex items-center gap-2 text-xs text-gray-400"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#a88a58]" />Agent 正在理解需求并分配创作工具</div> : null
  const steps = actionStates(run)
  return <div aria-label="Agent 工具调度" className="mt-4 rounded-xl bg-[#f7f7f4] px-3 py-2.5 dark:bg-white/[0.035]">
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 text-[11px] font-medium text-gray-400">Agent 调度</span>
      {actions.map((action, index) => {
        const current=steps[index].state
        const done=current==='succeeded',failed=['failed','cancelled','remote_unknown'].includes(current),active=current==='running',receipt=current==='submitted'
        const state=actionStateLabels[current]
        const tone = done ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300' : failed ? 'bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300' : active ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300' : receipt ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300' : 'bg-black/[0.04] text-gray-500 dark:bg-white/[0.06] dark:text-gray-400'
        return <span key={`${action.tool}:${index}`} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] ${tone}`}>
          <span className={`h-1 w-1 rounded-full ${done ? 'bg-emerald-500' : failed ? 'bg-red-500' : active ? 'animate-pulse bg-amber-500' : receipt ? 'bg-blue-500' : 'bg-gray-300'}`} />{toolLabels[action.tool] || '专业创作工具'} · {state}
        </span>
      })}
    </div>
  </div>
}

export function AgentPlanCard({ run, status, busy, onConfirm, onStop,onResume,onRetry,retriedIds,statusLabel }: { run: AgentRun; status: AgentStatus; busy: boolean; onConfirm: () => void; onStop: () => void;onResume?:()=>void;onRetry?:(id:string)=>void;retriedIds?:string[];statusLabel?:string }) {
  const imageJobs = run.jobs.filter((job) => job.capability !== 'text_generation')
  const waiting = run.status === 'awaiting_confirmation'
  const notice = run.execution_notice
  const isPlanning = run.status === 'waiting_jobs' && imageJobs.length === 0
  const canConfirm = canConfirmAgentRun(run, status)
  const title = workflowLabels[run.plan?.workflow || ''] || '创作任务'
  const previewBadge = run.planner_mode === 'mock' && <span className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] text-gray-500 dark:bg-white/5 dark:text-gray-400">预览计划</span>
  const workspaceLinks = <>
    {run.workspace_url && <Link className={chatButton} to={run.workspace_url}>打开任务与下载<ExternalLinkIcon className="h-3.5 w-3.5" /></Link>}
    {run.result.actions?.map((action) => typeof action.result.workspace_url === 'string' ? <Link key={action.tool} className={chatButton} to={action.result.workspace_url}>打开样图验证<ExternalLinkIcon className="h-3.5 w-3.5" /></Link> : null)}
  </>

  if(run.status==='awaiting_review'||(waiting&&status.auto_execution?.mode==='autonomous'))return <section aria-label="总控任务计划" className="studio-card p-4">
    <h3 className="text-sm font-semibold">{run.status==='awaiting_review'?'方案待审核':'历史待执行方案'}</h3>
    <p className="mt-2 text-sm leading-6">{run.plan?.summary}</p>
    <ToolSchedule run={run} planning={false}/><RunErrors run={run}/>
    <div className="mt-4 flex flex-wrap gap-2"><button type="button" className={chatButton} disabled={busy||!canConfirm} onClick={onConfirm}>{run.status==='awaiting_review'?'方案通过，开始生成':'继续原任务'}</button><button type="button" className={chatButton} disabled={busy} onClick={onStop}>停止后续操作</button></div>
  </section>

  if (waiting) {
    const imageCount = notice?.image_count ?? run.plan?.image_count ?? 0
    const credits = notice?.estimated_credits ?? run.plan?.budget?.estimated_cost
    return <section aria-label="总控任务计划" className="overflow-hidden rounded-[22px] border border-black/[0.08] bg-white shadow-[0_12px_36px_rgba(28,25,23,0.06)] dark:border-white/10 dark:bg-gray-900">
      <div className="px-5 pt-5 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-sm font-semibold"><SparklesIcon className="h-4 w-4 text-[#8b6f47]" />{title}</div>
          {previewBadge}
        </div>
        <h3 className="mt-4 text-lg font-semibold tracking-tight">这次创作需要你确认</h3>
        {run.plan?.summary && <p className="mt-1.5 text-sm leading-6 text-gray-500 dark:text-gray-400">{run.plan.summary}</p>}
      </div>
      <dl className="mx-5 mt-5 grid grid-cols-3 divide-x divide-black/[0.07] rounded-2xl bg-[#f7f7f4] py-4 text-center sm:mx-6 dark:divide-white/10 dark:bg-white/[0.04]">
        <div className="px-2"><dt className="text-[11px] text-gray-500 dark:text-gray-400">图片数量</dt><dd className="mt-1.5 text-base font-semibold">{imageCount} 张</dd></div>
        <div className="px-2"><dt className="text-[11px] text-gray-500 dark:text-gray-400">预计耗时</dt><dd className="mt-1.5 text-sm font-semibold leading-6">{notice?.estimate?.text || '待系统评估'}</dd></div>
        <div className="px-2"><dt className="text-[11px] text-gray-500 dark:text-gray-400">预计平台额度</dt><dd className="mt-1.5 text-base font-semibold">{credits ?? '—'}</dd></div>
      </dl>
      <div className="px-5 pb-5 sm:px-6 sm:pb-6">
        {notice?.reason && <p role="status" className="mt-4 rounded-xl bg-amber-50 px-3 py-2.5 text-sm leading-6 text-amber-800 dark:bg-amber-950/30 dark:text-amber-300">{notice.reason}</p>}
        {run.plan?.budget?.sufficient === false && <p role="alert" className="mt-3 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600 dark:bg-red-950/30 dark:text-red-300">平台额度不足，当前计划无法执行{run.plan.budget.available_balance != null ? `，可用额度 ${run.plan.budget.available_balance}` : ''}。</p>}
        {run.plan?.budget?.max_charge_units != null && <p className="mt-3 text-sm text-gray-500">本次调研最多使用 {run.plan.budget.max_charge_units} 调研单位。</p>}
        <ToolSchedule run={run} planning={isPlanning} />
        <RunErrors run={run} />
        {!canConfirm && <p role="alert" className="mt-3 text-sm text-amber-700 dark:text-amber-300">当前计划不可执行，请检查额度、权限或补充信息。</p>}
        <AgentImageProgress run={run} busy={busy} onRetry={onRetry} retriedIds={retriedIds}/>
        <div className="mt-5 flex gap-3">
          <button className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full bg-[#242421] px-5 text-sm font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-gray-900" disabled={busy || !canConfirm} onClick={onConfirm}>继续生成</button>
          <button className="inline-flex min-h-11 flex-1 items-center justify-center rounded-full border border-black/[0.1] px-5 text-sm font-medium transition hover:bg-black/[0.04] disabled:opacity-40 dark:border-white/15 dark:hover:bg-white/5" disabled={busy} onClick={onStop} title="仅停止后续操作，不取消已提交的图片任务">停止后续操作</button>
        </div>
        {(run.workspace_url || run.result.actions?.some((action) => typeof action.result.workspace_url === 'string')) && <div className="mt-3 flex flex-wrap gap-2">{workspaceLinks}</div>}
      </div>
    </section>
  }

  return <section aria-label="总控任务计划" className="rounded-[20px] border border-black/[0.07] bg-white/80 p-4 dark:border-white/10 dark:bg-gray-900/80">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm font-medium"><SparklesIcon className="h-4 w-4 text-[#8b6f47]" />{title}{previewBadge}</div>
      <span className={`inline-flex items-center gap-1.5 text-xs ${run.status === 'failed' ? 'text-red-500' : 'text-gray-500 dark:text-gray-400'}`}>
        {['planning', 'waiting_jobs'].includes(run.status) && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#a88a58]" />}
          {statusLabel || (isPlanning ? run.plan?.workflow==='suggestions'?'正在生成建议':'正在理解需求' : statusLabels[run.status] || run.status)}
      </span>
    </div>
    {run.plan?.summary && <p className="mt-2.5 text-sm leading-6 text-gray-600 dark:text-gray-300">{run.plan.summary}</p>}
    {notice?.estimate && run.status === 'waiting_jobs' && <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{notice.estimate.text}</p>}
    <ToolSchedule run={run} planning={isPlanning} />
    <RunErrors run={run} />
    {notice?.reason&&['ready_to_submit','submitted'].includes(run.status)&&<p role="status" className="mt-3 text-sm text-stone-600">{notice.reason}</p>}
    <AgentImageProgress run={run} busy={busy} onRetry={onRetry} retriedIds={retriedIds}/>
    <div className="mt-4 flex flex-wrap gap-2">
      {run.planner_mode==='dsh-native'&&['interrupted','failed'].includes(run.result.native_state||'')&&onResume&&<button className={chatButton} disabled={busy} onClick={onResume} title="读取已记录结果；费用未知的请求不会重新发送">读取回执并恢复</button>}
      {!['completed', 'cancelled', 'failed', 'stale', 'needs_input','awaiting_clarification', 'blocked', 'remote_unknown'].includes(run.status) && <button className={chatButton} disabled={busy} title="已提交任务可在任务中心管理" onClick={onStop}><StopIcon className="h-3.5 w-3.5" />停止后续操作</button>}
      {workspaceLinks}
    </div>
  </section>
}

export function AgentResultGallery({ outputs, onEdit, onError }: { outputs: AgentOutput[]; onEdit: (image: AgentOutput) => void; onError: (message: string) => void }) {
  const [preview, setPreview] = useState<AgentOutput | null>(null)
  const [downloading, setDownloading] = useState(false)
  useEffect(() => {
    if (!preview) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setPreview(null) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [preview])
  async function downloadAll() {
    setDownloading(true)
    try { await downloadServerOutputZip(outputs.map((output) => ({ ...output, review_status:undefined, display_filename: output.filename, download_filename: output.filename, url: output.content_url, url_expires_at: null })), '对话图片结果.zip') } catch (error) { onError(error instanceof Error ? error.message : '下载失败') } finally { setDownloading(false) }
  }
  if (!outputs.length) return null
  return <section aria-label="对话图片结果" className="mt-5">
    <div className="mb-3 flex items-center justify-between">
      <div><h3 className="text-sm font-semibold">生成结果</h3><p className="mt-0.5 text-xs text-gray-400">共 {outputs.length} 张，点击图片查看大图</p></div>
      <button className={chatButton} disabled={downloading} onClick={() => void downloadAll()}><DownloadIcon className="h-3.5 w-3.5" />{downloading ? '打包中…' : '下载本组'}</button>
    </div>
    <div className="grid grid-cols-2 gap-3 sm:gap-4">
      {outputs.map((output) => <article key={output.id} className="group overflow-hidden rounded-[18px] border border-black/[0.07] bg-white shadow-[0_4px_18px_rgba(28,25,23,0.03)] dark:border-white/10 dark:bg-gray-900">
        <button className="relative block aspect-square w-full overflow-hidden bg-[#f0f0ed] dark:bg-black/20" onClick={() => setPreview(output)} aria-label={`查看图片${output.number ?? ''}`}>
          <AuthenticatedImage src={output.content_url} alt={`图片 ${output.number ?? '结果'} · v${output.version}`} className="h-full w-full object-contain transition duration-500 group-hover:scale-[1.02]" />
          <span className="absolute left-2.5 top-2.5 rounded-full bg-black/55 px-2 py-1 text-[10px] text-white backdrop-blur-sm">{output.number ?? '—'} · v{output.version}</span>
        </button>
        <div className="p-3 sm:p-3.5">
          {output.amazon_module && <p className="mb-1 truncate text-xs font-medium">A+ · {output.amazon_module.module_snapshot?.title || output.amazon_module.module_id} · 方案 v{output.amazon_module.plan_revision}</p>}
          {output.batch_tryon&&<p className="mb-1 truncate text-xs font-medium">{output.batch_tryon.template_name} × {output.batch_tryon.garment_filename}</p>}
          {output.review_status&&<span className="text-xs text-gray-500">审核：{({pending:'待审核',approved:'已通过',rejected:'已打回'} as Record<string,string>)[output.review_status]||output.review_status}</span>}
          <p className="truncate text-[11px] text-gray-400">图片 {output.number ?? '—'} · v{output.version} · {output.width}×{output.height}{output.parent_output_id ? ' · 基于上一版编辑' : ''}</p>
          {output.source_asset_id&&<p className="mt-1 truncate text-xs text-stone-600" title={output.source_filename||undefined}>原图 {output.source_index??'—'}{output.source_filename?` · ${output.source_filename}`:''}</p>}
          <div className="mt-2.5 flex gap-1.5">
            <button className="inline-flex min-h-8 flex-1 items-center justify-center gap-1 rounded-full bg-[#f4f4f1] px-2 text-[11px] font-medium transition hover:bg-[#eaeae5] dark:bg-white/5 dark:hover:bg-white/10" onClick={() => onEdit(output)}><EditIcon className="h-3 w-3" />继续修改</button>
            <button aria-label={`下载图片 ${output.number ?? ''}`} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-black/[0.07] transition hover:bg-black/[0.04] dark:border-white/10 dark:hover:bg-white/5" onClick={() => void downloadAuthenticatedFile(output.download_url, output.filename).catch((error) => onError(error.message))}><DownloadIcon className="h-3.5 w-3.5" /></button>
          </div>
        </div>
      </article>)}
    </div>
    {preview && <div role="dialog" aria-label="查看图片" className="fixed inset-0 z-50 flex flex-col bg-[#11110f]/95 text-white backdrop-blur-md" onClick={() => setPreview(null)}>
      <div className="flex min-h-16 items-center justify-between gap-3 px-4 sm:px-6" onClick={(event) => event.stopPropagation()}>
        <div className="min-w-0"><p className="truncate text-sm font-medium">{preview.filename}</p><p className="mt-0.5 text-xs text-white/50">{preview.width}×{preview.height} · v{preview.version}</p></div>
        <div className="flex shrink-0 items-center gap-2">
          <button className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-white/15 px-3 text-xs hover:bg-white/10" onClick={() => void downloadAuthenticatedFile(preview.download_url, preview.filename).catch((error) => onError(error.message))}><DownloadIcon className="h-4 w-4" />下载</button>
          <button aria-label="关闭图片预览" className="inline-flex h-9 w-9 items-center justify-center rounded-full hover:bg-white/10" onClick={() => setPreview(null)}><CloseIcon className="h-5 w-5" /></button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center p-3 pb-6 sm:p-6" onClick={(event) => event.stopPropagation()}><AuthenticatedImage src={preview.content_url} alt="生成结果大图" className="max-h-full max-w-full object-contain" /></div>
    </div>}
  </section>
}
