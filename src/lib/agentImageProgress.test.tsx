import {describe,it,expect,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {imageProgress,imageJobState} from './agentImageProgress'
import type {AgentRun} from './agentControlApi'
import AgentImageProgress from '../components/agent-control/AgentImageProgress'

function run(states:string[]):AgentRun{return {id:'r',conversation_id:'c',status:'waiting_jobs',revision:1,planner_mode:'existing_text',
  plan:null,result:{},events:[],error_code:null,state_signature:null,confirmation_token:null,workspace_url:null,
  jobs:states.map((status,i)=>({id:'j'+i,status,progress:80,error_code:null,capability:'image_edit',image_kind:'aplus'}))}}
describe('real image progress',()=>{
  it('ignores internal job percentage and treats dispatched tasks as queued',()=>{
    const r=run(['succeeded','succeeded','failed','running','dispatching','queued'])
    expect(imageProgress(r)).toMatchObject({percent:50,succeeded:2,failed:1,running:1,queued:2,ended:3,total:6})
    const html=renderToStaticMarkup(<AgentImageProgress run={r} busy={false}/>)
    expect(html).toContain('50%');expect(html).toContain('aria-valuenow="50"')
    expect(html).not.toContain('80%');expect(html).toContain('成功 2/6 张');expect(html).toContain('失败：1')
  })
  it('ends at 100 with failures rather than reporting all images successful',()=>{
    const p=imageProgress(run(['succeeded','failed','cancelled']))
    expect(p).toMatchObject({percent:100,succeeded:1,failed:1,cancelled:1})
  })
  it('keeps unknown outcome separate and does not offer retries',()=>{
    const r=run(['failed']);r.jobs[0].upstream_unknown=true;r.jobs[0].can_retry=true
    const html=renderToStaticMarkup(<AgentImageProgress run={r} busy={false} onRetry={vi.fn()}/>)
    expect(imageJobState(r.jobs[0])).toBe('unknown');expect(html).toContain('勿重复提交');expect(html).not.toContain('仅重新生成这张')
  })
  it('restores from job rows alone, deduplicates links, excludes text analysis',()=>{
    const r=run(['succeeded','queued']);r.jobs.push(r.jobs[0],{id:'text',status:'succeeded',progress:100,error_code:null,capability:'text_generation'})
    expect(imageProgress(JSON.parse(JSON.stringify(r)))).toMatchObject({percent:50,total:2})
  })
})
