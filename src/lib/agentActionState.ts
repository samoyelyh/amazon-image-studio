import type {AgentRun} from './agentControlApi'

export type ActionState='waiting'|'submitted'|'running'|'succeeded'|'failed'|'cancelled'|'remote_unknown'
const asyncTools=new Set(['plan_intent','suggest_creative_directions','generate_chat_images','generate_chat_tryon','submit_tryon_batch','generate_aplus','analyze_chat_assets','analyze_tryon_references','followup_batch_results'])
export const actionStateLabels:Record<ActionState,string>={waiting:'等待',submitted:'已提交',running:'运行中',succeeded:'成功',failed:'失败',cancelled:'已取消',remote_unknown:'上游未知'}

export function actionStates(run:AgentRun):Array<{state:ActionState;jobIds:string[]}> {
  const seen=new Map<string,number>()
  return (run.plan?.actions||[]).map((action,actionIndex)=>{
    const occurrence=seen.get(action.tool)||0;seen.set(action.tool,occurrence+1)
    const receipt=run.result.actions?.filter(r=>r.tool===action.tool)[occurrence]
    const result=receipt?.result
    const jobIds=[...new Set([
      ...(Array.isArray(result?.job_ids)?result.job_ids.filter((v):v is string=>typeof v==='string'):[]),
      ...['planning_job_id','suggestion_job_id'].flatMap(k=>typeof result?.[k]==='string'?[result[k] as string]:[]),
    ])]
    const linked=jobIds.map(id=>run.jobs.find(j=>j.id===id))
    let state:ActionState='waiting'
    if(jobIds.length){
      if(linked.some(j=>j?.status==='remote_unknown'||j?.error_code?.includes('remote_unknown')))state='remote_unknown'
      else if(linked.some(j=>j?.status==='failed'))state='failed'
      else if(linked.every(j=>j?.status==='succeeded'))state='succeeded'
      else if(linked.every(j=>j&&['succeeded','cancelled'].includes(j.status))&&linked.some(j=>j?.status==='cancelled'))state='cancelled'
      else if(linked.some(j=>j&&['running','dispatching'].includes(j.status)))state='running'
      else state='submitted'
    }else if(receipt){
      state=asyncTools.has(action.tool)?'submitted':'succeeded'
    }else{
      const events=run.events.filter(e=>e.payload.tool===action.tool&&e.payload.action_index===actionIndex)
      const terminal=events[events.length-1]
      if(terminal?.type==='tool_failed')state='failed'
      else if(terminal?.type==='tool_started')state='running'
      else if(run.status==='cancelled')state='cancelled'
    }
    return {state,jobIds}
  })
}
