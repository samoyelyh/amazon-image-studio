import {describe,expect,it} from 'vitest'
import type {ServerJob,ServerJobBatch} from './jobsApi'
import {taskMetrics,taskStatusGroup} from './taskPresentation'

describe('task filters and metrics',()=>{
  it.each([
    ['waiting_for_resource','active'],['retry_waiting','active'],['running','active'],
    ['succeeded','succeeded'],['partially_succeeded','succeeded'],['failed','failed'],
    ['cancelled','cancelled'],['paused','paused'],['remote_unknown','other'],['future-state','other'],
  ])('keeps %s separate from unrelated statuses',(status,group)=>expect(taskStatusGroup(status)).toBe(group))
  it('counts jobs and outputs only once, even if parent/child batch data overlaps',()=>{
    const jobs=[{id:'a',status:'running',outputs:[]},{id:'b',status:'succeeded',outputs:[{id:'o'}]},
      {id:'c',status:'cancelled',outputs:[]},{id:'d',status:'failed',outputs:[]}] as ServerJob[]
    const batches=[{jobs}, {jobs:[jobs[0],jobs[1]]}] as ServerJobBatch[]
    expect(taskMetrics(batches,[jobs[1]])).toEqual({active:1,succeeded:1,failed:1,cancelled:1,outputs:1})
  })
})
