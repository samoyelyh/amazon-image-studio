import { expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { AgentPlanCard } from './AgentControlWorkspace'
import type { AgentRun } from '../../lib/agentControlApi'

it('keeps preview identity and errors without persistent footnotes', () => {
  const run: AgentRun = { id: 'r', conversation_id: 'c', status: 'awaiting_confirmation', revision: 1, planner_mode: 'mock', plan: {
    schema_version: 1, summary: '生成 4 张套图', actions: [{ tool: 'submit_tryon_batch', arguments: {} }], image_count: 4, may_charge: true, cost_note: '使用原资源池',
  }, result: {}, error_code: null, state_signature: 'a'.repeat(64), confirmation_token: 'b'.repeat(64), events: [], jobs: [], workspace_url: null }
  const html = renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={run} status={{ enabled: true, writes_enabled: false, model_calls_enabled: false, planner_mode: 'mock', checkpoint_configured: true }} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
  expect(html).toContain('预览计划')
  expect(html).toContain('Agent 调度')
  expect(html).toContain('批量套图')
  expect(html).not.toContain('非真实 AI 推理')
  expect(html).not.toContain('不代表提交后的生图免费')
  expect(html).toContain('disabled=""')
  expect(html).not.toContain('不会取消已经提交的图片 Job')
})

it('shows a large task estimate and asks once, not repeated explanations',()=>{
  const run:AgentRun={id:'r',conversation_id:'c',status:'awaiting_confirmation',revision:1,planner_mode:'existing_text',
    plan:{schema_version:1,summary:'生成 8 张',actions:[],image_count:8,may_charge:true,cost_note:'不应常驻显示',budget:{estimated_cost:80,sufficient:true}},
    execution_notice:{automatic:false,reason:'本次超过 3 张图片，请确认后生成',image_count:8,estimated_credits:80,estimate:{text:'预计约 4–12 分钟',source:'conservative_reservation',sample_count:0}},
    result:{},error_code:null,state_signature:'a'.repeat(64),confirmation_token:'b'.repeat(64),events:[],jobs:[],workspace_url:null}
  const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={run} status={{enabled:true,writes_enabled:true,model_calls_enabled:true,planner_mode:'existing_text',checkpoint_configured:true}} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
  expect(html).toContain('预计约 4–12 分钟')
  expect(html).toContain('本次超过 3 张图片')
  expect(html).toContain('继续生成')
  expect(html).toContain('图片数量')
  expect(html).toContain('预计平台额度')
  expect(html).toContain('停止后续操作')
  expect(html).toContain('不取消已提交的图片任务')
  expect(html).not.toContain('不应常驻显示')
  expect(html).not.toContain('能力选择与执行记录')
})

it('does not mark an image tool as completed when only its job submission has a receipt', () => {
  const run: AgentRun = {
    id: 'r', conversation_id: 'c', status: 'waiting_jobs', revision: 1, planner_mode: 'existing_text',
    plan: { schema_version: 1, summary: '生成图片', actions: [{ tool: 'generate_chat_images', arguments: {} }], image_count: 1, may_charge: true, cost_note: '' },
    result: { actions: [{ tool: 'generate_chat_images', result: {} }] }, error_code: null,
    state_signature: 'a'.repeat(64), confirmation_token: 'b'.repeat(64), events: [],
    jobs: [{ id: 'job', status: 'queued', progress: 0, error_code: null, capability: 'image_generation' }], workspace_url: null,
  }
  const html = renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={run} status={{ enabled: true, writes_enabled: true, model_calls_enabled: true, planner_mode: 'existing_text', checkpoint_configured: true }} busy={false} onConfirm={vi.fn()} onStop={vi.fn()} /></MemoryRouter>)
  expect(html).toContain('图片生成 · 已提交')
  expect(html).not.toContain('图片生成 · 完成')
})
