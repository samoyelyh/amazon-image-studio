import {expect,it} from 'vitest'
import type {AgentRun} from './agentControlApi'
import {actionStates} from './agentActionState'

const run:AgentRun={id:'r',conversation_id:'c',status:'waiting_jobs',revision:1,planner_mode:'mock',
  plan:{schema_version:1,summary:'生成',actions:[{tool:'generate_chat_images',arguments:{}}],image_count:1,may_charge:true,cost_note:''},
  result:{actions:[{tool:'generate_chat_images',result:{job_ids:['a']}}]},error_code:null,state_signature:null,confirmation_token:null,events:[],jobs:[],workspace_url:null}
it('does not turn a receipt or completed run with missing job into image success',()=>{
  expect(actionStates({...run,status:'completed'})[0].state).toBe('submitted')
})
it('maps repeated tools by receipt occurrence, never all image jobs',()=>{
  const value={...run,plan:{...run.plan!,actions:[...run.plan!.actions,...run.plan!.actions]},
    result:{actions:[{tool:'generate_chat_images',result:{job_ids:['a']}},{tool:'generate_chat_images',result:{job_ids:['b']}}]},
    jobs:[{id:'a',status:'succeeded',progress:100,error_code:null},{id:'b',status:'failed',progress:0,error_code:'failed'}]}
  expect(actionStates(value).map(a=>a.state)).toEqual(['succeeded','failed'])
})
it.each([['queued','submitted'],['running','running'],['dispatching','running'],['succeeded','succeeded'],['failed','failed'],['cancelled','cancelled'],['remote_unknown','remote_unknown']])('maps job %s separately', (status,state)=>{
  expect(actionStates({...run,jobs:[{id:'a',status,progress:0,error_code:null}]})[0].state).toBe(state)
})
it('does not attribute unrelated text or old image failures to a successful image action',()=>{
  expect(actionStates({...run,jobs:[{id:'a',status:'succeeded',progress:100,error_code:null},
    {id:'old',status:'failed',progress:0,error_code:'failed',capability:'text_generation'}]})[0].state).toBe('succeeded')
})
it('read-only completed receipt succeeds, text generation waits for its own job',()=>{
  expect(actionStates({...run,plan:{...run.plan!,actions:[{tool:'read_shared_queue',arguments:{}}]},result:{actions:[{tool:'read_shared_queue',result:{}}]}})[0].state).toBe('succeeded')
  expect(actionStates({...run,plan:{...run.plan!,actions:[{tool:'plan_intent',arguments:{}}]},result:{actions:[{tool:'plan_intent',result:{planning_job_id:'a'}}]},jobs:[{id:'a',status:'running',progress:0,error_code:null}]})[0].state).toBe('running')
})
it('sample review approvals finish without image jobs, corrections wait for their own jobs',()=>{
 const value={...run,plan:{...run.plan!,actions:[{tool:'review_tryon_samples',arguments:{}}]}}
 expect(actionStates({...value,result:{actions:[{tool:'review_tryon_samples',result:{job_ids:[]}}]}})[0].state).toBe('succeeded')
 expect(actionStates({...value,result:{actions:[{tool:'review_tryon_samples',result:{job_ids:['a']}}]},jobs:[{id:'a',status:'running',progress:0,error_code:null}]})[0].state).toBe('running')
})
