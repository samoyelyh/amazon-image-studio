import { expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SharedQueueView } from './BatchTryOnSharedQueue'
import { formatQueueWait, type SharedQueueBoard } from '../lib/batchTryOnSharedQueueApi'

export const queueFixture: SharedQueueBoard = {
  snapshot_at: '2026-10-30T10:00:00Z', truncated: false,
  running_count: 6, waiting_count: 10, failed_count: 1, analysis_running: 2,
  capacity: { configured: 6, effective: 6, in_use: 6, source: 'redis_lease', reason: '图片与Luna共用6个槽位' },
  entries: [
    { id: 'my-tab', name: '礼品场景 · 本周新品', creator_name: '我', created_at: '2026-10-30T08:20:00Z',
      status: 'running', total_count: 32, completed_count: 20, processed_count: 21, running_count: 4, waiting_count: 7,
      failed_count: 1, cancelled_count: 0, retrying_count: 1, analysis_running: 1, auxiliary_running: 0,
      ahead_count: 0, progress_percent: 66, can_open: true, navigation: { project_id: 'mine', workspace_id: 'my-tab', batch_id: null },
      estimate: { minimum_seconds: 90, maximum_seconds: 360, sample_count: 20, reason: '历史耗时区间估计，不保证上游开始时间' } },
    { id: 'colleague-tab', name: '观赛场景 · 秋季系列', creator_name: '同事小林', created_at: '2026-10-30T08:30:00Z',
      status: 'running', total_count: 16, completed_count: 11, processed_count: 11, running_count: 2, waiting_count: 3,
      failed_count: 0, cancelled_count: 0, retrying_count: 0, analysis_running: 1, auxiliary_running: 0,
      ahead_count: 7, progress_percent: 69, can_open: false, navigation: null,
      estimate: { minimum_seconds: null, maximum_seconds: null, sample_count: 0, reason: '等待AI分析完成' } },
  ],
}

it('renders a locked summary for colleagues without a detail link', () => {
  const html = renderToStaticMarkup(<SharedQueueView board={queueFixture} onOpen={vi.fn()} />)
  expect(html).toContain('同事小林')
  expect(html).toContain('仅创建人可进入')
  expect(html).toContain('disabled=""')
  expect(html).toContain('进入我的任务')
  expect(html).not.toContain('href=')
  expect(html).not.toContain('<img')
})

it('does not invent a countdown when estimates are unavailable', () => {
  expect(formatQueueWait(queueFixture.entries[1].estimate)).toBe('暂无可靠估计')
  expect(formatQueueWait(queueFixture.entries[0].estimate)).toBe('约 1–6 分钟')
})
