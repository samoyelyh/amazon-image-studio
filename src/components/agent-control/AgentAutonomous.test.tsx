import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {MemoryRouter} from 'react-router-dom'
import {AgentPlanCard} from './AgentChatCards'
import AgentPromptPanel from './AgentPromptPanel'
import {AgentClarificationCard} from './AgentClarificationCard'
import type {AgentRun,AgentStatus} from '../../lib/agentControlApi'
const run:AgentRun={id:'r',conversation_id:'c',status:'waiting_jobs',revision:3,planner_mode:'existing_text',
  plan:{schema_version:1,summary:'生成模特展示图',workflow:'fast',actions:[{tool:'generate_chat_images',arguments:{prompt:'保持球衣颜色和号码'}}],image_count:1,may_charge:true,cost_note:'不应展示的费用审批',budget:{sufficient:true,estimated_cost:10}},
  result:{},error_code:null,state_signature:null,confirmation_token:null,events:[],jobs:[{id:'j',status:'queued',progress:0,error_code:null,capability:'image_edit'}],workspace_url:null,
  prompts:[{id:'plan',version:1,source:'plan',content:'保持球衣颜色和号码'},{id:'job-j',version:0,source:'executed',job_id:'j',content:'保持球衣颜色和号码。输出真实摄影图片。'}]}
const status:AgentStatus={enabled:true,writes_enabled:true,model_calls_enabled:true,checkpoint_configured:true,planner_mode:'existing_text',auto_execution:{enabled:true,mode:'autonomous',max_images:3,max_seconds:300,max_credits:50,max_active_runs:3,submissions_per_minute:6}}
it('ordinary async creation displays progress without fee, quota or model approval',()=>{
  const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={run} status={status} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
  for(const phrase of ['确认费用','确认消耗','是否允许','这次创作需要你确认','预计平台额度','不应展示的费用审批'])expect(html).not.toContain(phrase)
  expect(html).toContain('成功 0/1 张')
})
it('shows a text-planning timeout separately from an actual image generation failure',()=>{
 const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={{...run,status:'remote_unknown',error_code:'agent.remote_unknown',
  result:{execution_error:'素材分析或需求规划的上游请求超时，返回状态未知；本轮尚未提交图片生成，不会自动重复请求。'},
  jobs:[{id:'text',status:'failed',capability:'text_generation',progress:0,error_code:'job.max_attempts'}]}} status={status} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
 expect(html).toContain('本轮尚未提交图片生成')
 expect(html).not.toContain('上游状态未知，请勿重复生成。')
})
it('only explicit plan review offers the review action, without a cost dialog',()=>{
  const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={{...run,status:'awaiting_review',confirmation_token:'x',state_signature:'y'}} status={status} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
  expect(html).toContain('方案待审核');expect(html).toContain('方案通过，开始生成');expect(html).not.toContain('预计平台额度')
})
it('shows actual final prompt, full expansion, copy and version edit without blocking generation',()=>{
  const save=vi.fn(),generate=vi.fn()
  const html=renderToStaticMarkup(<AgentPromptPanel run={run} busy={false} onSave={save} onGenerate={generate} onError={vi.fn()}/>)
  expect(html).toContain('执行提示词');expect(html).toContain('最终实际执行 Prompt');expect(html).toContain('展开完整 Prompt');expect(html).toContain('复制 Prompt');expect(html).toContain('编辑')
  expect(html).toContain('保持球衣颜色和号码。输出真实摄影图片。');expect(save).not.toHaveBeenCalled();expect(generate).not.toHaveBeenCalled()
})
it('genuine clarification retains a real input instead of exposing internal state codes',()=>{
  const html=renderToStaticMarkup(<AgentClarificationCard run={{...run,status:'awaiting_clarification'}} answered={false} busy={false} onReply={vi.fn()} onSuggest={vi.fn()}/>)
  expect(html).toContain('填写补充说明');expect(html).toContain('补充并继续');expect(html).not.toContain('awaiting_clarification')
})
it('a saved ordinary-chat prompt can generate a new task without mutating the old one',()=>{
  const generate=vi.fn()
  const html=renderToStaticMarkup(<AgentPromptPanel run={{...run,prompts:[{id:'v2',version:2,source:'user',content:'编辑后的白底图提示词',replayable:true}]}} busy={false} onSave={vi.fn()} onGenerate={generate} onError={vi.fn()}/>)
  expect(html).toContain('用此版本生成');expect(generate).not.toHaveBeenCalled()
})
it('professional workflow prompts do not expose an ordinary-image shortcut around their business rules',()=>{
  const html=renderToStaticMarkup(<AgentPromptPanel run={{...run,prompts:[{id:'v3',version:3,source:'user',content:'专业模块提示词',replayable:false}]}} busy={false} onSave={vi.fn()} onGenerate={vi.fn()} onError={vi.fn()}/>)
  expect(html).toContain('复制 Prompt');expect(html).not.toContain('用此版本生成')
})
