import {expect,it} from 'vitest'
import {amazonCardRunId,isSavedAmazonDraft} from './agentAmazonTimeline'
import type {AgentRun} from './agentControlApi'
import type {AmazonPlanRecord} from './amazonAgentApi'

const plan:AmazonPlanRecord={
 id:'plan',revision:1,approvals:{},findings:[],manual_checks:[],
 plan:{marketplace:'US',aplus_type:'basic',rules_version:'v1',product_identity_lock:'',campaign_style_lock:'',modules:[],
  insight:{customers_and_scenes:[],competitor_points:[],buyer_concerns:[],keywords_and_intent:[],visual_opportunities:[],limitations:[],evidence:[]}},
 submissions:[{batch_id:'batch',job_ids:['image'],module_ids:['module']}]
}
const run=(id:string,result:AgentRun['result'],rest:Partial<AgentRun>={})=>({id,result,jobs:[],plan:null,...rest}) as AgentRun
it('keeps the current plan beside its design round while later edits and chat stay in order',()=>{
 const runs=[run('chat',{}),run('edit',{actions:[{tool:'revise_amazon_modules',result:{amazon_plan_id:'plan'}}]}),run('design',{actions:[{tool:'save_aplus_plan',result:{amazon_plan_id:'plan'}}]})]
 expect(amazonCardRunId(runs,plan)).toBe('design')
 expect(runs.map(r=>r.id)).toEqual(['chat','edit','design'])
})
it('uses original owned image jobs for legacy runs without a plan-save receipt',()=>{
 const runs=[run('other',{}),run('edit',{}, {outputs:[{amazon_module:{plan_id:'plan'}}] as AgentRun['outputs']}),run('original',{}, {jobs:[{id:'image'}] as AgentRun['jobs']})]
 expect(amazonCardRunId(runs,plan)).toBe('original')
})
it('does not attach an unrelated plan to a message and supports pending plan review',()=>{
 expect(amazonCardRunId([run('unrelated',{})],plan)).toBeUndefined()
 expect(amazonCardRunId([run('review',{}, {plan:{schema_version:1,summary:'待审核方案',image_count:1,may_charge:false,cost_note:'',actions:[{tool:'generate_aplus',arguments:{plan_id:'plan'}}]}})],plan)).toBe('review')
})

it('only simplifies the empty follow-up form for a successfully saved native draft',()=>{
 const draft={...plan,findings:[],submissions:[]} as AmazonPlanRecord
 const saved=run('draft',{actions:[{tool:'save_aplus_plan',result:{amazon_plan_id:'plan'}}]}, {
  planner_mode:'dsh-native',status:'needs_input',error_code:null,
  plan:{schema_version:1,summary:'方案已保存',image_count:0,may_charge:false,cost_note:'',actions:[],needs_input:[]}
 })
 expect(isSavedAmazonDraft(saved,[draft])).toBe(true)
 expect(isSavedAmazonDraft({...saved,plan:{...saved.plan!,needs_input:['请补充商品事实']}},[draft])).toBe(false)
 expect(isSavedAmazonDraft(saved,[{...draft,findings:['尺寸需调整']}])).toBe(false)
 expect(isSavedAmazonDraft(saved,[plan])).toBe(false)
 expect(isSavedAmazonDraft({...saved,error_code:'upstream_error'},[draft])).toBe(false)
})
