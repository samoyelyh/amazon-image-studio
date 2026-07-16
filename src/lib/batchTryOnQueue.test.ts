import { describe, expect, it } from 'vitest'
import { BatchTryOnQueueController, buildBatchTryOnReferenceOrder, getFailedBatchTryOnItemIds } from './batchTryOnQueue'

describe('batch try-on reference image order', () => {
  it('always places the model template before the garment', () => {
    expect(buildBatchTryOnReferenceOrder('template-id', 'garment-id')).toEqual(['template-id', 'garment-id'])
  })
})

describe('BatchTryOnQueueController', () => {
  it('never exceeds the configured concurrency', async () => {
    let active = 0
    let maxActive = 0
    const controller = new BatchTryOnQueueController<number>(async () => {
      active++
      maxActive = Math.max(maxActive, active)
      await new Promise((resolve) => setTimeout(resolve, 5))
      active--
    }, 2)

    await controller.start([1, 2, 3, 4, 5])
    expect(maxActive).toBe(2)
  })

  it('does not start new work while paused and continues after resume', async () => {
    const started: number[] = []
    let releaseFirst: () => void = () => undefined
    const firstGate = new Promise<void>((resolve) => { releaseFirst = () => resolve() })
    const controller = new BatchTryOnQueueController<number>(async (item) => {
      started.push(item)
      if (item === 1) await firstGate
    }, 1)

    void controller.start([1, 2, 3])
    await flushMicrotasks()
    expect(started).toEqual([1])
    controller.pause()
    releaseFirst()
    await flushMicrotasks()
    expect(started).toEqual([1])
    await controller.resume()
    expect(started).toEqual([1, 2, 3])
  })

  it('continues remaining work after one task fails', async () => {
    const completed: number[] = []
    const controller = new BatchTryOnQueueController<number>(async (item) => {
      if (item === 2) throw new Error('expected failure')
      completed.push(item)
    }, 2)

    await controller.start([1, 2, 3])
    expect(completed).toEqual([1, 3])
  })

  it('selects only failed tasks for retry', () => {
    expect(getFailedBatchTryOnItemIds([
      { id: 'done', status: 'done' },
      { id: 'failed-a', status: 'error' },
      { id: 'pending', status: 'pending' },
      { id: 'failed-b', status: 'error' },
    ])).toEqual(['failed-a', 'failed-b'])
  })
})

async function flushMicrotasks() {
  await Promise.resolve()
  await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
}
