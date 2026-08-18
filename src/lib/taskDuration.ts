const SERVER_WAITING_STATUSES = new Set(['queued', 'dispatching', 'waiting_for_resource', 'retry_waiting'])

export interface TaskDurationSource {
  status: string
  createdAt: number
  startedAt?: number | null
  finishedAt?: number | null
  elapsed?: number | null
  generationDurationMs?: number | null
  serverJobId?: string
  serverJobStatus?: string
}

export function parseApiDateTime(value: string | number | null | undefined): number | null {
  if (value == null || value === '') return null
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    return Math.abs(value) < 100_000_000_000 ? value * 1000 : value
  }
  const trimmed = value.trim()
  if (!trimmed) return null
  if (/^-?\d+(?:\.\d+)?$/.test(trimmed)) return parseApiDateTime(Number(trimmed))
  // MySQL DATETIME values are stored as UTC but may lose tzinfo when loaded.
  const explicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed)
  const parsed = Date.parse(explicitZone ? trimmed : `${trimmed}Z`)
  return Number.isFinite(parsed) ? parsed : null
}

export function isTaskWaitingForGeneration(task: TaskDurationSource): boolean {
  return Boolean(task.serverJobId && task.serverJobStatus && SERVER_WAITING_STATUSES.has(task.serverJobStatus))
}

export function calculateTaskDuration(task: TaskDurationSource, now = Date.now()): number | null {
  if (isTaskWaitingForGeneration(task)) return task.generationDurationMs || null

  const persisted = task.generationDurationMs
  const startedAt = task.startedAt ?? (task.serverJobId ? null : task.createdAt)
  const isLive = task.status === 'running' && (!task.serverJobId || task.serverJobStatus === 'running')

  if (isLive && startedAt != null) {
    return Math.max(0, (persisted ?? 0) + now - startedAt)
  }
  if (persisted != null) return Math.max(0, persisted)
  if (startedAt != null && task.finishedAt != null) return Math.max(0, task.finishedAt - startedAt)
  if (task.elapsed != null) return Math.max(0, task.elapsed)
  return null
}

export function formatDuration(milliseconds: number | null | undefined): string {
  if (milliseconds == null || !Number.isFinite(milliseconds)) return '--:--:--'
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000))
  const hours = String(Math.floor(totalSeconds / 3600)).padStart(2, '0')
  const minutes = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, '0')
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}
