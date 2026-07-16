export function buildBatchTryOnReferenceOrder(templateImageId: string, garmentImageId: string): [string, string] {
  return [templateImageId, garmentImageId]
}

export function getFailedBatchTryOnItemIds(items: Array<{ id: string; status: string }>) {
  return items.filter((item) => item.status === 'error').map((item) => item.id)
}

export interface BatchTryOnQueueSnapshot {
  activeCount: number
  waitingCount: number
  paused: boolean
}

export class BatchTryOnQueueController<T> {
  private readonly worker: (item: T) => Promise<void>
  private readonly queued = new Set<T>()
  private readonly active = new Set<T>()
  private readonly waiters = new Set<() => void>()
  private concurrency: number
  private paused = true

  constructor(worker: (item: T) => Promise<void>, concurrency = 2) {
    this.worker = worker
    this.concurrency = normalizeConcurrency(concurrency)
  }

  get snapshot(): BatchTryOnQueueSnapshot {
    return {
      activeCount: this.active.size,
      waitingCount: this.queued.size,
      paused: this.paused,
    }
  }

  setConcurrency(concurrency: number) {
    this.concurrency = normalizeConcurrency(concurrency)
    this.pump()
  }

  enqueue(items: Iterable<T>) {
    for (const item of items) {
      if (!this.active.has(item)) this.queued.add(item)
    }
    this.pump()
  }

  start(items: Iterable<T> = []) {
    this.enqueue(items)
    this.paused = false
    this.pump()
    return this.waitForIdle()
  }

  pause() {
    this.paused = true
  }

  resume() {
    this.paused = false
    this.pump()
    return this.waitForIdle()
  }

  stopPending() {
    this.paused = true
    this.queued.clear()
    this.resolveIfIdle()
  }

  waitForIdle(): Promise<void> {
    if (this.active.size === 0 && this.queued.size === 0) return Promise.resolve()
    return new Promise((resolve) => this.waiters.add(resolve))
  }

  private pump() {
    if (this.paused) return
    while (this.active.size < this.concurrency && this.queued.size > 0) {
      const item = this.queued.values().next().value as T
      this.queued.delete(item)
      this.active.add(item)
      void Promise.resolve()
        .then(() => this.worker(item))
        .catch(() => undefined)
        .finally(() => {
          this.active.delete(item)
          this.pump()
          this.resolveIfIdle()
        })
    }
    this.resolveIfIdle()
  }

  private resolveIfIdle() {
    if (this.active.size > 0 || this.queued.size > 0) return
    for (const resolve of this.waiters) resolve()
    this.waiters.clear()
  }
}

function normalizeConcurrency(value: number) {
  if (!Number.isFinite(value)) return 2
  return Math.min(3, Math.max(1, Math.trunc(value)))
}
