import type {ServerJob,ServerJobBatch} from './jobsApi'
export type TaskFilter='all'|'active'|'succeeded'|'failed'|'cancelled'|'paused'
const active=new Set(['pending','dispatched','waiting_for_resource','running','retry_waiting','queued','dispatching','waiting_resource','retrying'])
export function taskStatusGroup(status:string):Exclude<TaskFilter,'all'>|'other'{
  if(status==='succeeded'||status==='partially_succeeded')return 'succeeded'
  if(status==='failed')return 'failed'
  if(status==='cancelled')return 'cancelled'
  if(status==='paused')return 'paused'
  return active.has(status)?'active':'other'
}
export function taskMetrics(batches:ServerJobBatch[],standalone:ServerJob[]){
  const jobs=[...new Map([...batches.flatMap(b=>b.jobs),...standalone].map(j=>[j.id,j])).values()]
  return {active:jobs.filter(j=>taskStatusGroup(j.status)==='active').length,
    succeeded:jobs.filter(j=>j.status==='succeeded').length,failed:jobs.filter(j=>j.status==='failed').length,
    cancelled:jobs.filter(j=>j.status==='cancelled').length,outputs:new Set(jobs.flatMap(j=>j.outputs.map(o=>o.id))).size}
}
