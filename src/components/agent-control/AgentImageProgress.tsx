import type {AgentRun} from '../../lib/agentControlApi'
import {imageProgress,imageJobState} from '../../lib/agentImageProgress'

const labels={queued:'排队中',running:'生成中',succeeded:'成功',failed:'失败',cancelled:'已取消',unknown:'上游状态未知'}
export default function AgentImageProgress({run,busy,onRetry,retriedIds=[]}:{run:AgentRun;busy:boolean;onRetry?:(jobId:string)=>void;retriedIds?:string[]}){
  const p=imageProgress(run)
  if(!p.total)return null
  const kind=p.jobs.some(j=>j.image_kind==='aplus')?'Amazon A+ 图片':p.jobs.some(j=>j.image_kind==='listing')?'Listing 图片':'图片'
  return <section aria-label="图片生成进度" className="mt-4 rounded-2xl border border-stone-200 bg-stone-50/70 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{p.ended===p.total?`${kind}任务已结束`:`正在生成${kind}`}</h3><strong className="text-lg tabular-nums">{p.percent}%</strong></div>
    <div role="progressbar" aria-label="图片任务整体进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p.percent} className="mt-3 h-2 overflow-hidden rounded-full bg-stone-200"><div className={`h-full rounded-full transition-[width] ${p.failed||p.unknown?'bg-amber-600':'bg-emerald-600'}`} style={{width:`${p.percent}%`}}/></div>
    <p className="mt-2 text-sm tabular-nums">成功 {p.succeeded}/{p.total} 张 · 已结束 {p.ended}/{p.total} 个任务</p>
    <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm"><span>排队中：{p.queued}</span><span>生成中：{p.running}</span><span>成功：{p.succeeded}</span><span className={p.failed?'text-red-700':''}>失败：{p.failed}</span>{p.cancelled>0&&<span>已取消：{p.cancelled}</span>}{p.unknown>0&&<span className="text-amber-800">上游未知：{p.unknown}，请核对，勿重复提交</span>}</div>
    <details className="mt-3 text-sm"><summary className="cursor-pointer">查看每张图片状态</summary><ul className="mt-2 max-h-60 space-y-2 overflow-y-auto">{p.jobs.map((job,index)=>{
      const state=imageJobState(job),retried=retriedIds.includes(job.id)
      return <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2"><span className="min-w-0 break-words">{index+1}. {job.label||'图片'} · {labels[state]}</span>{state==='failed'&&job.can_retry&&onRetry&&(retried?<span className="text-stone-600">已创建单张重试，见后续消息</span>:<button className="min-h-9 rounded-full border px-3 font-medium hover:bg-stone-100 disabled:opacity-40" disabled={busy} onClick={()=>onRetry(job.id)}>仅重新生成这张</button>)}</li>
    })}</ul></details>
  </section>
}
