import {useMemo,useState} from 'react'
import BatchTryOnGarmentPreprocessDialog,{type GarmentReferencePreview} from '../BatchTryOnGarmentPreprocessDialog'
import {fetchAssetBlob,getAsset} from '../../lib/contentApi'
import {uploadGarmentReferenceDataUrl} from '../../lib/serverImageAssets'
import {compactGarmentTransform,garmentTransformMetadata} from '../../lib/batchTryOnGarmentPreprocess'
import {attachAgentImage,getBatchInputs,saveBatchInputs,type BatchInputManifest} from '../../lib/agentControlApi'
import type {BatchTryOnGarment} from '../../types'

export default function AgentGarmentPreprocess({manifest,conversationId,onSaved,onError}:{manifest:BatchInputManifest;conversationId:string;onSaved:()=>Promise<void>;onError:(s:string)=>void}){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[sources,setSources]=useState<Record<string,string>>({})
 const [sourceIds,setSourceIds]=useState<Record<string,string>>({})
 const garments=useMemo<BatchTryOnGarment[]>(()=>manifest.garments.map((g,i)=>({id:g.id,batchId:manifest.id,garmentImageId:g.primary_asset_id,serverAssetId:g.primary_asset_id,garmentFileName:g.label,index:i,selected:true,createdAt:0})),[manifest])
 async function show(){
  setBusy(true)
  try{
   const values:Record<string,string>={},originals:Record<string,string>={}
   for(const g of garments){
    let asset=await getAsset(g.garmentImageId);const seen=new Set<string>()
    while(asset.source_asset_id&&!seen.has(asset.id)&&seen.size<8){seen.add(asset.id);asset=await getAsset(asset.source_asset_id)}
    originals[g.id]=asset.id
    const blob=await fetchAssetBlob(`/assets/${asset.id}/content`);values[g.garmentImageId]=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(new Error('原图读取失败'));reader.readAsDataURL(blob)})
   }
   setSourceIds(originals);setSources(values);setOpen(true)
  }catch(e){onError(e instanceof Error?e.message:'原图读取失败')}finally{setBusy(false)}
 }
 async function save(previews:GarmentReferencePreview[]){
  setBusy(true)
  try{
   // Upload and attach through existing Asset APIs. Originals are never changed.
   const added:Array<{assetId:string;view:'front'|'back'|'detail';key:string}>=[]
   for(const p of previews){
    const g=manifest.garments.find(g=>g.id===p.garmentId);if(!g)throw new Error('服装关联已改变，请刷新后重试')
    const t=compactGarmentTransform(p.transform)
    const asset=await uploadGarmentReferenceDataUrl(p.dataUrl,g.label,{sourceAssetId:sourceIds[g.id]||g.primary_asset_id,garmentView:p.garmentView,transformType:t.eraseStrokes.length?(t.mode==='crop'?'crop_mask':'mask'):t.mode,transformMetadata:garmentTransformMetadata(t)})
    await attachAgentImage(conversationId,asset.id,p.garmentView)
    added.push({assetId:asset.id,view:p.garmentView,key:g.key})
   }
   const latest=await getBatchInputs(conversationId);if(!latest)throw new Error('素材清单读取失败')
   // Bind explicit group keys, not filenames or array positions.
   latest.entries=latest.entries.map(e=>{
    const a=added.find(a=>a.assetId===e.asset_id)
    if(a)return {...e,role:a.view,garment_key:a.key,enabled:true}
    const group=manifest.garments.find(g=>Object.values(g.references).some(ids=>ids.includes(e.asset_id)))
    return group&&added.some(a=>a.key===group.key&&a.view===e.role)?{...e,enabled:false}:e
   })
   await saveBatchInputs(conversationId,latest);setOpen(false);await onSaved()
  }catch(e){onError(e instanceof Error?e.message:'参考图保存失败');throw e}finally{setBusy(false)}
 }
 return <><button className="rounded-lg border px-3 py-2 text-xs disabled:opacity-40" disabled={busy||!garments.length} onClick={()=>void show()}>{busy?'正在准备…':'正背面裁剪与绑定'}</button><BatchTryOnGarmentPreprocessDialog open={open} garments={garments} sourceUrls={sources} saving={busy} onClose={()=>setOpen(false)} onSave={save} title="聊天服装参考处理"/></>
}
