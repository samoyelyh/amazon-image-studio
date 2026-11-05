import {useEffect,useRef,useState} from 'react'
import AgentSampleReview from './AgentSampleReview'
import {downloadAuthenticatedFile,withPartialExportConfirmation} from '../../lib/serverDownloads'
import {agentRequestId,confirmAgentProductionRules,saveAgentProductionRules,sendAgentChatMessage,
  type AgentProductionPlan,type AgentOutput,type AgentAttachment,type AssetUnderstanding,type AgentRun} from '../../lib/agentControlApi'

// Conversation API returns runs newest-first. Keep one live editor per persisted plan.
export function productionCardRunId(runs:Array<Pick<AgentRun,'id'|'result'>>,planId:string){
  return runs.find(r=>r.result.actions?.some(a=>a.result.production_plan_id===planId))?.id
}

const button='rounded-lg border px-3 py-2 text-xs disabled:opacity-40 dark:border-white/15'
export default function AgentProductionCard({plan,conversationId,attachments,outputs,onRefresh,onError}:{plan:AgentProductionPlan;conversationId:string;attachments:AgentAttachment[];outputs:AgentOutput[];onRefresh:()=>Promise<void>;onError:(m:string)=>void}){
  const [draft,setDraft]=useState(plan),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false)
  const [override,setOverride]=useState({template_asset_id:'',garment_asset_id:'',instruction:''})
  const [exportTemplate,setExportTemplate]=useState(''),[exportGarment,setExportGarment]=useState('')
  const [fontChoice,setFontChoice]=useState('')
  const keys=useRef<Record<string,string>>({})
  useEffect(()=>{setDraft(plan);setDirty(false)},[plan.id,plan.revision])
  const names=new Map(attachments.map(a=>[a.asset_id,a.filename]))
  plan.input_manifest?.garments.forEach(g=>names.set(g.id,g.label))
  const remaining=Math.max(0,plan.combination_count-(plan.submitted_count||0))
  const anyApproved=Object.keys(plan.sample_approvals).length>0
  const sampleReady=(plan.sample_required_template_ids?.length?plan.sample_required_template_ids:Object.keys(plan.template_rules)).every(id=>!!plan.sample_approvals[id])
  async function act(action:()=>Promise<unknown>){setBusy(true);try{await action();await onRefresh()}catch(e){onError(e instanceof Error?e.message:'操作失败')}finally{setBusy(false)}}
  function change(next:AgentProductionPlan){setDraft(next);setDirty(true)}
  async function confirmRules(){const saved=await saveAgentProductionRules(conversationId,draft);await confirmAgentProductionRules(conversationId,saved)}
  async function exportResults(){return withPartialExportConfirmation(partial=>{
    const params=new URLSearchParams({allow_partial:String(partial)})
    if(exportTemplate)params.set('template_asset_id',exportTemplate)
    if(exportGarment)params.set('garment_id',exportGarment)
    return downloadAuthenticatedFile(`/agent/conversations/${conversationId}/production-plans/${plan.id}/archive?${params}`,'批量换衣结果.zip')
  })}
  function assign(id:string,role:'template'|'garment'){
    const original=draft.template_rules[id]||draft.garment_rules[id]||{role,confidence:1,template_type:'pure_white',view:'auto',protected_elements:[],allowed_changes:[],visual_facts:[],uncertainties:[]}
    const t={...draft.template_rules},g={...draft.garment_rules};delete t[id];delete g[id]
    ;(role==='template'?t:g)[id]={...original,role}
    change({...draft,template_rules:t,garment_rules:g,unresolved_asset_ids:draft.unresolved_asset_ids.filter(a=>a!==id)})
  }
  async function start(stage:'validation'|'production'){
    const key=`${plan.id}:${plan.revision}:${plan.review_revision}:${plan.submitted_count}:${stage}`
    keys.current[key]??=agentRequestId()
    await sendAgentChatMessage(conversationId,{content:stage==='validation'?'按当前已确认规则生成样图验证':'按当前已审核样图进行正式批量套图',
      client_request_id:keys.current[key],attachment_ids:[],production_plan_id:plan.id,production_revision:plan.revision,production_stage:stage,production_approved_only:stage==='production'&&!!plan.sample_review_required})
  }
  function ruleEditor(id:string,rule:AssetUnderstanding,kind:'template_rules'|'garment_rules'){
    return <div key={id} className="rounded-lg border p-2 text-xs dark:border-white/10"><p className="truncate">{names.get(id)||id}</p>
      <select aria-label={`${names.get(id)||id} 识别角色`} disabled={!!plan.input_manifest} title={plan.input_manifest?'在整理素材与关联中修改角色':undefined} value={rule.role} onChange={e=>assign(id,e.target.value as 'template'|'garment')} className="mt-2 bg-transparent"><option value="template">模板</option><option value="garment">服装</option></select>
      <p className="mt-1 text-gray-500">置信度 {Math.round(rule.confidence*100)}% · {rule.view}</p>
      {kind==='template_rules'&&<select aria-label={`${names.get(id)||id} 模板类型`} className="mt-2 bg-transparent" value={rule.template_type} onChange={e=>change({...draft,[kind]:{...draft[kind],[id]:{...rule,template_type:e.target.value}}})}>{[['pure_white','纯白底'],['gift_scene','礼品场景'],['stadium_scene','观赛场景'],['detail_display','细节展示'],['casual_scene','休闲场景'],['custom_process','定制流程']].map(([v,t])=><option key={v} value={v}>{t}</option>)}</select>}
      <select aria-label={`${names.get(id)||id} 展示面`} className="ml-2 mt-2 bg-transparent" value={rule.view} onChange={e=>change({...draft,[kind]:{...draft[kind],[id]:{...rule,view:e.target.value}}})}>{[['auto','自动'],['front','正面'],['back','背面'],['front_back','正背面'],['detail','细节']].map(([v,t])=><option key={v} value={v}>{t}</option>)}</select>
      <textarea aria-label={`${names.get(id)||id} 保持规则`} className="mt-2 min-h-16 w-full rounded border bg-transparent p-2 dark:border-white/10" value={rule.protected_elements.join('\n')}
        onChange={e=>change({...draft,[kind]:{...draft[kind],[id]:{...rule,protected_elements:e.target.value.split('\n')}}})}/>
      <p className="text-gray-500">{rule.visual_facts.join('；')}</p>{rule.uncertainties.length>0&&<p className="text-amber-600">待核对：{rule.uncertainties.join('；')}</p>}</div>
  }
  return <section aria-label="聊天内套图规则与样图" className="my-4 rounded-2xl border bg-white p-4 dark:border-white/10 dark:bg-gray-900">
    <h3 className="text-sm font-medium">素材理解与批量套图</h3><p className="mt-2 text-xs text-gray-500">{Object.keys(draft.template_rules).length} 个模板 · {Object.keys(draft.garment_rules).length} 件服装 · {plan.combination_count} 张图片 · 规则 v{plan.revision}</p>
    <p className="my-2 text-sm">{plan.unresolved_asset_ids.length?'请补充素材关联':'规则已就绪'}{(plan.sample_review_required||Object.keys(plan.samples).length>0)&&` · 样图 ${Object.keys(plan.sample_approvals).length}/${Object.keys(plan.template_rules).length}`}</p>
    {draft.unresolved_asset_ids.map(id=><div key={id} className="my-2 text-xs text-amber-600">{names.get(id)||id} 角色待确认 <button className={button} onClick={()=>assign(id,'template')}>设为模板</button> <button className={button} onClick={()=>assign(id,'garment')}>设为服装</button></div>)}
    <details className="my-3 text-sm"><summary>查看与调整替换规则</summary><label className="text-xs">通用替换要求<textarea aria-label="通用换衣要求" className="my-2 min-h-28 w-full rounded-xl border bg-transparent p-3 text-xs dark:border-white/10" value={draft.common_prompt} onChange={e=>change({...draft,common_prompt:e.target.value})}/></label>
      {Object.entries(draft.template_prompts||{}).map(([tid,prompt])=><label key={tid} className="my-3 block text-sm">{names.get(tid)||tid} · 通用换衣提示词<textarea aria-label={`${names.get(tid)||tid} 通用换衣提示词`} className="my-2 min-h-36 w-full rounded-xl border bg-transparent p-3 text-sm" value={prompt} onChange={e=>change({...draft,template_prompts:{...draft.template_prompts,[tid]:e.target.value}})}/></label>)}
    <details className="my-3 text-sm"><summary>模板 / 服装规则</summary><div className="mt-2 grid max-h-80 gap-2 overflow-auto sm:grid-cols-2">{Object.entries(draft.template_rules).map(([id,r])=>ruleEditor(id,r,'template_rules'))}{Object.entries(draft.garment_rules).map(([id,r])=>ruleEditor(id,r,'garment_rules'))}</div></details>
    <details className="my-3 text-xs"><summary>特殊组合调整 · {draft.combination_overrides.length}</summary><div className="mt-2 flex flex-wrap gap-2"><select aria-label="组合模板" className="max-w-48 bg-transparent" value={override.template_asset_id} onChange={e=>setOverride({...override,template_asset_id:e.target.value})}><option value="">选择模板</option>{Object.keys(draft.template_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select><select aria-label="组合服装" className="max-w-48 bg-transparent" value={override.garment_asset_id} onChange={e=>setOverride({...override,garment_asset_id:e.target.value})}><option value="">选择服装</option>{Object.keys(draft.garment_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select><input aria-label="组合附加要求" className="rounded border bg-transparent p-2 dark:border-white/10" value={override.instruction} onChange={e=>setOverride({...override,instruction:e.target.value})}/><button className={button} disabled={!override.template_asset_id||!override.garment_asset_id||!override.instruction.trim()} onClick={()=>{change({...draft,combination_overrides:[...draft.combination_overrides,override]});setOverride({...override,instruction:''})}}>加入当前组合</button></div>{draft.combination_overrides.map((o,i)=><p key={i} className="mt-2">{names.get(o.template_asset_id)} × {names.get(o.garment_asset_id)}：{o.instruction}</p>)}</details>
    {plan.input_manifest&&<details className="my-3 text-xs"><summary>指定组合字体图</summary><div className="mt-2 flex flex-wrap gap-2"><select aria-label="字体覆盖模板" value={override.template_asset_id} onChange={e=>setOverride({...override,template_asset_id:e.target.value})}><option value="">选择模板</option>{Object.keys(draft.template_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select><select aria-label="字体覆盖服装" value={override.garment_asset_id} onChange={e=>setOverride({...override,garment_asset_id:e.target.value})}><option value="">选择服装</option>{Object.keys(draft.garment_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select><select aria-label="当前组合图C" value={fontChoice} onChange={e=>setFontChoice(e.target.value)}><option value="">选择字体参考</option>{plan.input_manifest.entries.filter(e=>e.role==='font').map(e=><option key={e.asset_id} value={e.asset_id}>{e.filename}</option>)}</select><button className={button} disabled={!override.template_asset_id||!override.garment_asset_id||!fontChoice} onClick={()=>{
      const prior=draft.combination_overrides.find(o=>o.template_asset_id===override.template_asset_id&&o.garment_asset_id===override.garment_asset_id)
      change({...draft,combination_overrides:[...draft.combination_overrides.filter(o=>o!==prior),{...override,instruction:prior?.instruction||'本组合使用指定图C，其余商品设计不变。',font_reference_asset_id:fontChoice}]})
    }}>应用到当前组合</button></div></details>}
    </details><div className="flex flex-wrap gap-2">
      {dirty&&<button className={button} disabled={busy||draft.unresolved_asset_ids.length>0} onClick={()=>void act(confirmRules)}>保存规则调整</button>}
      <button className={button} disabled={busy||dirty||draft.unresolved_asset_ids.length>0} onClick={()=>void act(()=>start('validation'))}>生成样图</button>
      <button className={`${button} bg-blue-600 text-white`} disabled={busy||dirty||draft.unresolved_asset_ids.length>0||(plan.sample_review_required&&!anyApproved)||remaining===0} onClick={()=>void act(()=>start('production'))}>{remaining===0?'本批已全部提交':plan.sample_review_required&&!sampleReady?'生产已通过的模板':`批量生成剩余 ${remaining} 张`}</button>
      {plan.production_batch_id&&<button className={button} disabled={busy} onClick={()=>void act(exportResults)}>导出本批结果</button>}
    </div>
    {plan.production_batch_id&&<div className="mt-2 flex flex-wrap gap-2"><select aria-label="导出模板范围" className="max-w-60 rounded border p-2 text-xs" value={exportTemplate} onChange={e=>setExportTemplate(e.target.value)}><option value="">全部模板</option>{Object.keys(plan.template_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select><select aria-label="导出服装范围" className="max-w-60 rounded border p-2 text-xs" value={exportGarment} onChange={e=>setExportGarment(e.target.value)}><option value="">全部服装</option>{Object.keys(plan.garment_rules).map(id=><option key={id} value={id}>{names.get(id)||id}</option>)}</select></div>}
    <AgentSampleReview plan={plan} conversationId={conversationId} outputs={outputs} onRefresh={onRefresh} onError={onError}/>
    {dirty&&<p className="mt-2 text-xs text-amber-600">规则已修改，请保存调整；已提交的历史图片不会覆盖。</p>}
  </section>
}
