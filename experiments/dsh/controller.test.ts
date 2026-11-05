import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { PlatformController } from './controller.ts'

const alice={org:'org1',user:'alice',session:'main'}
const input=(request:string,text='生成一张商品图',other={})=>({...alice,request,text,mode:'task' as const,...other})
test('ordinary chat cannot create a Ticket or an execution effect',()=>{
  const c=new PlatformController(':memory:')
  const r=c.intake(input('chat','如何生成商品图？',{mode:'chat'}))
  assert.equal(r.execute,false);assert.equal(c.list(alice).length,0);assert.equal(c.repo.list('effect').length,0)
})
test('explicit task accepts once, mandate is immutable, conflicting replay is refused',()=>{
  const c=new PlatformController(':memory:');const x=input('req1');const r=c.intake(x)
  assert.equal(c.intake(x).ticket,r.ticket);assert.equal(c.list(alice).length,1)
  assert.equal(c.list(alice)[0].mandate.strength,'explicit')
  assert.throws(()=>c.intake({...x,text:'different'}),/different input/)
})
test('followup resumes the same ended Ticket through the official Subscription path',()=>{
  const c=new PlatformController(':memory:');const a=c.intake(input('req1'));const mandate=c.list(alice)[0].mandate
  c.report(alice,a.ticket,'ready','complete')
  const b=c.intake(input('req2','第二张改成白底',{mode:'continue'}))
  assert.equal(b.ticket,a.ticket);assert.equal(c.list(alice).length,1)
  assert.equal(c.list(alice)[0].assignments.length,2);assert.deepEqual(c.list(alice)[0].mandate,mandate)
  assert.equal(c.repo.list('decision').length,1)
})
test('independent tasks and explicit target routing do not share contexts',()=>{
  const c=new PlatformController(':memory:');const a=c.intake(input('req1'));const b=c.intake(input('req2','生成另一件商品图',{new_task:true}))
  assert.notEqual(a.ticket,b.ticket)
  const r=c.intake(input('req3','只改第一件背景',{mode:'continue',ticket:a.ticket}))
  assert.equal(r.ticket,a.ticket);assert.equal(c.list(alice).find(t=>t.id===b.ticket)!.inputs.length,0)
  assert.equal(c.list(alice).filter(t=>t.assignments.at(-1)?.state==='running').length,2)
})
test('owner and organization isolation is enforced before followup fanout',()=>{
  const c=new PlatformController(':memory:');const a=c.intake(input('req1'))
  for(const owner of [{org:'org1',user:'bob'},{org:'org2',user:'alice'}]){
    assert.equal(c.list(owner).length,0)
    assert.throws(()=>c.intake({...input('intrude','修改',{mode:'continue',ticket:a.ticket}),...owner}),/not found/)
    assert.throws(()=>c.bind(owner,a.ticket,'forged'),/not found/)
  }
})
test('busy assignment is recovered on disk reload without creating another Ticket',()=>{
  const path=join(mkdtempSync(join(tmpdir(),'dsh-core-')),'core.sqlite')
  let c=new PlatformController(path);const a=c.intake(input('req1'));const old=c.list(alice)[0].assignments[0].id;c.repo.db.close()
  c=new PlatformController(path);const ticket=c.list(alice)[0]
  assert.equal(ticket.id,a.ticket);assert.equal(ticket.assignments.length,2);assert.notEqual(ticket.assignments.at(-1)!.id,old)
  assert.equal(c.intake(input('req1')).ticket,a.ticket)
  assert.ok(ticket.inputs.some(i=>i.kind==='text' && i.text.includes('restarted')))
  c.repo.db.close()
})
test('stopped mandate cannot resume; missing focus asks a question',()=>{
  const c=new PlatformController(':memory:')
  assert.equal(c.intake(input('req0','继续',{mode:'continue'})).route,'clarify')
  const a=c.intake(input('req1'));c.intake(input('req2','停止任务',{mode:'stop',ticket:a.ticket}))
  assert.throws(()=>c.intake(input('req3','继续',{mode:'continue',ticket:a.ticket})),/new authorization/)
})
