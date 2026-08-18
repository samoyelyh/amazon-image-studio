import { useCallback, useEffect, useRef } from 'react'
import type { ServerJobBatchDiagnostics } from '../lib/jobsApi'
import { getServerBatch, getServerBatchDiagnostics, getServerJobsByIds } from '../lib/jobsApi'
import { importServerOutput } from '../lib/serverImageAssets'
import {
  activeServerJobIds,
  buildBatchTryOnServerJobPatch,
  isTerminalServerBatchStatus,
  restorableRegenerationTaskIds,
  selectCurrentBatchTryOnJobs,
} from '../lib/batchTryOnServerSync'
import { restoreServerStyleProfiles } from '../lib/batchTryOnWorkspaceState'
import { useStore } from '../store'
import type { BatchTryOnItem } from '../types'

interface UseBatchTryOnServerPollingOptions {
  enabled: boolean
  batchId?: string
  serverBatchId?: string
  serverBatchIds?: string[]
  canReadAudit: boolean
  onDiagnostics: (value: ServerJobBatchDiagnostics | null) => void
  onError: (message: string) => void
  formatError: (error: unknown) => string
}

export function useBatchTryOnServerPolling(options: UseBatchTryOnServerPollingOptions) {
  const optionsRef = useRef(options)
  optionsRef.current = options
  const serverTimerRefs = useRef(new Map<string, ReturnType<typeof setTimeout>>())
  const regenerationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const setBatch = useStore((state) => state.setBatchTryOnBatch)

  const stopServerPolling = useCallback(() => {
    for (const timer of serverTimerRefs.current.values()) clearTimeout(timer)
    serverTimerRefs.current.clear()
  }, [])

  const stopRegenerationPolling = useCallback(() => {
    if (regenerationTimerRef.current) clearTimeout(regenerationTimerRef.current)
    regenerationTimerRef.current = null
  }, [])

  const pollServerBatch = useCallback(async (serverBatchId: string) => {
    const previousTimer = serverTimerRefs.current.get(serverBatchId)
    if (previousTimer) clearTimeout(previousTimer)
    serverTimerRefs.current.delete(serverBatchId)
    try {
      const serverBatch = await getServerBatch(serverBatchId)
      const currentOptions = optionsRef.current
      if (currentOptions.canReadAudit && currentOptions.serverBatchId === serverBatchId) {
        void getServerBatchDiagnostics(serverBatchId)
          .then(currentOptions.onDiagnostics)
          .catch(() => currentOptions.onDiagnostics(null))
      }
      const current = useStore.getState().batchTryOnBatch
      const trackedBatchIds = new Set([...(current?.serverBatchIds || []), current?.serverBatchId].filter(Boolean))
      if (!current || !trackedBatchIds.has(serverBatchId)) return
      const jobs = selectCurrentBatchTryOnJobs(serverBatch.jobs)
      const nextItems: BatchTryOnItem[] = []
      for (const item of current.items) {
        const job = jobs.get(item.id)
        if (!job) { nextItems.push(item); continue }
        const patch = await buildBatchTryOnServerJobPatch(item, job, {
          mode: 'batch',
          paused: serverBatch.status === 'paused',
          importOutput: importServerOutput,
        })
        nextItems.push({ ...item, ...patch })
      }
      const terminal = isTerminalServerBatchStatus(serverBatch.status)
      const restoredProfiles = serverBatch.style_profiles?.length
        ? restoreServerStyleProfiles(serverBatch.style_profiles, current.garments)
        : []
      const recoveredProfiles = restoredProfiles.some((profile) => (
        Object.values(profile.garmentStructure).some((value) => Boolean(value))
      )) ? restoredProfiles : current.styleProfiles
      // Multiple submitted groups may be polled concurrently. Only write items owned by
      // this server batch so an older poll response cannot roll back another group's state.
      const patches = new Map(nextItems.filter((item) => jobs.has(item.id)).map((item) => [item.id, item]))
      setBatch((latest) => {
        if (!latest) return latest
        const items = latest.items.map((item) => patches.get(item.id) || item)
        const anyActive = items.some((item) => ['queued', 'retry_waiting', 'running'].includes(item.status))
        return {
          ...latest,
          items,
          styleProfiles: latest.serverBatchId === serverBatchId ? recoveredProfiles : latest.styleProfiles,
          queuePaused: anyActive ? false : latest.queuePaused || serverBatch.status === 'paused' || terminal,
          updatedAt: Date.now(),
        }
      })
      if (!terminal && serverBatch.status !== 'paused') {
        serverTimerRefs.current.set(serverBatchId, setTimeout(() => { void pollServerBatch(serverBatchId) }, 2_000))
      }
    } catch (error) {
      const currentOptions = optionsRef.current
      currentOptions.onError(`批次状态同步失败，正在重试：${currentOptions.formatError(error)}`)
      serverTimerRefs.current.set(serverBatchId, setTimeout(() => { void pollServerBatch(serverBatchId) }, 5_000))
    }
  }, [setBatch])

  const pollRegeneratedJobs = useCallback(async (taskIds: string[]) => {
    stopRegenerationPolling()
    const uniqueTaskIds = [...new Set(taskIds)]
    if (!uniqueTaskIds.length) return
    try {
      const jobs = await getServerJobsByIds(uniqueTaskIds)
      const jobsById = new Map(jobs.map((job) => [job.id, job]))
      const current = useStore.getState().batchTryOnBatch
      if (!current) return
      const patches = new Map<string, Partial<BatchTryOnItem>>()
      for (const item of current.items) {
        const job = item.taskId ? jobsById.get(item.taskId) : undefined
        if (!job) continue
        patches.set(item.id, await buildBatchTryOnServerJobPatch(item, job, {
          mode: 'regeneration',
          importOutput: importServerOutput,
        }))
      }
      setBatch((latest) => latest?.id === current.id ? {
        ...latest,
        items: latest.items.map((item) => {
          const patch = patches.get(item.id)
          return patch ? { ...item, ...patch } : item
        }),
        queuePaused: false,
        updatedAt: Date.now(),
      } : latest)
      const activeTaskIds = activeServerJobIds(jobs)
      if (activeTaskIds.length) {
        regenerationTimerRef.current = setTimeout(
          () => { void pollRegeneratedJobs(activeTaskIds) },
          2_000,
        )
      }
    } catch {
      regenerationTimerRef.current = setTimeout(
        () => { void pollRegeneratedJobs(uniqueTaskIds) },
        5_000,
      )
    }
  }, [setBatch, stopRegenerationPolling])

  useEffect(() => {
    const batchIds = [...new Set([...(options.serverBatchIds || []), options.serverBatchId].filter((value): value is string => Boolean(value)))]
    if (options.enabled) for (const batchId of batchIds) void pollServerBatch(batchId)
    return stopServerPolling
  }, [options.enabled, options.serverBatchId, options.serverBatchIds, pollServerBatch, stopServerPolling])

  useEffect(() => {
    if (!options.enabled) return
    const current = useStore.getState().batchTryOnBatch
    const taskIds = restorableRegenerationTaskIds(current?.items ?? [])
    if (taskIds.length) void pollRegeneratedJobs(taskIds)
    return stopRegenerationPolling
  }, [options.enabled, options.batchId, pollRegeneratedJobs, stopRegenerationPolling])

  return {
    pollServerBatch,
    pollRegeneratedJobs,
    stopServerPolling,
    stopRegenerationPolling,
  }
}
