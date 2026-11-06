import {it,expect,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AmazonModulePreview,{moduleSlotOutputs} from './AmazonModulePreview'
import type {AmazonPlanRecord,AmazonModule} from '../../lib/amazonAgentApi'
import type {AgentOutput} from '../../lib/agentControlApi'
vi.mock('../AuthenticatedImage',()=>({default:(p:{src:string;alt:string;className?:string})=><img {...p}/>}))
const module={id:'details',title:'真实细节',spec_id:'three',headline:'Original Details',body:'Product truth',image_slots:[1,2,3].map(n=>({id:`block${n}`,composition:`view${n}`,headline:`Feature ${n}`,body:`Evidence ${n}`}))} as AmazonModule
const record={id:'plan',module_specs:{details:{type:'basic',layout:'three_columns',width:600,height:600,slots:[1,2,3].map(n=>({id:`block${n}`,width:600,height:600}))}}} as unknown as AmazonPlanRecord
const outputs=[1,2,3].map(n=>({id:`o${n}`,version:1,content_url:`/${n}.png`,amazon_module:{plan_id:'plan',module_id:'details',slot_id:`block${n}`}})) as AgentOutput[]
it('renders each independent native image slot and its own copy',()=>{
 const html=renderToStaticMarkup(<AmazonModulePreview record={record} module={module} outputs={outputs}/> )
 expect(html.match(/<img /g)?.length).toBe(3);expect(html).toContain('data-layout="three_columns"')
 for(const n of [1,2,3]){expect(html).toContain(`/${n}.png`);expect(html).toContain(`Feature ${n}`)}
})
it('latest version is chosen per slot without replacing neighbouring images',()=>{
 const result=moduleSlotOutputs(record,module,[...outputs,{...outputs[0],id:'new',version:2,content_url:'/new.png'}])
 expect(result.map(p=>p.output?.id)).toEqual(['new','o2','o3'])
})
it('mobile preview stacks cells and missing slots remain visible',()=>{
 const html=renderToStaticMarkup(<AmazonModulePreview record={record} module={module} outputs={outputs.slice(0,1)} mobile/>)
 expect(html).toContain('grid-template-columns:1fr');expect(html).toContain('等待 block2 图片');expect(html).toContain('等待 block3 图片')
})
it('uses the owned original-crop endpoint instead of a generated replacement for a source slot',()=>{
 const original={...module,image_slots:module.image_slots!.map(s=>s.id==='block1'?{...s,source_crop:{asset_id:'source',box:[0,0,1,1]}}:s)}
 const html=renderToStaticMarkup(<AmazonModulePreview record={record} module={original} outputs={outputs} conversationId="conversation"/>)
 expect(html).toContain('/api/v1/agent/conversations/conversation/amazon-plans/plan/source/details/block1')
 expect(html).toContain('商品原图局部');expect(html).not.toContain('src="/1.png"')
 expect(html).toContain('/2.png');expect(html).toContain('/3.png')
})
