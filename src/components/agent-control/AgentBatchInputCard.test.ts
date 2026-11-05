import {expect,it,vi} from 'vitest'
import {authenticatedFetch} from '../../lib/authApi'
import {getBatchInputs,saveBatchInputs,type BatchInputManifest} from '../../lib/agentControlApi'
vi.mock('../../lib/authApi',()=>({authenticatedFetch:vi.fn()}))
const manifest:BatchInputManifest={id:'manifest',revision:4,entries:[{asset_id:'front',filename:'NF0000532-front.png',role:'front',garment_key:'sku:0000532',manual:true,analysis:{}}],templates:[],garments:[],unresolved_asset_ids:[],pairing_mode:'paired',pairs:[],combination_count:0}
it('saves logical garment associations with revision checks through the original API',async()=>{
 vi.mocked(authenticatedFetch).mockResolvedValue(manifest)
 await saveBatchInputs('conversation',manifest)
 const calls=vi.mocked(authenticatedFetch).mock.calls
 const call=calls[calls.length-1]
 expect(call[0]).toBe('/agent/conversations/conversation/batch-inputs')
 const body=JSON.parse(String(call[1]?.body))
 expect(body).toMatchObject({expected_revision:4,pairing_mode:'paired',entries:[{role:'front',garment_key:'sku:0000532'}]})
 expect(body).not.toHaveProperty('job_ids')
})
it('restores the server manifest instead of relying on localStorage',async()=>{
 vi.mocked(authenticatedFetch).mockResolvedValue(manifest)
 expect(await getBatchInputs('conversation')).toEqual(manifest)
})
