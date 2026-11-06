import {useEffect,useRef,useState} from 'react'
import AuthenticatedImage from '../AuthenticatedImage'
import {confirmAmazonModules,reviseAmazonModule,type AmazonPlanRecord,type AmazonModule,type AmazonReceipt} from '../../lib/amazonAgentApi'
import {agentRequestId,sendAgentChatMessage,confirmAgentRun,type AgentRun,type AgentOutput} from '../../lib/agentControlApi'
import {downloadAuthenticatedFile} from '../../lib/serverDownloads'
import {chatButton} from './AgentChatCards'
import AmazonModulePreview from './AmazonModulePreview'

export function AmazonResearchStatus({receipts}:{receipts:AmazonReceipt[]}){
  if(!receipts.length)return null
  return <details className="my-3 rounded-xl border p-3 text-xs dark:border-white/10"><summary>市场调研记录 · {receipts.length}</summary>{receipts.map(r=><div key={r.id} className="mt-2"><p>{r.tool} · {r.status} · {r.collected_at}</p><p>实际计费单位：{r.chargedUnits??'上游未提供，需核对'} · 预留 {r.reserved_units}{r.cache_hit?' · 使用缓存':''}</p>{r.error_code&&<p className="text-amber-600">{r.error_code}，未自动重试。</p>}</div>)}</details>
}

