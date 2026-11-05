import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import BatchTryOnQueueSettings from './BatchTryOnQueueSettings'
import type { RetentionSettings } from '../lib/batchTryOnSharedQueueApi'

const settings: RetentionSettings = { enabled: true, days: 3, action: 'delete', age_basis: 'last_activity',
  revision: 1, can_manage: true, last_run_at: null, last_run_summary: {}, pending_storage_count: 0 }
it('shows configurable server retention and irreversible deletion confirmation', () => {
  const html = renderToStaticMarkup(<BatchTryOnQueueSettings initialSettings={settings} onClose={() => {}} onChanged={() => {}} />)
  expect(html).toContain('队列自动清理设置')
  expect(html).toContain('value="3"')
  expect(html).toContain('永久清理不可撤销')
  expect(html).toContain('永久删除确认文字')
  expect(html).toMatch(/disabled=""[^>]*>保存设置/)
  expect(html).not.toContain('立即执行本轮清理') // No execution before preview.
})
it('makes colleague settings read-only', () => {
  const html = renderToStaticMarkup(<BatchTryOnQueueSettings initialSettings={{ ...settings, can_manage: false }} onClose={() => {}} onChanged={() => {}} />)
  expect(html).toContain('只有团队管理员可以修改')
  expect(html).toContain('<fieldset disabled=""')
})
