import {useRef,useState} from 'react'
import type {ImportSource} from '../../lib/agentImportFiles'

type ImportProps={onImport:(files:File[],source:ImportSource)=>void;disabled?:boolean}
const targets={
 template:{label:'导入模板',title:'上传模板图',description:'用来保留人物、背景和构图'},
 garment:{label:'导入服装',title:'上传服装',description:'需要穿到模板上的服装商品'},
 auto:{label:'自动识别',title:'导入混合素材',description:'角色不明确的素材由 AI 分类'},
} satisfies Record<ImportSource,{label:string;title:string;description:string}>

// Each target owns its inputs and source, including after a picker is cancelled.
function ImportTarget({source,onImport,disabled=false,card=false,open=false,onToggle,onClose}:{source:ImportSource;card?:boolean;open?:boolean;onToggle?:()=>void;onClose?:()=>void}&ImportProps){
 const pictures=useRef<HTMLInputElement>(null),folder=useRef<HTMLInputElement>(null),archive=useRef<HTMLInputElement>(null)
 const target=targets[source]
 const choose=(kind:'pictures'|'folder'|'archive')=>{if(!disabled)({pictures,folder,archive}[kind]).current?.click()}
 const selected=(el:HTMLInputElement)=>{
  const files=Array.from(el.files||[]);el.value=''
  if(files.length&&!disabled){onClose?.();onImport(files,source)}
 }
 return <div className={card?'min-w-0 rounded-xl border border-stone-200 bg-white p-4':'min-w-0'} role={card?'group':undefined} aria-label={card?target.title+'卡片':undefined} data-import-source={source}>
  {card?<><h4 className="text-sm font-semibold">{target.title}</h4><p className="mt-1 text-sm text-stone-600">{target.description}</p></>:<button type="button" disabled={disabled} aria-expanded={open} aria-haspopup="dialog" className="rounded-full border px-3 py-2 text-xs disabled:opacity-40" onClick={onToggle}>{target.label}</button>}
  {(card||open)&&<div role={card?'group':'dialog'} aria-label={target.title+'方式'} className={card?'mt-3 flex flex-wrap gap-2':'absolute bottom-full left-0 z-30 mb-2 flex w-64 flex-col rounded-xl border bg-white p-3 shadow-xl'} onKeyDown={e=>{if(e.key==='Escape')onClose?.()}}>
   {!card&&<p className="mb-2 px-2 text-sm font-semibold">{target.title}</p>}
   {([['pictures','选择图片'],['folder','选择文件夹'],['archive','选择 ZIP']] as const).map(([kind,label])=><button key={kind} type="button" disabled={disabled} className={card?'rounded-lg border px-3 py-2 text-sm hover:bg-stone-50 disabled:opacity-40':'rounded-lg px-3 py-2 text-left text-sm hover:bg-stone-100 disabled:opacity-40'} onClick={()=>choose(kind)}>{label}</button>)}
   {!card&&<button type="button" className="mt-1 rounded-lg px-3 py-2 text-left text-sm text-stone-600" onClick={onClose}>收起</button>}
  </div>}
  <input aria-label={target.title+'图片文件'} className="hidden" ref={pictures} type="file" multiple disabled={disabled} accept=".jpg,.jpeg,.png,.webp" onChange={e=>selected(e.currentTarget)}/>
  <input aria-label={target.title+'文件夹'} className="hidden" ref={folder} type="file" multiple disabled={disabled} {...{webkitdirectory:'',directory:''}} onChange={e=>selected(e.currentTarget)}/>
  <input aria-label={target.title+'ZIP压缩包'} className="hidden" ref={archive} type="file" multiple disabled={disabled} accept=".zip,application/zip" onChange={e=>selected(e.currentTarget)}/>
 </div>
}

export default function AgentMaterialImport({onImport,disabled=false,variant='compact'}:ImportProps&{variant?:'compact'|'cards'}){
 const [openSource,setOpenSource]=useState<ImportSource|null>(null)
 if(variant==='cards')return <div aria-label="分别导入模板与服装">
  <div className="grid gap-3 sm:grid-cols-2">{(['template','garment'] as const).map(source=><ImportTarget key={source} source={source} card disabled={disabled} onImport={onImport}/>)}</div>
  <details className="mt-3"><summary className="cursor-pointer text-sm text-stone-600">混合素材：自动识别</summary><div className="mt-2"><ImportTarget source="auto" card disabled={disabled} onImport={onImport}/></div></details>
 </div>
 return <div className="relative flex flex-wrap items-center gap-1" aria-label="智能素材导入">{(['template','garment','auto'] as const).map(source=><ImportTarget key={source} source={source} disabled={disabled} onImport={onImport} open={openSource===source} onToggle={()=>setOpenSource(openSource===source?null:source)} onClose={()=>setOpenSource(null)}/>)}</div>
}
