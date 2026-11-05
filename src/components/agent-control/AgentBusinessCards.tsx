import type {AgentRun} from '../../lib/agentControlApi'
import type {ImportSource} from '../../lib/agentImportFiles'
import AgentMaterialImport from './AgentMaterialImport'

export default function AgentBusinessCards({run,onImport,disabled=false}:{run:AgentRun;onImport:(files:File[],source:ImportSource)=>void;disabled?:boolean}){
 const cards=(run.result.actions||[]).flatMap(a=>Array.isArray(a.result.cards)?a.result.cards as Array<{type:string;message?:string}>:[])
 return <>{cards.map((c,i)=>c.type==='batch_upload_guide'?<section key={i} aria-label="批量换衣上传引导" className="mt-3"><AgentMaterialImport variant="cards" disabled={disabled} onImport={onImport}/></section>:c.type==='memory_receipt'?<p key={i} role="status" className="mt-3 text-sm text-emerald-700">{c.message}</p>:null)}</>
}