export default function AgentAmazonCard({record,conversationId,outputs=[],pendingRun,onRefresh,onError}:{record:AmazonPlanRecord;conversationId:string;outputs?:AgentOutput[];pendingRun?:AgentRun;onRefresh:()=>Promise<void>;onError:(s:string)=>void}){
  const [modules,setModules]=useState(record.plan.modules),[selected,setSelected]=useState<string[]>(record.plan.modules.map(m=>m.id)),[facts,setFacts]=useState<string[]>([]),[rights,setRights]=useState(false),[busy,setBusy]=useState(false),[dirty,setDirty]=useState<string[]>([])
  const keys=useRef<Record<string,string>>({})
  const imageCount=modules.reduce((n,m)=>n+(record.module_specs?.[m.id]?.slots?.length||1),0)
  const selectedImageCount=modules.filter(m=>selected.includes(m.id)).reduce((n,m)=>n+(record.module_specs?.[m.id]?.slots?.length||1),0)
  const [preview,setPreview]=useState<'desktop'|'mobile'|null>(null)
  const saving=useRef<string|null>(null)
  useEffect(()=>{const savedId=saving.current;setModules(old=>record.plan.modules.map(m=>dirty.includes(m.id)&&m.id!==savedId?old.find(x=>x.id===m.id)||m:m));setDirty(old=>old.filter(id=>id!==savedId));saving.current=null},[record.id,record.revision])
  async function act(f:()=>Promise<unknown>){setBusy(true);try{await f();await onRefresh()}catch(e){onError(e instanceof Error?e.message:'操作失败')}finally{setBusy(false)}}
  function update(m:AmazonModule,key:keyof AmazonModule,value:string){setModules(old=>old.map(x=>x.id===m.id?{...x,[key]:value}:x));setDirty(old=>[...new Set([...old,m.id])])}
  async function generate(){
    const pending=pendingRun?.plan?.actions.find(a=>a.tool==='generate_aplus')?.arguments
    if(pendingRun&&pending?.plan_id===record.id&&pending.expected_revision===record.revision&&Array.isArray(pending.module_ids)&&[...pending.module_ids].sort().join(',')===[...selected].sort().join(',')){await confirmAgentRun(pendingRun);return}
    const k=`${record.id}:${record.revision}:${[...selected].sort().join(',')}`;keys.current[k]??=agentRequestId();await sendAgentChatMessage(conversationId,{content:'方案可以，直接生成所选图片，其他图片保持不变',attachment_ids:[],client_request_id:keys.current[k],amazon_plan_id:record.id,amazon_revision:record.revision,amazon_module_ids:selected})
  }
  return <section aria-label="A+运营需求卡" className="my-4 rounded-2xl border bg-white p-4 dark:border-white/10 dark:bg-gray-900">
    <div className="flex justify-between"><h3 className="font-medium">{record.plan.deliverable==='listing'?'Listing 图片方案':'A+ 运营需求卡'}</h3><span className="text-xs text-gray-500">{record.plan.marketplace} · {modules.length} 个模块 · {imageCount} 张素材 · v{record.revision}</span></div>
    <div className="my-3 space-y-2">{modules.map((m,i)=>{const output=outputs.filter(o=>o.amazon_module?.plan_id===record.id&&o.amazon_module.module_id===m.id).sort((a,b)=>b.version-a.version)[0];return <div key={m.id} className="flex gap-3 rounded-xl bg-gray-50 p-3">{output&&<AuthenticatedImage src={output.content_url} alt={`第${i+1}张 ${m.title}`} className="h-20 w-20 shrink-0 rounded-lg object-contain"/>}<div><p className="text-sm font-medium">{i+1}. {m.title}</p><p className="mt-1 text-sm">{m.main_point}</p><p className="mt-1 text-xs text-gray-600">{m.composition}</p>{output&&<p className="mt-1 text-xs text-gray-500">版本 {output.version} · 待质量审核</p>}</div></div>})}</div>
    <div className="flex flex-wrap gap-2"><button className={`${chatButton} bg-blue-600 !text-white`} disabled={busy||(record.controller==='dsh-native'&&record.submissions.length>0)||!selected.length||!!dirty.length||!!record.findings.length} onClick={()=>void act(generate)}>{record.controller==='dsh-native'&&record.submissions.length>0?'DSH 已自动提交，修改请选中对应图片':<> {pendingRun?.status==='awaiting_review'?'确认方案，':''}生成所选 {selectedImageCount} 张素材</>}</button><button className={chatButton} disabled={busy} onClick={()=>void act(()=>downloadAuthenticatedFile(`/api/v1/agent/conversations/${conversationId}/amazon-plans/${record.id}/archive`,`amazon-${record.id}.zip`))}>下载整套 ZIP</button></div>
    <details className="my-3 text-xs"><summary>查看依据与编辑完整方案</summary>
    <details className="my-3 text-xs"><summary>商品与品牌一致性</summary><p className="mt-2 whitespace-pre-wrap">{record.plan.product_identity_lock}</p><p className="mt-2 whitespace-pre-wrap">{record.plan.campaign_style_lock}</p></details>
    <details className="my-3 text-xs"><summary>市场洞察摘要</summary>{([['customers_and_scenes','客户与场景'],['competitor_points','竞品卖点（非我方事实）'],['buyer_concerns','买家关注'],['keywords_and_intent','关键词与意图'],['visual_opportunities','视觉机会']] as const).map(([k,label])=><div className="mt-2" key={k}><strong>{label}</strong><p>{record.plan.insight[k]?.join('；')||'暂无已验证资料'}</p></div>)}</details>
    <details className="my-3 text-xs" open><summary>卖点证据与风险</summary>{record.plan.insight.evidence.map(e=><label key={e.id} className="mt-2 block rounded-lg bg-gray-50 p-2 dark:bg-white/5"><input type="checkbox" disabled={e.scope!=='own_product'||e.status!=='fact'} checked={facts.includes(e.id)} onChange={v=>setFacts(old=>v.target.checked?[...old,e.id]:old.filter(x=>x!==e.id))}/> 我已核对：{e.statement}<span className="block text-gray-500">{e.scope} / {e.status} · {e.source} · {e.collected_at}{e.asin&&` · ${e.asin}`}{e.review_sample_count!=null&&` · 评论样本${e.review_sample_count} · ${e.review_scope}`}</span></label>)}{record.plan.insight.limitations.map((s,i)=><p key={i} className="mt-2 text-amber-600">{s}</p>)}{record.findings.map((s,i)=><p key={i} className="mt-2 text-red-600">{s}</p>)}</details>
    {modules.map((m,i)=><details key={m.id} className="my-3 rounded-xl border p-3 text-xs dark:border-white/10" open={i===0}><summary className="cursor-pointer">{i+1}. {m.title} · {record.approvals[m.id]?'已确认':'待审核'}{dirty.includes(m.id)?' · 未保存':''}</summary>
      <label className="mt-2 block"><input type="checkbox" checked={selected.includes(m.id)} onChange={e=>setSelected(old=>e.target.checked?[...old,m.id]:old.filter(id=>id!==m.id))}/> 选择本模块</label>
      <div className="my-2 flex gap-2">{m.reference_asset_ids.map(id=><AuthenticatedImage key={id} src={`/api/v1/assets/${id}/content`} alt={`${m.title}参考图`} className="h-20 w-20 rounded-lg object-contain"/>)}</div>
      {([['main_point','主要卖点'],['headline','英文标题（原生文字）'],['body','英文正文（原生文字）'],['composition','画面构图'],['desktop_layout','桌面布局'],['mobile_layout','手机布局'],['image_prompt','图片Prompt（不含排版文字）']] as const).map(([k,label])=><label key={k} className="my-2 block">{label}<textarea aria-label={`${m.id} ${label}`} value={m[k]} onChange={e=>update(m,k,e.target.value)} className="mt-1 min-h-16 w-full rounded-lg border bg-transparent p-2 dark:border-white/10"/></label>)}
      <div className="my-2 rounded-lg bg-white p-3 text-sm">{record.module_specs?.[m.id]?.label} · {(record.module_specs?.[m.id]?.slots||[]).map(s=>s.id+' '+s.width+'×'+s.height).join(' / ')}</div>
      {!!m.design_principles?.length&&<details className="my-2"><summary>本模块应用的专业设计规则</summary><p className="mt-2">{m.design_principles.join(' · ')}</p>{m.art_direction&&Object.entries(m.art_direction).map(([k,v])=><p key={k} className="mt-2">{k}：{v}</p>)}<p className="mt-2">{record.skill_trace?.map(s=>s.id+' v'+s.version).join(' · ')}</p></details>}
      <p className="text-gray-500">验收：{m.acceptance.join('；')} · 规格 {m.spec_id}</p><button className={`${chatButton} mt-2`} disabled={busy||!dirty.includes(m.id)} onClick={()=>{saving.current=m.id;void act(()=>reviseAmazonModule(conversationId,record,m))}}>保存本模块修改</button>
    </details>)}
    <label className="my-3 block text-xs"><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/> 我确认素材可商业使用，涉及的品牌、球队、赛事标识已有授权。</label>
    <div className="flex flex-wrap gap-2"><button className={chatButton} disabled={busy||!rights||!selected.length||!!dirty.length||!!record.findings.length} onClick={()=>void act(()=>confirmAmazonModules(conversationId,record,selected,facts,rights))}>确认所选模块与事实</button><button className={chatButton} onClick={()=>void act(()=>downloadAuthenticatedFile(`/api/v1/agent/conversations/${conversationId}/amazon-plans/${record.id}/export`,`aplus-${record.id}.json`))}>导出图片与文案清单</button></div>
    </details>
    <div className="mt-3 flex flex-wrap gap-2"><button className={chatButton} onClick={()=>setPreview('desktop')}>双端排版预览</button></div>
    {preview&&<div role="dialog" aria-label="A+双端排版预览" className="fixed inset-0 z-50 overflow-auto bg-black/70 p-4"><div className="mx-auto max-w-5xl rounded-2xl bg-white p-4 text-gray-900"><div className="sticky top-0 z-10 flex flex-wrap gap-2 bg-white py-2"><button className={chatButton} onClick={()=>setPreview('desktop')}>桌面预览</button><button className={chatButton} onClick={()=>setPreview('mobile')}>手机预览</button><button className={chatButton} onClick={()=>setPreview(null)}>关闭预览</button></div><p className="my-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">本平台模块组合审核预览，不代表 Seller Central 实际渲染或发布成功。</p><div className="mx-auto" style={{maxWidth:preview==='mobile'?375:970}}>{modules.map(m=><AmazonModulePreview key={m.id} record={record} module={m} outputs={outputs} mobile={preview==='mobile'}/>)}</div></div></div>}
  </section>
}
