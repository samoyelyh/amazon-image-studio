import {useState} from 'react'
import type {AgentRun,AgentPrompt} from '../../lib/agentControlApi'
import {copyTextToClipboard} from '../../lib/clipboard'
import {StudioButton} from '../ui/Studio'

const labels:Record<AgentPrompt['source'],string>={planner:'AI 规划指令',plan:'生成方案',submitted:'已提交任务 Prompt',executed:'最终实际执行 Prompt',user:'修改版本'}
export default function AgentPromptPanel({run,busy,onSave,onGenerate,onError}:{run:AgentRun;busy:boolean;onSave:(source:AgentPrompt,content:string)=>Promise<AgentRun>;onGenerate:(version:AgentPrompt)=>void;onError:(text:string)=>void}){
  const [selected,setSelected]=useState(''),[draft,setDraft]=useState(''),[editing,setEditing]=useState(false),[copied,setCopied]=useState(false),[saving,setSaving]=useState(false)
  const prompts=run.prompts||[]
  if(!prompts.length)return null
  const current=prompts.find(p=>p.id===selected)||prompts[prompts.length-1]
  const canGenerate=current.source==='user'&&current.replayable===true
  return <details aria-label="执行提示词" className="mt-3 rounded-xl border border-black/[0.06] p-3 dark:border-white/10">
    <summary className="cursor-pointer text-xs text-gray-500">提示词与调用详情</summary>
    <div className="mt-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">执行提示词</h3>
      <select aria-label="提示词历史版本" className="studio-input max-w-full text-xs sm:w-auto" value={current.id} onChange={e=>{setSelected(e.target.value);setEditing(false);setCopied(false)}}>
        {prompts.map(p=><option key={p.id} value={p.id}>{labels[p.source]}{p.version?` · V${p.version}`:''}{p.job_id?` · ${p.job_id.slice(0,8)}`:''}</option>)}
      </select></div>
    <details className="mt-3"><summary className="cursor-pointer text-sm">展开完整 Prompt</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-stone-50 p-3 text-sm leading-6">{current.content}</pre></details>
    {!editing&&<p className="mt-2 line-clamp-2 whitespace-pre-wrap break-words text-sm leading-6 text-stone-700">{current.content}</p>}
    {editing&&<label className="mt-3 block text-sm">编辑为新版本<textarea aria-label="编辑提示词" className="studio-input mt-2 min-h-40 resize-y" maxLength={10000} value={draft} onChange={e=>setDraft(e.target.value)}/></label>}
    <div className="mt-3 flex flex-wrap gap-2">
      <StudioButton onClick={()=>void copyTextToClipboard(current.content).then(()=>setCopied(true)).catch(()=>onError('复制失败，请展开并手动复制提示词。'))}>{copied?'已复制':'复制 Prompt'}</StudioButton>
      {!editing&&<StudioButton disabled={busy} onClick={()=>{setDraft(current.content);setEditing(true)}}>编辑</StudioButton>}
      {editing&&<><StudioButton disabled={busy||saving||!draft.trim()} onClick={()=>{
        setSaving(true);void onSave(current,draft.trim()).then(next=>{const saved=[...(next.prompts||[])].reverse().find(p=>p.source==='user');if(saved)setSelected(saved.id);setEditing(false)}).catch(e=>onError(e.message)).finally(()=>setSaving(false))
      }}>{saving?'正在保存…':'保存为新版本'}</StudioButton><StudioButton disabled={saving} onClick={()=>setEditing(false)}>取消编辑</StudioButton></>}
      {canGenerate&&!editing&&<StudioButton variant="primary" disabled={busy} onClick={()=>onGenerate(current)}>用此版本生成</StudioButton>}
    </div>
    {editing&&<p className="mt-2 text-sm text-stone-600">保存新版本不会覆盖已提交任务；需要采用时点击“用此版本生成”。</p>}
    </div>
  </details>
}
