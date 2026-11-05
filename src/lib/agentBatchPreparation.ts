import type {AgentRun} from './agentControlApi'

/** Hold only automatic import continuations; chat and image Jobs stay parallel. */
export function hasBatchPreparation(runs:AgentRun[]):boolean {
  return runs.some(run=>['planning','ready_to_submit','submitted','waiting_jobs'].includes(run.status)&&(
    run.status==='planning'||run.plan?.actions.some(a=>['plan_intent','analyze_chat_assets'].includes(a.tool))))
}

/** Receipt is a submitted input scope, never evidence that images succeeded. */
export function importWasSubmitted(runs:AgentRun[],key:string):boolean {
  return runs.some(run=>run.result.submitted_import_keys?.includes(key))
}
