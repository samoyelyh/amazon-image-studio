import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AgentSampleReview from './AgentSampleReview'
import AgentBusinessCards from './AgentBusinessCards'
import {sendAgentChatMessage,type AgentProductionPlan,type AgentRun} from '../../lib/agentControlApi'
import {authenticatedFetch} from '../../lib/authApi'
vi.mock('../../lib/authApi',()=>({authenticatedFetch:vi.fn(),authenticatedFetchResponse:vi.fn()}))
const rule={role:'template' as const,confidence:1,template_type:'pure_white',view:'front',protected_elements:[],allowed_changes:[],visual_facts:[],uncertainties:[]}
const plan:AgentProductionPlan={id:'p',revision:1,review_revision:4,common_prompt:'规则',template_rules:{t:rule},garment_rules:{g:{...rule,role:'garment'}},combination_overrides:[],unresolved_asset_ids:[],confirmed:true,combination_count:1,samples:{t:'j'},sample_approvals:{},production_batch_id:null,
 sample_catalog:[{sample_number:1,template_id:'t',job_id:'j',output_id:'o',asset_id:'a',status:'succeeded',approved:false,notes:''}]}
it('uses stable sample numbers and offers correction on the current output',()=>{
 const html=renderToStaticMarkup(<AgentSampleReview plan={plan} conversationId="c" outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
 expect(html).toContain('样图 1');expect(html).toContain('待审核');expect(html).toContain('样图 1 修改要求');expect(html).toContain('按要求修改');expect(html).toContain('重做')
})
it('reflects persisted approval without providing an active duplicate approval',()=>{
 const p={...plan,sample_catalog:plan.sample_catalog!.map(s=>({...s,approved:true}))}
 const html=renderToStaticMarkup(<AgentSampleReview plan={p} conversationId="c" outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
 expect(html).toMatch(/<button[^>]*disabled=""[^>]*>已通过<\/button>/)
})
it('card sends the same review business contract through the chat endpoint',async()=>{
 const sample_review={plan_id:'p',expected_revision:1,expected_review_revision:4,decisions:[{sample_number:1,output_id:'o',decision:'approve' as const}]}
 await sendAgentChatMessage('c',{content:'样图1通过',attachment_ids:[],client_request_id:'review-key',sample_review})
 expect(vi.mocked(authenticatedFetch).mock.lastCall?.[0]).toBe('/agent/conversations/c/messages')
 expect(JSON.parse(String(vi.mocked(authenticatedFetch).mock.lastCall?.[1]?.body))).toMatchObject({sample_review,auto_execute:true,chat_mode:true})
})
it('dynamic guide and memory cards use actual tool results',()=>{
 const run={result:{actions:[{tool:'guide_batch_inputs',result:{cards:[{type:'batch_upload_guide'}]}},{tool:'manage_user_preference',result:{cards:[{type:'memory_receipt',message:'已更新个人偏好。'}]}}]}} as unknown as AgentRun
 const html=renderToStaticMarkup(<AgentBusinessCards run={run} onImport={vi.fn()}/>)
 expect(html).toContain('上传模板图卡片');expect(html).toContain('上传服装卡片');expect(html).not.toContain('上传模板与服装</button>');expect(html).toContain('已更新个人偏好。')
 expect(renderToStaticMarkup(<AgentBusinessCards run={{result:{}} as AgentRun} onImport={vi.fn()}/>)).toBe('')
})
