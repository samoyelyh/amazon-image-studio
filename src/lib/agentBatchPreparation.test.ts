import {expect,it} from 'vitest'
import {hasBatchPreparation,importWasSubmitted} from './agentBatchPreparation'
import type {AgentRun} from './agentControlApi'
const run=(status:string,tool:string)=>({status,plan:{actions:[{tool}]}} as AgentRun)
it('holds automatic import continuation through the text planner and understanding stages',()=>{
 for(const status of ['planning','ready_to_submit','submitted','waiting_jobs']){
  expect(hasBatchPreparation([run(status,'plan_intent')])).toBe(true)
  expect(hasBatchPreparation([run(status,'analyze_chat_assets')])).toBe(true)
 }
})
it('restores covered import scopes after refresh without treating them as completed images',()=>{
 const saved={...run('failed','analyze_chat_assets'),result:{submitted_import_keys:['current']}}
 expect(importWasSubmitted([saved],'current')).toBe(true)
 expect(importWasSubmitted([saved],'new-inputs')).toBe(false)
 expect(saved.status).toBe('failed')
})
it('does not block independent asynchronous images, review, or settled history',()=>{
 for(const status of ['completed','failed','cancelled','remote_unknown','awaiting_review']){
  expect(hasBatchPreparation([run(status,'plan_intent')])).toBe(false)
 }
 expect(hasBatchPreparation([run('waiting_jobs','generate_chat_tryon')])).toBe(false)
 expect(hasBatchPreparation([run('waiting_jobs','generate_chat_images')])).toBe(false)
 expect(hasBatchPreparation([])).toBe(false)
})
