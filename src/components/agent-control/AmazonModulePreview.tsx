import AuthenticatedImage from '../AuthenticatedImage'
import type {AgentOutput} from '../../lib/agentControlApi'
import type {AmazonModule,AmazonPlanRecord} from '../../lib/amazonAgentApi'

export function moduleSlotOutputs(record:AmazonPlanRecord,module:AmazonModule,outputs:AgentOutput[]){
 const spec=record.module_specs?.[module.id]
 const slots=spec?.slots||[{id:'main',width:spec?.width||970,height:spec?.height||300}]
 return slots.map(slot=>({slot,copy:module.image_slots?.find(s=>s.id===slot.id),output:outputs
  .filter(o=>o.amazon_module?.plan_id===record.id&&o.amazon_module.module_id===module.id&&(o.amazon_module.slot_id||'main')===slot.id)
  .sort((a,b)=>b.version-a.version)[0]}))
}

export default function AmazonModulePreview({record,module,outputs,mobile=false}:{record:AmazonPlanRecord;module:AmazonModule;outputs:AgentOutput[];mobile?:boolean}){
 const spec=record.module_specs?.[module.id],layout=spec?.layout||'header',pictures=moduleSlotOutputs(record,module,outputs)
 const text=<div className="min-w-0 whitespace-pre-wrap break-words p-5"><h3 className="text-xl font-semibold leading-tight">{module.headline}</h3><p className="mt-3 text-sm leading-6">{module.body}</p></div>
 function picture(p:typeof pictures[number]){return p.output?<AuthenticatedImage src={p.output.content_url} alt={`${module.title} · ${p.slot.id}`} className="block h-auto w-full"/>:<div className="flex items-center justify-center bg-stone-100 p-6 text-center text-sm text-stone-600" style={{aspectRatio:`${p.slot.width}/${p.slot.height}`}}>等待 {p.slot.id} 图片</div>}
 const side=['image_left','image_right'].includes(layout)
 const concept=record.plan?.creative_strategy?.concept
 const fonts={editorial_serif:'Georgia, serif',clean_sans:'Arial, sans-serif',technical_mono:'Consolas, monospace'}
 return <article aria-label={`${module.title}模块预览`} data-layout={layout} style={concept?{backgroundColor:concept.canvas_color,color:concept.ink_color,borderColor:concept.accent_color,fontFamily:fonts[concept.native_type_style]}:undefined} className="my-4 overflow-hidden border border-stone-200 bg-white text-stone-900">
  {side?<div className="grid items-center" style={{gridTemplateColumns:mobile?'1fr':'1fr 1fr'}}>{layout==='image_right'&&!mobile?text:null}<div>{picture(pictures[0])}</div>{layout!=='image_right'||mobile?text:null}</div>
  :['three_columns','four_columns','sidebar'].includes(layout)?<><h3 className="px-5 pt-5 text-xl font-semibold">{module.headline}</h3><div className="grid gap-4 p-5" style={{gridTemplateColumns:mobile?'1fr':layout==='sidebar'?'2fr 1fr':`repeat(${pictures.length},minmax(0,1fr))`}}>{pictures.map(p=><div key={p.slot.id} className="min-w-0">{picture(p)}<div className="mt-3 whitespace-pre-wrap break-words"><h4 className="font-semibold">{p.copy?.headline}</h4><p className="mt-2 text-sm leading-6">{p.copy?.body}</p></div></div>)}</div>{module.body&&<p className="px-5 pb-5 text-sm">{module.body}</p>}</>
  :layout==='overlay'&&!mobile?<div className="relative">{picture(pictures[0])}<div className="absolute inset-y-0 right-0 flex w-[42%] items-center bg-white/85">{text}</div></div>
  :<>{picture(pictures.find(p=>p.slot.id===(mobile?'mobile':'desktop'))||pictures[0])}{text}</>}
 </article>
}
