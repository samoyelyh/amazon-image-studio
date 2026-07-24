import { describe, expect, it } from 'vitest'
import type { TaskRecord } from '../types'
import { isListingTransferTask, listingTransferDisabledReason } from './listingTransferEligibility'


function task(overrides: Partial<TaskRecord> = {}): TaskRecord {
  return {
    id: 'job-1',
    serverJobId: 'job-1',
    serverWorkspaceType: 'listing',
    serverOutputAssetIds: ['asset-1'],
    serverGeneratedOutputIds: ['output-1'],
    prompt: 'listing image',
    params: {
      size: '1024x1024',
      aspect_ratio: '1:1',
      quality: 'high',
      output_format: 'png',
      output_compression: null,
      moderation: 'auto',
      n: 1,
    },
    inputImageIds: [],
    outputImages: ['image-1'],
    status: 'done',
    error: null,
    createdAt: Date.now(),
    finishedAt: Date.now(),
    elapsed: 1000,
    ...overrides,
  }
}


const allowed = {
  isStandalone: false,
  canReadGeneratedOutputs: true,
  canWriteProjects: true,
}


describe('Listing 结果发送资格', () => {
  it('识别服务端 Listing 任务并允许成功结果发送', () => {
    const result = task()
    expect(isListingTransferTask(result)).toBe(true)
    expect(listingTransferDisabledReason(result, allowed)).toBe('')
  })

  it('禁止生成失败的结果发送', () => {
    expect(listingTransferDisabledReason(task({ status: 'error' }), allowed)).toBe('生成失败的结果不能发送')
  })

  it('禁止没有服务端 Asset 的浏览器结果发送', () => {
    expect(listingTransferDisabledReason(task({ serverOutputAssetIds: undefined }), allowed)).toContain('服务端 Asset')
  })

  it('不把 A+ 任务显示为 Listing 发送入口', () => {
    expect(isListingTransferTask(task({ serverWorkspaceType: 'aplus', category: undefined }))).toBe(false)
  })
})
