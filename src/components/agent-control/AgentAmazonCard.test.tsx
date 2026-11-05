import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AgentAmazonCard,{AmazonResearchStatus} from './AgentAmazonCard'
import {confirmAmazonModules,reviseAmazonModule,type AmazonPlanRecord} from '../../lib/amazonAgentApi'
import {authenticatedFetch} from '../../lib/authApi'
vi.mock('../../lib/authApi',()=>({authenticatedFetch:vi.fn(),authenticatedFetchResponse:vi.fn()}))
const module={id:'m3',title:'第三模块',spec_id:'basic_image_text_overlay',main_point:'酒红色',user_need:'展示',evidence_ids:['f'],composition:'左图右文',image_prompt:'No text',reference_asset_ids:['a'],headline:'Game Day',body:'Details',desktop_layout:'左图右文',mobile_layout:'上图下文',prohibited:[],acceptance:[]}
const record:AmazonPlanRecord={id:'plan',revision:2,plan:{marketplace:'US',aplus_type:'basic',rules_version:'v1',product_identity_lock:'球衣',campaign_style_lock:'白色',insight:{customers_and_scenes:[],competitor_points:[],buyer_concerns:[],keywords_and_intent:[],visual_opportunities:[],limitations:['未研究'],evidence:[{id:'f',statement:'竞品称防水',source:'评论样本',collected_at:'2026-11-01',scope:'competitor',status:'fact',period:'',review_scope:'子体',review_sample_count:2}]},modules:[module]},approvals:{},findings:[],manual_checks:[],submissions:[]}
it('shows editable native copy and separate facts/rights/fee boundaries',()=>{
 const html=renderToStaticMarkup(<AgentAmazonCard record={record} conversationId="chat" onRefresh={vi.fn()} onError={vi.fn()}/> )
 expect(html).toContain('英文标题（原生文字）');expect(html).toContain('第三模块');expect(html).toContain('评论样本2')
 expect(html).toContain('确认所选模块与事实');expect(html).toContain('双端排版预览');expect(html).toContain('ZIP')
 expect(html).toMatch(/disabled=""[^>]*\/>/)
})
it('uses module-scoped revision and explicit human facts confirmation',async()=>{
 await reviseAmazonModule('chat',record,module)
 let call=vi.mocked(authenticatedFetch).mock.calls.slice(-1)[0]!
 expect(call[0]).toBe('/agent/conversations/chat/amazon-plans/plan/module')
 expect(JSON.parse(String(call[1]?.body))).toMatchObject({expected_revision:2,module:{id:'m3'}})
 await confirmAmazonModules('chat',record,['m3'],['f'],true)
 call=vi.mocked(authenticatedFetch).mock.calls.slice(-1)[0]!
 expect(JSON.parse(String(call[1]?.body))).toEqual({expected_revision:2,module_ids:['m3'],verified_evidence_ids:['f'],commercial_rights_confirmed:true})
})
it('does not report a missing charge receipt as zero',()=>{
 const html=renderToStaticMarkup(<AmazonResearchStatus receipts={[{id:'r',status:'unknown',tool:'asin.detail',collected_at:'now',chargedUnits:null,reserved_units:2,cache_hit:false,error_code:'timeout'}]}/> )
 expect(html).toContain('上游未提供，需核对');expect(html).toContain('未自动重试')
})
it('offers one suite confirmation without requiring per-fact checkboxes first',()=>{
 const listing={...record,plan:{...record.plan,deliverable:'listing' as const,modules:[{...module,id:'m1'},{...module,id:'m2'}]}}
 const html=renderToStaticMarkup(<AgentAmazonCard record={listing} conversationId="chat" onRefresh={vi.fn()} onError={vi.fn()}/> )
 expect(html).toContain('Listing 图片方案')
 expect(html).toMatch(/<button[^>]*>确认方案，生成所选 2 张<\/button>/)
 expect(html).not.toMatch(/<button[^>]* disabled=""[^>]*>确认方案，生成所选/)
 expect(html).toContain('查看依据与编辑完整方案')
 expect(html).toContain('下载整套 ZIP')
})
