import type {AgentRun} from './agentControlApi'
import type {AmazonPlanRecord} from './amazonAgentApi'

/** Keep the live plan beside its original design reply, never in a global footer. */
export function amazonCardRunId(runs:AgentRun[],record:AmazonPlanRecord){
 const oldestFirst=[...runs].reverse()
 const created=oldestFirst.find(r=>r.result.actions?.some(a=>a.tool==='save_aplus_plan'&&a.result.amazon_plan_id===record.id))
 if(created)return created.id
 const jobs=new Set(record.submissions.flatMap(s=>s.job_ids))
 return oldestFirst.find(r=>r.result.actions?.some(a=>a.result.amazon_plan_id===record.id)
  ||r.plan?.actions.some(a=>a.arguments.plan_id===record.id)
  ||r.outputs?.some(o=>o.amazon_module?.plan_id===record.id)
  ||r.jobs.some(j=>jobs.has(j.id)))?.id
}

/** Native plan-only replies use needs_input while waiting for the next chat turn. */
export function isSavedAmazonDraft(run:AgentRun,records:AmazonPlanRecord[]){
 return run.planner_mode==='dsh-native'&&run.status==='needs_input'&&!run.error_code
  &&run.plan?.image_count===0&&!run.plan.needs_input?.length&&!run.plan.blocked_reason
  &&!!run.result.actions?.some(a=>a.tool==='save_aplus_plan'&&!a.result.error_code
   &&records.some(p=>p.id===a.result.amazon_plan_id&&!p.findings.length&&!p.submissions.length))
}
