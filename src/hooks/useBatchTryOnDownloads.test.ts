import { expect, it } from 'vitest'
import { currentQueueBatchIds } from './useBatchTryOnDownloads'
import type { BatchTryOnBatch } from '../types'

it('exports every production submission in the current queue, not only the most recent', () => {
  const batch = { serverBatchId: 'batch-2', serverBatchIds: ['sample', 'batch-1', 'batch-2'], items: [
    { id: 'validation:t1:1', serverBatchId: 'sample' },
    { id: 'item1', serverBatchId: 'batch-1' }, { id: 'item2', serverBatchId: 'batch-2' },
    { id: 'item3', serverBatchId: 'batch-1' },
  ] } as BatchTryOnBatch
  expect(currentQueueBatchIds(batch)).toEqual(['batch-1', 'batch-2'])
})
