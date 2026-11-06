import { createHash, randomUUID } from 'node:crypto'
import { Engine, latestAssignment, ticketStage } from './upstream/src/core/index.ts'
import type { Assignment, Ticket, Trigger, DomainEvent, Policy } from './upstream/src/core/index.ts'
import { SqliteRepositories } from './repositories.ts'

export type Owner = { org: string; user: string }
export type Intake = Owner & { session: string; request: string; text: string; mode: 'chat' | 'task' | 'continue' | 'status' | 'stop'; ticket?: string; new_task?: boolean; semantic?: boolean }
const hash = (s: unknown) => createHash('sha256').update(JSON.stringify(s)).digest('hex')
type Binding = Owner & { session: string; conversation?: string }

/** Only the domain core is upstream DSH. This source/assessor/executor glue is ours. */
export class PlatformController {
  repo: SqliteRepositories
  engine: Engine
  constructor(path: string, readonly nativeSessions = false) {
    this.repo = new SqliteRepositories(path)
    const policy: Policy = {
      version: 'image-platform-explicit-v1', paused: false, evalTimeoutMs: 30000,
      gate: trigger => trigger.human && trigger.meta.authorized === true
        ? { admissible: true, strength: 'explicit', basis: { via: 'listed' } }
        : { admissible: false, reason: 'Explicit platform task authorization is required' },
      revalidate: m => m.policyVersion === 'image-platform-explicit-v1', admitsInferred: () => false,
    }
    const queue = (kind: string, t: Ticket, a: Assignment) => this.repo.put('effect', `${kind}:${a.id}`, { kind, ticket: t.id, assignment: a.id })
    this.engine = new Engine({ repo: this.repo, policy: () => policy,
      scope: { scope: () => ({ listened: true, observed: false }) },
      assessor: { request: c => this.repo.put('candidate', c.evalId, c) },
      executor: { start: (t,a) => queue('start',t,a), deliver: (t,a) => queue('deliver',t,a), stop: (t,a) => queue('stop',t,a) },
      outbox: { send: m => this.repo.put('outbox',m.id,m), status: id => this.repo.get('outbox',id) ? 'pending' : undefined, withdraw: () => {} },
      emit: (event: DomainEvent) => this.repo.put('event', randomUUID(), event),
    })
    // Official interruption handling adds a new Assignment and recovery Input.
    for (const t of this.repo.tickets.open()) {
      const a = latestAssignment(t)
      if (a?.state === 'running') this.engine.assignmentInterrupted(t.id, a.id)
    }
    this.settle()
  }
  owned(owner: Owner, id: string) {
    const b = this.repo.get<Binding>('binding', id)
    if (!b || b.org !== owner.org || b.user !== owner.user) throw Object.assign(new Error('Task not found'), { status: 404 })
    return b
  }
  settle() {
    // These are durable port effects, never shell commands or model/tool calls.
    for (const e of this.repo.list<any>('effect')) {
      if (e.done) continue
      if (this.nativeSessions && ['start','deliver'].includes(e.kind)) continue
      const t = this.repo.tickets.get(e.ticket); const a = t && latestAssignment(t)
      if (a?.id === e.assignment && e.kind === 'start' && a.state === 'pending') this.engine.assignmentStarted(t!.id,a.id)
      if (a?.id === e.assignment && e.kind === 'deliver' && a.state === 'running') {
        const ids = t!.undelivered
        this.engine.inputsDelivered(t!.id,a.id,ids)
        this.engine.inputsRead(t!.id,ids)
      }
      this.repo.put('effect',`${e.kind}:${e.assignment}`,{...e,done:true})
    }
    // A start callback may enqueue delivery in the same pass.
    const left = this.repo.list<any>('effect').some(e => !e.done && !(this.nativeSessions && ['start','deliver'].includes(e.kind)))
    if (left) this.settle()
  }
  /** Harness publication/input commit acknowledges the actual Executor port. */
  sessionStarted(owner: Owner, id: string, session: string) {
    const binding=this.owned(owner,id),ticket=this.repo.tickets.get(id)!,a=latestAssignment(ticket)
    if (!a || !['pending','running'].includes(a.state)) throw new Error('No authorized DSH Assignment for this Session')
    if (a.state==='pending') this.engine.assignmentStarted(id,a.id)
    this.repo.put('native-session',session,{ticket:id,assignment:a.id,org:owner.org,user:owner.user})
    const current=this.repo.tickets.get(id)!,ids=current.undelivered
    if(ids.length){this.engine.inputsDelivered(id,a.id,ids);this.engine.inputsRead(id,ids)}
    for(const e of this.repo.list<any>('effect')){
      if(e.assignment===a.id&&['start','deliver'].includes(e.kind))this.repo.put('effect',`${e.kind}:${e.assignment}`,{...e,done:true})
    }
    return {ticket:id,assignment:a.id,session,mandate:ticket.mandate,binding}
  }
  intake(x: Intake) {
    const started = performance.now()
    return this.repo.atomic(() => {
      const rid = hash([x.org,x.user,x.session,x.request])
      const prior = this.repo.get<any>('receipt',rid)
      if (prior) {
        if (prior.fingerprint !== hash(x)) throw Object.assign(new Error('Request id reused with different input'),{status:409})
        return {...prior.result,replayed:true}
      }
      const sessionKey = hash([x.org,x.user,x.session])
      const focus = this.repo.get<string>('focus',sessionKey)
      let target = x.new_task ? undefined : x.ticket || ((['continue','status','stop'].includes(x.mode)) ? focus : undefined)
      if (target) this.owned(x,target)
      const finish = (value: any) => {
        const result={...value,planning_ms:performance.now()-started,request:x.request}
        this.repo.put('receipt',rid,{fingerprint:hash(x),result}); return result
      }
      if (x.mode === 'chat') return finish({route:'chat',ticket:null,context_ticket:x.ticket || focus || null,execute:false})
      if (['continue','status','stop'].includes(x.mode) && !target) return finish({route:'clarify',ticket:null,execute:false,message:'请选择要继续的任务。'})
      if (x.mode === 'status') return finish({route:'status',ticket:target,execute:false})
      if (x.mode === 'stop') { this.engine.stopTicket(target!,'Stopped by owner'); this.settle(); return finish({route:'stopped',ticket:target,execute:false}) }
      // The browser selects Task/Continue explicitly. A question is never promoted by a model.
      if (!x.semantic && (/^(你好|谢谢|hi\b|hello\b)/i.test(x.text.trim()) || /^(什么是|怎么|如何|为什么)/.test(x.text.trim())))
        return finish({route:'chat',ticket:null,execute:false})
      if (target && this.repo.tickets.get(target)?.ended?.by === 'human')
        throw Object.assign(new Error('Stopped task requires a new authorization'),{status:409})
      const thread = target ? this.repo.triggers.get(this.repo.tickets.get(target)!.origin.triggerId)!.threads[0]! : {source:'image-platform',id:rid}
      const trigger: Trigger = {id:rid,source:'image-platform',threads:[thread],actor:{source:'image-platform',id:hash([x.org,x.user])},
        human:true,addressed:'direct',at:new Date().toISOString(),text:x.text,meta:{authorized:true,owner:hash([x.org,x.user])},
        channel:{source:'image-platform',thread:thread.id,address:{session:x.session}}}
      this.engine.receive(trigger)
      if (!target) {
        const d = this.engine.decide(trigger.id,{kind:'accept',title:x.text.slice(0,80),scope:x.text,reason:'Authenticated user explicitly requested a platform task'})
        target = d.ticketId!
        this.repo.put('binding',target,{org:x.org,user:x.user,session:x.session})
      }
      this.repo.put('focus',sessionKey,target)
      this.settle()
      return finish({route:x.mode === 'continue' ? 'followup' : 'new_task',ticket:target,execute:true,trigger:trigger.id})
    })
  }
  list(owner: Owner, session?: string) {
    return this.repo.tickets.list().filter(t => {
      const b=this.repo.get<Binding>('binding',t.id)
      return b?.org===owner.org && b?.user===owner.user && (!session || b.session===session)
    }).map(t=>({...t,platform:this.repo.get('binding',t.id),stage:ticketStage(t)}))
  }
  bind(owner: Owner, id: string, conversation: string) {
    const b=this.owned(owner,id)
    if (b.conversation && b.conversation!==conversation) throw new Error('Conversation binding is immutable')
    this.repo.put('binding',id,{...b,conversation});return {...b,conversation}
  }
  report(owner: Owner, id: string, state: 'progress'|'waiting'|'ready'|'failed'|'blocked', summary: string, assignment?:string) {
    this.owned(owner,id); const t=this.repo.tickets.get(id)!
    if(assignment&&latestAssignment(t)?.id!==assignment)return t
    if (t.ended) return t
    const result=this.engine.report(id,{state,summary});this.settle();return result
  }
}
