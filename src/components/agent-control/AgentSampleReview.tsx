import {useState} from 'react'
import AuthenticatedImage from '../AuthenticatedImage'
import {agentRequestId,sendAgentChatMessage,type AgentProductionPlan,type AgentOutput} from '../../lib/agentControlApi'

const button='rounded-lg border px-3 py-2 text-xs disabled:opacity-40'
export default function AgentSampleReview({plan,conversationId,outputs,onRefresh,onError}:{plan:AgentProductionPlan;conversationId:string;outputs:AgentOutput[];onRefresh:()=>Promise<void>;onError:(s:string)=>void}){
 const [notes,setNotes]=useState<Record<number,string>>({}),[busy,setBusy]=useState(false)
 const catalog=plan.sample_catalog||Object.keys(plan.template_rules).map((tid,i)=>{
  const output=outputs.find(o=>o.job_id===plan.samples[tid])
  return {sample_number:i+1,template_id:tid,job_id:plan.samples[tid],output_id:output?.id,asset_id:output?.asset_id,status:output?'succeeded':'queued',approved:!!plan.sample_approvals[tid],notes:''}
 })
 async function review(sample:typeof catalog[number],decision:'approve'|'revise'|'redo'){
  if(!sample.output_id&&!(sample.status==='failed'&&decision==='redo'))return
  setBusy(true)
  try{
   await sendAgentChatMessage(conversationId,{content:`样图 ${sample.sample_number}${decision==='approve'?'通过':decision==='redo'?'重做':`修改：${notes[sample.sample_number]||''}`}`,
    client_request_id:agentRequestId(),attachment_ids:[],sample_review:{plan_id:plan.id,expected_revision:plan.revision,expected_review_revision:plan.review_revision,
     decisions:[{sample_number:sample.sample_number,...(sample.output_id?{output_id:sample.output_id}:{}),decision,notes:notes[sample.sample_number]||''}]}})
   await onRefresh()
  }catch(e){onError(e instanceof Error?e.message:'样图操作失败')}finally{setBusy(false)}
 }
 return <div aria-label="样图审核" className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{catalog.filter(s=>s.job_id).map(s=><article key={s.template_id} className="overflow-hidden rounded-xl border bg-white">
  <div className="flex items-center justify-between px-3 py-2 text-sm"><span>样图 {s.sample_number}</span><span>{s.approved?'已通过':s.status==='succeeded'?'待审核':s.status==='failed'?'生成失败':s.status==='cancelled'?'已取消':s.status==='remote_unknown'?'上游状态待核对':'生成中'}</span></div>
  {s.asset_id&&<div className="h-52 w-full"><AuthenticatedImage src={`/api/v1/assets/${s.asset_id}/content`} alt={`样图 ${s.sample_number}`} className="h-full w-full object-contain"/></div>}
  {s.status==='failed'&&!s.output_id&&<button className={`${button} m-3`} disabled={busy} onClick={()=>void review(s,'redo')}>仅重试这张样图</button>}
  {s.output_id&&<div className="space-y-2 p-3"><input aria-label={`样图 ${s.sample_number} 修改要求`} className="w-full rounded-lg border p-2 text-sm" placeholder={s.notes||'哪里需要调整？也可以直接在聊天中说'} value={notes[s.sample_number]||''} onChange={e=>setNotes({...notes,[s.sample_number]:e.target.value})}/>
   <div className="flex flex-wrap gap-2"><button className={button} disabled={busy||s.approved} onClick={()=>void review(s,'approve')}>{s.approved?'已通过':'通过'}</button><button className={button} disabled={busy||!notes[s.sample_number]?.trim()} onClick={()=>void review(s,'revise')}>按要求修改</button><button className={button} disabled={busy} onClick={()=>void review(s,'redo')}>重做</button></div>
  </div>}
 </article>)}</div>
}
