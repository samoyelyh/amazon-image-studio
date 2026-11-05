import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AgentProductionCard,{productionCardRunId} from './AgentProductionCard'
import {saveAgentProductionRules,confirmAgentProductionRules,type AgentProductionPlan} from '../../lib/agentControlApi'
import {authenticatedFetch} from '../../lib/authApi'
vi.mock('../../lib/authApi',()=>({authenticatedFetch:vi.fn(),authenticatedFetchResponse:vi.fn()}))
const rule={role:'template' as const,confidence:.95,template_type:'pure_white',view:'front',protected_elements:['构图'],allowed_changes:['服装'],visual_facts:[],uncertainties:[]}
const plan:AgentProductionPlan={id:'plan',revision:3,common_prompt:'当前服装事实以当前图B为准',template_rules:{t:rule},garment_rules:{g:{...rule,role:'garment'}},
  combination_overrides:[],unresolved_asset_ids:[],confirmed:false,combination_count:1,samples:{},sample_approvals:{},production_batch_id:null}
it('keeps rules confirmation and sample review inside the chat, not a workspace redirect',()=>{
  const html=renderToStaticMarkup(<AgentProductionCard plan={plan} conversationId="chat" attachments={[]} outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
  expect(html).toContain('通用换衣要求');expect(html).toContain('查看与调整替换规则');expect(html).toContain('生成样图')
  expect(html).not.toContain('下一步确认费用')
  expect(html).not.toContain('href=')
})
it('requires samples only when the human requested sample review',()=>{
  const html=renderToStaticMarkup(<AgentProductionCard plan={{...plan,confirmed:true,sample_review_required:true}} conversationId="chat" attachments={[]} outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
  expect(html).toMatch(/<button[^>]*disabled=""[^>]*>生产已通过的模板/)
})
it('allows direct production without a mandatory sample gate',()=>{
 const html=renderToStaticMarkup(<AgentProductionCard plan={plan} conversationId="chat" attachments={[]} outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
 expect(html.match(/<button[^>]*>批量生成剩余 1 张<\/button>/)?.[0]).not.toContain('disabled=""')
})
it('keeps one live rule editor when analysis, sample and production share the same plan',()=>{
  const runs=[{id:'sample',result:{actions:[{tool:'generate_chat_tryon',result:{production_plan_id:'plan'}}]}},
    {id:'analysis',result:{actions:[{tool:'analyze_chat_assets',result:{production_plan_id:'plan'}}]}}]
  expect(productionCardRunId(runs,'plan')).toBe('sample')
  expect(productionCardRunId(runs,'missing')).toBeUndefined()
})
it('sends versioned rules to owner-scoped endpoints without transferring generation authority',async()=>{
  vi.mocked(authenticatedFetch).mockResolvedValue(plan)
  await saveAgentProductionRules('chat',plan);await confirmAgentProductionRules('chat',plan)
  const calls=vi.mocked(authenticatedFetch).mock.calls
  expect(calls[0][0]).toBe('/agent/conversations/chat/production-plans/plan')
  expect(JSON.parse(String(calls[0][1]?.body))).toMatchObject({expected_revision:3,common_prompt:plan.common_prompt})
  expect(calls[1][0]).toContain('/confirm')
})
it('shows and saves each template reusable prompt without treating a sample as the template',async()=>{
 const p={...plan,template_prompts:{t:'保留模板人物和背景，当前图B决定服装设计'},analysis_mode:'template_first' as const}
 const html=renderToStaticMarkup(<AgentProductionCard plan={p} conversationId="chat" attachments={[]} outputs={[]} onRefresh={vi.fn()} onError={vi.fn()}/>)
 expect(html).toContain('t 通用换衣提示词')
 expect(html).toContain(p.template_prompts.t)
 await saveAgentProductionRules('chat',p)
 expect(JSON.parse(String(vi.mocked(authenticatedFetch).mock.lastCall?.[1]?.body)).template_prompts).toEqual(p.template_prompts)
})
