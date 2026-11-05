import type {AgentRun} from './agentControlApi'

export type ImageJob=AgentRun['jobs'][number]
export const activeImageStatuses=new Set(['queued','waiting_for_resource','dispatching','running','retry_waiting'])
export function imageJobState(job:ImageJob){
  if(job.upstream_unknown||job.status==='remote_unknown'||(job.status==='failed'&&/timeout|network|remote_unknown|524/.test(job.error_code||'')))return 'unknown'
  if(job.status==='succeeded')return 'succeeded'
  if(job.status==='failed')return 'failed'
  if(job.status==='cancelled')return 'cancelled'
  return job.status==='running'?'running':'queued'
}
export function imageProgress(run:AgentRun){
  const jobs=[...new Map(run.jobs.filter(j=>j.capability!=='text_generation').map(j=>[j.id,j])).values()]
  const counts={succeeded:0,failed:0,cancelled:0,unknown:0,running:0,queued:0}
  for(const job of jobs)counts[imageJobState(job)]++
  const ended=counts.succeeded+counts.failed+counts.cancelled+counts.unknown
  // Job.progress is internal processing stage (e.g. download/storage), not a
  // Provider's actual image percentage. No clock-based or per-image fake %.
  return {jobs,...counts,total:jobs.length,ended,percent:jobs.length?Math.round(100*ended/jobs.length):0,source:'finished_jobs' as const}
}
