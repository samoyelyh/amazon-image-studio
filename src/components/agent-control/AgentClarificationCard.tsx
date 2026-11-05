import {useState} from 'react'
import type {AgentRun} from '../../lib/agentControlApi'
import {chatButton} from './AgentChatCards'
import {StudioButton} from '../ui/Studio'

export function AgentClarificationCard({run,busy,answered,onReply,onSuggest,enabled=true}:{run:AgentRun;busy:boolean;answered:boolean;onReply:(text:string)=>void;onSuggest:()=>void;enabled?:boolean}){
  const [answer,setAnswer]=useState('')
  const [reopen,setReopen]=useState(false)
  if(!['needs_input','awaiting_clarification'].includes(run.status))return null
  if(!enabled)return <p role="status" className="mt-3 text-sm text-amber-800">当前服务尚未启用补充说明与 AI 建议。</p>
  return <section aria-label="补充说明" className="mt-4 rounded-2xl border border-stone-200 bg-white p-4">
    <h3 className="text-sm font-semibold text-stone-900">{answered?'已发送补充说明':'补充说明'}</h3>
    {answered&&!reopen&&<button type="button" className={`${chatButton} mt-2`} onClick={()=>setReopen(true)}>再次补充</button>}
    {(!answered||reopen)&&<form onSubmit={e=>{e.preventDefault();if(answer.trim()&&!busy)onReply(answer.trim())}}>
      <textarea aria-label="填写补充说明" value={answer} maxLength={6000} rows={3} onChange={e=>setAnswer(e.target.value)}
        onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.nativeEvent.isComposing){e.preventDefault();if(answer.trim()&&!busy)onReply(answer.trim())}}}
        placeholder="填写你的选择或要求，也可以让 AI 先给你几个方向…" className="mt-3 w-full resize-y rounded-xl border border-stone-300 bg-stone-50 p-3 text-sm text-stone-900 outline-none focus:border-stone-700"/>
      <div className="mt-3 flex flex-wrap gap-2"><StudioButton type="submit" variant="primary" disabled={busy||!answer.trim()}>补充并继续</StudioButton>
        <StudioButton disabled={busy} onClick={onSuggest}>让 AI 给我建议</StudioButton></div>
    </form>}
  </section>
}

export function AgentSuggestionsCard({run,busy,onAdopt}:{run:AgentRun;busy:boolean;onAdopt:(text:string)=>void}){
  const suggestions=run.result.creative_suggestions
  const [edited,setEdited]=useState<Record<number,string>>({})
  if(!suggestions)return null
  return <section aria-label="AI 创作建议" className="mt-4 space-y-3"><h3 className="text-sm font-semibold">{suggestions.summary}</h3>
    {suggestions.options.map((option,index)=><article key={index} className="rounded-2xl border border-stone-200 bg-white p-4">
      <h4 className="text-sm font-medium">{option.title}</h4>
      <textarea aria-label={`编辑建议 ${index+1}`} rows={3} maxLength={6000} value={edited[index]??option.instruction}
        onChange={e=>setEdited(old=>({...old,[index]:e.target.value}))} className="mt-2 w-full resize-y rounded-xl border border-stone-200 bg-stone-50 p-3 text-sm"/>
      <button type="button" disabled={busy||!(edited[index]??option.instruction).trim()} onClick={()=>onAdopt((edited[index]??option.instruction).trim())} className={chatButton}>采用此方案并继续</button>
    </article>)}
  </section>
}
