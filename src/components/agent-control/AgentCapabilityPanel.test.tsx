import {expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {AgentToolTrace} from './AgentCapabilityPanel'
import type {AgentRun} from '../../lib/agentControlApi'

const run:AgentRun={id:'run',conversation_id:'chat',status:'completed',revision:1,planner_mode:'mock',plan:null,result:{},
  error_code:null,state_signature:null,confirmation_token:null,events:[],jobs:[],workspace_url:null}
it('shows selected skill and actual tool call records without adding an execution button',()=>{
  const html=renderToStaticMarkup(<AgentToolTrace run={{...run,events:[
    {id:'selected',type:'capabilities_selected',payload:{skills:[{id:'asset-search',version:'1'}]},created_at:'now'},
    {id:'call',type:'capability_call_finished',payload:{capability_id:'business.search_my_assets',status:'succeeded',result:{count:1}},created_at:'now'},
  ]}}/>)
  expect(html).toContain('asset-search')
  expect(html).toContain('business.search_my_assets')
  expect(html).toContain('succeeded')
  expect(html).not.toContain('<button')
})
it('renders tool-result injection as escaped data, not HTML',()=>{
  const html=renderToStaticMarkup(<AgentToolTrace run={{...run,events:[{id:'call',type:'capability_call_finished',
    payload:{content:'<script>deleteEverything()</script>',trust:'untrusted_external_data'},created_at:'now'}]}}/>)
  expect(html).not.toContain('<script>')
  expect(html).toContain('&lt;script&gt;')
})
it('does not invent a tool trace for legacy runs',()=>{
  expect(renderToStaticMarkup(<AgentToolTrace run={run}/>)).toBe('')
})
