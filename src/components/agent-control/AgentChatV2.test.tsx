import { expect,it,vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { AgentPlanCard,AgentResultGallery } from './AgentChatCards'
import { canConfirmAgentRun,createAgentChat,sendAgentChatMessage,type AgentOutput,type AgentRun } from '../../lib/agentControlApi'
import { authenticatedFetch } from '../../lib/authApi'
vi.mock('../../lib/authApi',()=>({authenticatedFetch:vi.fn(),authenticatedFetchResponse:vi.fn()}))
const fixture:AgentRun={id:'run',conversation_id:'chat',status:'awaiting_confirmation',revision:1,planner_mode:'mock',
  plan:{schema_version:1,summary:'生成图片',actions:[{tool:'generate_chat_images',arguments:{}}],image_count:1,may_charge:true,cost_note:'需要确认'},
  result:{},error_code:null,state_signature:'a'.repeat(64),confirmation_token:'b'.repeat(64),events:[],jobs:[],workspace_url:null}

it('starts chat without requiring a project or form fields',async()=>{
  vi.mocked(authenticatedFetch).mockResolvedValue({id:'chat'})
  await createAgentChat()
  let calls=vi.mocked(authenticatedFetch).mock.calls
  expect(JSON.parse(String(calls[calls.length-1]?.[1]?.body))).toMatchObject({project_id:null,context_kind:'chat'})
  await sendAgentChatMessage('chat',{content:'生成一张图',client_request_id:'stable-id',attachment_ids:['attachment']})
  calls=vi.mocked(authenticatedFetch).mock.calls
  expect(JSON.parse(String(calls[calls.length-1]?.[1]?.body))).toMatchObject({chat_mode:true,auto_execute:true,attachment_ids:['attachment']})
})
it('keeps a disabled or unaffordable real fee plan from being confirmed',()=>{
  const status={enabled:true,writes_enabled:true,model_calls_enabled:true,planner_mode:'mock' as const,checkpoint_configured:true}
  const run={...fixture,plan:{...fixture.plan!,actions:[{tool:'generate_chat_images',arguments:{}}],budget:{estimated_cost:20,available_balance:10,sufficient:false}}}
  expect(canConfirmAgentRun(run,status)).toBe(false)
  expect(canConfirmAgentRun({...run,plan:{...run.plan,budget:{...run.plan.budget,sufficient:true}}},status)).toBe(true)
})
it('does not count text completion as an image completion',()=>{
  const html=renderToStaticMarkup(<MemoryRouter><AgentPlanCard run={{...fixture,jobs:[{id:'text',status:'succeeded',progress:100,error_code:null,capability:'text_generation'},{id:'image',status:'queued',progress:0,error_code:null,capability:'image_edit'}]}} status={{enabled:true,writes_enabled:false,model_calls_enabled:false,planner_mode:'mock',checkpoint_configured:true}} busy={false} onConfirm={vi.fn()} onStop={vi.fn()}/></MemoryRouter>)
  expect(html).toContain('成功 0/1 张')
  expect(html).not.toContain('不计入图片完成数量')
})
it('renders stable image numbers and versions instead of a jump-only result',()=>{
  const output:AgentOutput={id:'output',asset_id:'asset',job_id:'job',run_id:'run',number:3,sequence_number:1,filename:'result.png',width:1024,height:1536,size:100,mime_type:'image/png',content_url:'/assets/asset/content',download_url:'/assets/asset/download',parent_output_id:'original',root_output_id:'original',version:2,source_asset_id:'source-2',source_index:2,source_filename:'original-02.png'}
  const html=renderToStaticMarkup(<AgentResultGallery outputs={[output]} onEdit={vi.fn()} onError={vi.fn()}/>)
  expect(html).toContain('图片 3 · v2')
  expect(html).toContain('继续修改')
  expect(html).toContain('下载本组')
  expect(html).toContain('原图 2');expect(html).toContain('original-02.png')
})
