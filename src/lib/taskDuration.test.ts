import { describe, expect, it } from 'vitest'
import { calculateTaskDuration, formatDuration, parseApiDateTime } from './taskDuration'

const base = { status: 'running', createdAt: 1_000, startedAt: 2_000, finishedAt: null, elapsed: null }

describe('task duration', () => {
  it('does not count queued time as generation time', () => {
    expect(calculateTaskDuration({ ...base, serverJobId: 'job', serverJobStatus: 'queued' }, 10_000)).toBeNull()
    expect(calculateTaskDuration({ ...base, serverJobId: 'job', serverJobStatus: 'waiting_for_resource' }, 10_000)).toBeNull()
  })

  it('grows from startedAt only while the task is running', () => {
    expect(calculateTaskDuration({ ...base, serverJobId: 'job', serverJobStatus: 'running' }, 7_000)).toBe(5_000)
  })

  it.each(['done', 'error'])('uses the fixed persisted duration for %s tasks', (status) => {
    expect(calculateTaskDuration({ ...base, status, generationDurationMs: 65_000 }, 999_000)).toBe(65_000)
  })

  it('keeps retry waiting frozen at completed attempt duration', () => {
    expect(calculateTaskDuration({ ...base, serverJobId: 'job', serverJobStatus: 'retry_waiting', generationDurationMs: 4_000 }, 20_000)).toBe(4_000)
  })

  it('parses seconds, milliseconds and timezone-less UTC API values consistently', () => {
    expect(parseApiDateTime(1_700_000_000)).toBe(1_700_000_000_000)
    expect(parseApiDateTime(1_700_000_000_000)).toBe(1_700_000_000_000)
    expect(parseApiDateTime('2026-07-21T01:27:19')).toBe(Date.parse('2026-07-21T01:27:19Z'))
    expect(parseApiDateTime('2026-07-21T09:27:19+08:00')).toBe(Date.parse('2026-07-21T01:27:19Z'))
  })

  it('formats duration as hours, minutes and seconds', () => {
    expect(formatDuration(3_685_000)).toBe('01:01:25')
  })
})
