import {expect,it,vi} from 'vitest'
import {creativeModules} from './agentCreativeModules'
import {createAgentChat,setAgentCreativeContext} from './agentControlApi'
import {authenticatedFetch} from './authApi'
vi.mock('./authApi',()=>({authenticatedFetch:vi.fn()}))
it('provides all five professional modes and an explicit automatic reset',()=>{
 expect(creativeModules.map(m=>m.id)).toEqual(['auto','amazon_aplus','batch_tryon','listing_images','free_creation','image_edit'])
})
it('only carries a mode selection, never user-supplied Skill or Tool permissions',async()=>{
 await createAgentChat(undefined,'amazon_aplus')
 expect(JSON.parse(String(vi.mocked(authenticatedFetch).mock.lastCall?.[1]?.body))).toMatchObject({creative_module:'amazon_aplus'})
 await setAgentCreativeContext('chat','image_edit',2)
 expect(vi.mocked(authenticatedFetch).mock.lastCall?.[0]).toBe('/agent/conversations/chat/creative-context')
 expect(JSON.parse(String(vi.mocked(authenticatedFetch).mock.lastCall?.[1]?.body))).toEqual({module:'image_edit',expected_revision:2})
})
