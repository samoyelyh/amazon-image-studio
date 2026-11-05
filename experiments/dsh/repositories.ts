import { DatabaseSync } from 'node:sqlite'
import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import type { Repositories, Trigger, Thread, Ticket, Decision, TriggerDisposition } from './upstream/src/core/index.ts'

/** Platform adapter for the official, synchronous Repositories port. */
export class SqliteRepositories implements Repositories {
  db: DatabaseSync
  depth = 0
  constructor(path: string) {
    mkdirSync(dirname(path), { recursive: true })
    this.db = new DatabaseSync(path)
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
      CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, value TEXT NOT NULL, PRIMARY KEY(kind,id));`)
  }
  get<T>(kind: string, id: string): T | undefined {
    const row = this.db.prepare('SELECT value FROM records WHERE kind=? AND id=?').get(kind, id)
    return row ? JSON.parse(String(row.value)) : undefined
  }
  put(kind: string, id: string, value: unknown) {
    this.db.prepare('INSERT INTO records VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET value=excluded.value')
      .run(kind, id, JSON.stringify(value))
  }
  list<T>(kind: string): T[] {
    return this.db.prepare('SELECT value FROM records WHERE kind=? ORDER BY rowid').all(kind).map(r => JSON.parse(String(r.value)))
  }
  atomic<T>(work: () => T): T {
    if (this.depth) return work()
    this.db.exec('BEGIN IMMEDIATE'); this.depth++
    try { const value = work(); this.db.exec('COMMIT'); return value }
    catch (error) { this.db.exec('ROLLBACK'); throw error }
    finally { this.depth-- }
  }
  triggers = {
    get: (id: string) => this.get<Trigger>('trigger', id),
    save: (t: Trigger) => this.put('trigger', t.id, t),
    disposition: (id: string) => this.get<TriggerDisposition>('disposition', id),
    saveDisposition: (id: string, v: TriggerDisposition) => this.put('disposition', id, v),
  }
  threads = {
    get: (id: string) => this.get<Thread>('thread', id), save: (t: Thread) => this.put('thread', t.key, t),
    list: () => this.list<Thread>('thread'),
    active: () => this.list<Thread>('thread').filter(t => t.pending.length || t.evaluating),
  }
  tickets = {
    get: (id: string) => this.get<Ticket>('ticket', id), save: (t: Ticket) => this.put('ticket', t.id, t),
    list: () => this.list<Ticket>('ticket'), open: () => this.list<Ticket>('ticket').filter(t => !t.ended),
    active: () => this.list<Ticket>('ticket').filter(t => t.undelivered.length || ['pending', 'running'].includes(t.assignments.at(-1)?.state ?? '')),
  }
  decisions = {
    get: (id: string) => this.get<Decision>('decision', id), save: (d: Decision) => this.put('decision', d.id, d),
    byThread: (id: string) => this.list<Decision>('decision').filter(d => d.threadKey === id),
  }
}
