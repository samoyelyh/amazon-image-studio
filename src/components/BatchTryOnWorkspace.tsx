import { useEffect, useMemo, useRef } from 'react'
import type { BatchTryOnAspectRatio, BatchTryOnBatch, BatchTryOnItem, TaskParams } from '../types'
import { getImage } from '../lib/db'
import { calculateImageSize } from '../lib/size'
import { buildBatchTryOnPrompt } from '../lib/batchTryOnPrompt'
import { BatchTryOnQueueController, getFailedBatchTryOnItemIds } from '../lib/batchTryOnQueue'
import { createBatchTryOnFileNames, downloadBatchTryOnZip } from '../lib/batchTryOnFiles'
import { downloadImageIds } from '../lib/downloadImages'
import { getActiveApiProfile } from '../lib/apiProfiles'
import { runtimeConfig } from '../app/runtimeConfig'
import { uploadDataUrlAsset, importServerOutput } from '../lib/serverImageAssets'
import { getServerBatch, pauseServerBatch, resolveModelCode, resumeServerBatch, submitServerBatch } from '../lib/jobsApi'
import {
  createInputImageFromFile,
  deleteImageIfUnreferenced,
  ensureImageCached,
  getBatchTryOnProfileError,
  runBatchTryOnTask,
  useStore,
} from '../store'
import BatchTryOnTemplateUploader from './BatchTryOnTemplateUploader'
import BatchTryOnGarmentList from './BatchTryOnGarmentList'
import BatchTryOnQueue from './BatchTryOnQueue'

export const MAX_BATCH_TRY_ON_ITEMS = 50
const MAX_BATCH_TRY_ON_FILE_BYTES = 50 * 1024 * 1024
const MAX_MULTIUSER_FILE_BYTES = 20 * 1024 * 1024
const ACCEPTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])
const RATIO_OPTIONS: Array<{ value: BatchTryOnAspectRatio; label: string }> = [
  { value: 'template', label: '跟随模板图' },
  { value: '1:1', label: '1:1' },
  { value: '3:4', label: '3:4' },
  { value: '4:3', label: '4:3' },
  { value: '16:9', label: '16:9' },
  { value: '9:16', label: '9:16' },
]

export default function BatchTryOnWorkspace() {
  const batch = useStore((state) => state.batchTryOnBatch)
  const setBatch = useStore((state) => state.setBatchTryOnBatch)
  const settings = useStore((state) => state.settings)
  const globalParams = useStore((state) => state.params)
  const tasks = useStore((state) => state.tasks)
  const showToast = useStore((state) => state.showToast)
  const setLightboxImageId = useStore((state) => state.setLightboxImageId)
  const setShowSettings = useStore((state) => state.setShowSettings)
  const setConfirmDialog = useStore((state) => state.setConfirmDialog)
  const runnerRef = useRef<BatchTryOnQueueController<string> | null>(null)
  const serverPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!batch) setBatch(createEmptyBatch(globalParams))
  }, [batch, globalParams, setBatch])

  useEffect(() => {
    if (!batch) return
    setBatch((current) => {
      if (!current || current.id !== batch.id) return current
      let changed = false
      const items = current.items.map((item) => {
        if (!item.taskId) return item
        const task = tasks.find((candidate) => candidate.id === item.taskId)
        if (!task) return item
        if (task.status === 'done' && task.outputImages[0]) {
          if (item.status === 'done' && item.outputImageId === task.outputImages[0]) return item
          changed = true
          return { ...item, status: 'done' as const, outputImageId: task.outputImages[0], error: undefined, finishedAt: task.finishedAt ?? Date.now() }
        }
        if (task.status === 'error' && !task.falRecoverable && !task.customRecoverable) {
          if (item.status === 'error' && item.error === task.error) return item
          changed = true
          return { ...item, status: 'error' as const, error: task.error || '生成失败，请重试。', finishedAt: task.finishedAt ?? Date.now() }
        }
        return item
      })
      return changed ? { ...current, items, updatedAt: Date.now() } : current
    })
  }, [batch?.id, tasks, setBatch])

  const activeProfile = getActiveApiProfile(settings)
  const profileError = runtimeConfig.isStandalone ? getBatchTryOnProfileError(settings) : null
  const progress = useMemo(() => summarizeItems(batch?.items ?? []), [batch?.items])
  const outputSize = batch ? resolveOutputSize(batch) : 'auto'
  const isRunning = progress.running > 0 || Boolean(batch && !batch.queuePaused && progress.pending > 0)
  const startDisabledReason = !batch?.templateImageId
    ? '请先上传模特模板图'
    : !batch.items.length
      ? '请至少上传一张待套服装'
      : profileError
        ? profileError
        : progress.pending === 0
          ? '当前没有待处理任务'
          : ''

  const updateBatch = (patch: Partial<BatchTryOnBatch>) => {
    setBatch((current) => current ? { ...current, ...patch, updatedAt: Date.now() } : current)
  }

  const updateItem = (batchId: string, itemId: string, patch: Partial<BatchTryOnItem>) => {
    setBatch((current) => current?.id === batchId
      ? { ...current, items: current.items.map((item) => item.id === itemId ? { ...item, ...patch } : item), updatedAt: Date.now() }
      : current)
  }

  const runItem = async (itemId: string) => {
    const current = useStore.getState().batchTryOnBatch
    const item = current?.items.find((candidate) => candidate.id === itemId)
    if (!current?.templateImageId || !item) return
    const batchId = current.id
    const startedAt = Date.now()
    const size = resolveOutputSize(current)
    updateItem(batchId, itemId, { status: 'running', error: undefined, outputImageId: undefined, startedAt, finishedAt: undefined })

    try {
      const task = await runBatchTryOnTask({
        batchId,
        garmentFileName: item.garmentFileName,
        index: item.index,
        templateImageId: current.templateImageId,
        garmentImageId: item.garmentImageId,
        prompt: buildBatchTryOnPrompt({
          garmentFileName: item.garmentFileName,
          outputSize: size,
          extraRequirements: current.extraRequirements,
        }),
        params: { ...current.params, size, n: 1 },
        onTaskCreated: (taskId) => updateItem(batchId, itemId, { taskId }),
      })
      if (task.status === 'done' && task.outputImages[0]) {
        updateItem(batchId, itemId, { status: 'done', taskId: task.id, outputImageId: task.outputImages[0], error: undefined, finishedAt: task.finishedAt ?? Date.now() })
      } else {
        updateItem(batchId, itemId, { status: 'error', taskId: task.id, error: task.error || '接口没有返回图片，请重试。', finishedAt: task.finishedAt ?? Date.now() })
      }
    } catch (error) {
      updateItem(batchId, itemId, { status: 'error', error: friendlyError(error), finishedAt: Date.now() })
    }
  }

  const getRunner = () => {
    const concurrency = useStore.getState().batchTryOnBatch?.concurrency ?? 2
    if (!runnerRef.current) runnerRef.current = new BatchTryOnQueueController(runItem, concurrency)
    runnerRef.current.setConcurrency(concurrency)
    return runnerRef.current
  }

  const pollServerBatch = async (serverBatchId: string) => {
    if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
    serverPollTimerRef.current = null
    try {
      const serverBatch = await getServerBatch(serverBatchId)
      const current = useStore.getState().batchTryOnBatch
      if (!current || current.serverBatchId !== serverBatchId) return
      const jobs = new Map(serverBatch.jobs.map((job) => [job.client_item_id, job]))
      const nextItems: BatchTryOnItem[] = []
      for (const item of current.items) {
        const job = jobs.get(item.id)
        if (!job) { nextItems.push(item); continue }
        if (job.status === 'succeeded' && job.outputs[0]) {
          let outputImageId = item.outputImageId
          if (!outputImageId) outputImageId = await importServerOutput(job.outputs[0])
          nextItems.push({ ...item, taskId: job.id, outputImageId, status: 'done', error: undefined, finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : Date.now() })
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          nextItems.push({ ...item, taskId: job.id, status: job.status === 'cancelled' ? 'stopped' : 'error', error: job.error_message || (job.status === 'cancelled' ? '任务已取消' : '生成失败'), finishedAt: job.finished_at ? new Date(job.finished_at).getTime() : Date.now() })
        } else {
          nextItems.push({ ...item, taskId: job.id, status: serverBatch.status === 'paused' ? 'stopped' : 'running', error: undefined, startedAt: item.startedAt ?? Date.now() })
        }
      }
      const terminal = ['succeeded', 'failed', 'cancelled', 'partially_succeeded'].includes(serverBatch.status)
      setBatch({ ...current, items: nextItems, queuePaused: serverBatch.status === 'paused' || terminal, updatedAt: Date.now() })
      if (!terminal && serverBatch.status !== 'paused') {
        serverPollTimerRef.current = setTimeout(() => { void pollServerBatch(serverBatchId) }, 2_000)
      }
    } catch (error) {
      showToast(`批次状态同步失败，正在重试：${friendlyError(error)}`, 'error')
      serverPollTimerRef.current = setTimeout(() => { void pollServerBatch(serverBatchId) }, 5_000)
    }
  }

  const startServerItems = async (itemIds: string[]) => {
    const current = useStore.getState().batchTryOnBatch
    if (!current?.templateImageId) return
    try {
      const templateDataUrl = await ensureImageCached(current.templateImageId)
      if (!templateDataUrl) throw new Error('模特模板图读取失败，请重新上传。')
      const templateAsset = await uploadDataUrlAsset(templateDataUrl, 'model_template', current.templateFileName?.replace(/\.[^.]+$/, '') || 'model-template')
      const selectedItems = current.items.filter((item) => itemIds.includes(item.id))
      const modelCode = await resolveModelCode('multi_image_reference')
      const size = resolveOutputSize(current)
      const requestItems = []
      for (const item of selectedItems) {
        const garmentDataUrl = await ensureImageCached(item.garmentImageId)
        if (!garmentDataUrl) throw new Error(`${item.garmentFileName} 读取失败，请重新上传。`)
        const garmentAsset = await uploadDataUrlAsset(garmentDataUrl, 'garment', item.garmentFileName.replace(/\.[^.]+$/, ''))
        requestItems.push({
          client_item_id: item.id,
          prompt: buildBatchTryOnPrompt({ garmentFileName: item.garmentFileName, outputSize: size, extraRequirements: current.extraRequirements }),
          reference_asset_ids: [templateAsset.id, garmentAsset.id],
          size,
          quality: current.params.quality,
          output_format: current.params.output_format,
          metadata: { garment_filename: item.garmentFileName, index: item.index },
        })
      }
      const submitted = await submitServerBatch({
        name: `批量套图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`,
        workspace_type: 'batch_tryon',
        operation_code: 'batch_tryon.generate',
        capability: 'multi_image_reference',
        model_code: modelCode,
        idempotency_key: `batch:${crypto.randomUUID()}`,
        concurrency: current.concurrency,
        items: requestItems,
      })
      const jobByItem = new Map(submitted.jobs.map((job) => [job.client_item_id, job]))
      setBatch((latest) => latest?.id === current.id ? {
        ...latest,
        serverBatchId: submitted.id,
        queuePaused: false,
        items: latest.items.map((item) => itemIds.includes(item.id)
          ? { ...item, taskId: jobByItem.get(item.id)?.id, status: 'running', error: undefined, outputImageId: undefined, startedAt: Date.now(), finishedAt: undefined }
          : item),
        updatedAt: Date.now(),
      } : latest)
      showToast(`服务端批次已创建，共 ${submitted.total_jobs} 个任务`, 'success')
      void pollServerBatch(submitted.id)
    } catch (error) {
      setBatch((latest) => latest ? { ...latest, queuePaused: true, items: latest.items.map((item) => itemIds.includes(item.id) ? { ...item, status: 'error', error: friendlyError(error), finishedAt: Date.now() } : item), updatedAt: Date.now() } : latest)
      showToast(friendlyError(error), 'error')
    }
  }

  useEffect(() => {
    if (!runtimeConfig.isStandalone && batch?.serverBatchId && batch.items.some((item) => item.status === 'running')) {
      void pollServerBatch(batch.serverBatchId)
    }
    return () => {
      if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
      serverPollTimerRef.current = null
    }
    // 恢复只跟随服务端批次 ID，避免每次轮询更新 items 后重复启动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch?.serverBatchId])

  const startItems = (itemIds: string[]) => {
    if (!batch || itemIds.length === 0) return
    updateBatch({ queuePaused: false })
    setBatch((current) => current ? {
      ...current,
      items: current.items.map((item) => itemIds.includes(item.id) && (item.status === 'error' || item.status === 'stopped')
        ? { ...item, status: 'pending', error: undefined, taskId: undefined, outputImageId: undefined, startedAt: undefined, finishedAt: undefined }
        : item),
      updatedAt: Date.now(),
    } : current)
    if (!runtimeConfig.isStandalone) {
      void startServerItems(itemIds)
      return
    }
    void getRunner().start(itemIds).then(() => {
      setBatch((current) => current ? { ...current, queuePaused: false, updatedAt: Date.now() } : current)
    })
  }

  const pauseQueue = () => {
    if (!runtimeConfig.isStandalone && batch?.serverBatchId) {
      void pauseServerBatch(batch.serverBatchId).then(() => {
        if (serverPollTimerRef.current) clearTimeout(serverPollTimerRef.current)
        serverPollTimerRef.current = null
        setBatch((current) => current ? { ...current, queuePaused: true, items: current.items.map((item) => item.status === 'running' ? { ...item, status: 'stopped' } : item), updatedAt: Date.now() } : current)
        showToast('服务端批次已暂停；已进入上游请求的任务可能仍会完成', 'info')
      }).catch((error) => showToast(friendlyError(error), 'error'))
      return
    }
    getRunner().pause()
    updateBatch({ queuePaused: true })
    showToast('队列已暂停，正在生成的任务会继续完成', 'info')
  }

  const resumeQueue = () => {
    const current = useStore.getState().batchTryOnBatch
    if (!current) return
    if (!runtimeConfig.isStandalone && current.serverBatchId) {
      void resumeServerBatch(current.serverBatchId).then(() => {
        setBatch((latest) => latest ? { ...latest, queuePaused: false, items: latest.items.map((item) => item.status === 'stopped' ? { ...item, status: 'running' } : item), updatedAt: Date.now() } : latest)
        void pollServerBatch(current.serverBatchId!)
      }).catch((error) => showToast(friendlyError(error), 'error'))
      return
    }
    const pendingIds = current.items.filter((item) => item.status === 'pending' || item.status === 'stopped').map((item) => item.id)
    const runner = getRunner()
    runner.enqueue(pendingIds)
    updateBatch({ queuePaused: false })
    void runner.resume()
  }

  const uploadTemplate = async (files: File[]) => {
    if (isRunning || !files[0]) return
    try {
      validateImageFile(files[0])
      const image = await createInputImageFromFile(files[0])
      if (!image) throw new Error('模板图读取失败，请选择 PNG、JPG、JPEG 或 WEBP 图片。')
      const stored = await getImage(image.id)
      const previousId = batch?.templateImageId
      setBatch((current) => {
        const base = current ?? createEmptyBatch(globalParams)
        return {
          ...base,
          templateImageId: image.id,
          templateFileName: files[0].name,
          templateWidth: stored?.width,
          templateHeight: stored?.height,
          items: base.items.map(resetItemForNewRun),
          queuePaused: true,
          updatedAt: Date.now(),
        }
      })
      if (previousId && previousId !== image.id) window.setTimeout(() => void deleteImageIfUnreferenced(previousId), 0)
      showToast('模特模板图已上传', 'success')
    } catch (error) {
      showToast(friendlyError(error), 'error')
    }
  }

  const removeTemplate = () => {
    if (!batch?.templateImageId || isRunning) return
    const imageId = batch.templateImageId
    updateBatch({ templateImageId: null, templateFileName: undefined, templateWidth: undefined, templateHeight: undefined, items: batch.items.map(resetItemForNewRun), queuePaused: true })
    window.setTimeout(() => void deleteImageIfUnreferenced(imageId), 0)
  }

  const uploadGarments = async (files: File[]) => {
    if (isRunning || files.length === 0) return
    const current = batch ?? createEmptyBatch(globalParams)
    const remaining = MAX_BATCH_TRY_ON_ITEMS - current.items.length
    if (remaining <= 0) {
      showToast(`待套服装最多 ${MAX_BATCH_TRY_ON_ITEMS} 张`, 'error')
      return
    }

    const added: BatchTryOnItem[] = []
    const errors: string[] = []
    for (const file of files.slice(0, remaining)) {
      try {
        validateImageFile(file)
        const image = await createInputImageFromFile(file)
        if (!image) throw new Error('图片读取失败')
        added.push({
          id: createId(),
          batchId: current.id,
          garmentImageId: image.id,
          garmentFileName: file.name,
          index: current.items.length + added.length,
          status: 'pending',
          createdAt: Date.now(),
        })
      } catch (error) {
        errors.push(`${file.name}：${friendlyError(error)}`)
      }
    }
    if (added.length > 0) {
      setBatch({ ...current, items: [...current.items, ...added], queuePaused: true, updatedAt: Date.now() })
      showToast(`已添加 ${added.length} 张待套服装`, 'success')
    }
    if (files.length > remaining) errors.push(`超过上限的 ${files.length - remaining} 张图片未添加`)
    if (errors.length > 0) showToast(errors[0], 'error')
  }

  const removeGarment = (item: BatchTryOnItem) => {
    if (isRunning) return
    setBatch((current) => current ? {
      ...current,
      items: current.items.filter((candidate) => candidate.id !== item.id).map((candidate, index) => ({ ...candidate, index })),
      updatedAt: Date.now(),
    } : current)
    window.setTimeout(() => void deleteImageIfUnreferenced(item.garmentImageId), 0)
  }

  const clearGarments = () => {
    if (!batch || isRunning) return
    const ids = batch.items.map((item) => item.garmentImageId)
    updateBatch({ items: [], queuePaused: true })
    window.setTimeout(() => ids.forEach((id) => void deleteImageIfUnreferenced(id)), 0)
  }

  const clearBatch = () => {
    if (!batch) return
    const imageIds = [batch.templateImageId, ...batch.items.map((item) => item.garmentImageId)].filter((id): id is string => Boolean(id))
    runnerRef.current?.stopPending()
    runnerRef.current = null
    setBatch(null)
    window.setTimeout(() => imageIds.forEach((id) => void deleteImageIfUnreferenced(id)), 0)
    showToast('当前批次已清空', 'success')
  }

  const requestClearBatch = () => {
    if (progress.running === 0) {
      clearBatch()
      return
    }
    setConfirmDialog({
      title: '清空当前批次？',
      message: '已经发送的生成请求不会被强制终止，完成后仍会保留在历史记录中；尚未开始的任务会停止。',
      confirmText: '清空批次',
      cancelText: '取消',
      tone: 'warning',
      action: clearBatch,
    })
  }

  const downloadOne = async (item: BatchTryOnItem) => {
    if (!item.outputImageId) return
    const [fileName] = createBatchTryOnFileNames([item])
    const base = fileName.replace(/\.[^.]+$/, '')
    const result = await downloadImageIds([item.outputImageId], base)
    showToast(result.successCount ? '结果图已下载' : '结果图下载失败', result.successCount ? 'success' : 'error')
  }

  const downloadAll = async () => {
    if (!batch) return
    const items = batch.items.flatMap((item) => item.outputImageId ? [{ imageId: item.outputImageId, garmentFileName: item.garmentFileName, index: item.index }] : [])
    try {
      const result = await downloadBatchTryOnZip(items, batch.id)
      showToast(`已打包 ${result.successCount} 张结果${result.failCount ? `，${result.failCount} 张失败` : ''}`, result.successCount ? 'success' : 'error')
    } catch (error) {
      showToast(`批量下载失败：${friendlyError(error)}`, 'error')
    }
  }

  if (!batch) return <div className="p-6 text-sm text-gray-400">正在恢复批量套图批次...</div>

  return (
    <div className="bg-gray-50/70 p-4 dark:bg-gray-950/50 sm:p-5">
      <div className="grid gap-4 xl:grid-cols-2">
        <BatchTryOnTemplateUploader
          imageId={batch.templateImageId}
          fileName={batch.templateFileName}
          width={batch.templateWidth}
          height={batch.templateHeight}
          disabled={isRunning}
          onUpload={(files) => void uploadTemplate(files)}
          onRemove={removeTemplate}
          onView={() => batch.templateImageId && setLightboxImageId(batch.templateImageId)}
        />
        <BatchTryOnGarmentList
          items={batch.items}
          maxItems={MAX_BATCH_TRY_ON_ITEMS}
          disabled={isRunning}
          onUpload={(files) => void uploadGarments(files)}
          onRemove={removeGarment}
          onClear={clearGarments}
          onView={(imageId) => setLightboxImageId(imageId)}
        />
      </div>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.85fr)]">
          <label>
            <span className="text-sm font-bold text-gray-900 dark:text-gray-100">额外要求</span>
            <textarea value={batch.extraRequirements} disabled={isRunning} onChange={(event) => updateBatch({ extraRequirements: event.target.value })} className="mt-2 min-h-32 w-full resize-y rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100" placeholder="例如：衣服自然放下，不要塞进裤子；保持原图只展示到膝盖；服装使用印染效果，不要变成刺绣。" />
            <span className="mt-1.5 block text-xs text-gray-400">只影响当前批次，且不会覆盖内置的服装与模特保真规则。</span>
          </label>
          <div>
            <div className="text-sm font-bold text-gray-900 dark:text-gray-100">输出设置</div>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              <FieldSelect label="输出比例" value={batch.aspectRatio} disabled={isRunning} onChange={(value) => updateBatch({ aspectRatio: value as BatchTryOnAspectRatio })} options={RATIO_OPTIONS} />
              <FieldSelect label="输出质量" value={batch.params.quality} disabled={isRunning} onChange={(value) => updateBatch({ params: { ...batch.params, quality: value as TaskParams['quality'] } })} options={['high', 'medium', 'low', 'auto'].map((value) => ({ value, label: value }))} />
              <FieldSelect label="输出格式" value={batch.params.output_format} disabled={isRunning} onChange={(value) => updateBatch({ params: { ...batch.params, output_format: value as TaskParams['output_format'] } })} options={[{ value: 'jpeg', label: 'JPEG' }, { value: 'png', label: 'PNG' }, { value: 'webp', label: 'WEBP' }]} />
              <FieldSelect label="并发数" value={String(batch.concurrency)} disabled={isRunning} onChange={(value) => updateBatch({ concurrency: Number(value) as 1 | 2 | 3 })} options={[1, 2, 3].map((value) => ({ value: String(value), label: `${value}` }))} />
            </div>
            <div className="mt-3 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-xs text-gray-600 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-300">
              <div>输出尺寸：<span className="font-mono font-semibold">{outputSize}</span> · 每件服装 1 张结果</div>
              <div className="mt-1">生图配置：{runtimeConfig.isStandalone ? `${activeProfile.name} · ${activeProfile.model}` : '平台统一资源池（服务端安全调用）'}</div>
              {profileError && <button type="button" onClick={() => setShowSettings(true, 'api')} className="mt-2 text-left font-semibold text-red-600 underline decoration-red-300 underline-offset-2 dark:text-red-300">{profileError} 点击前往设置</button>}
            </div>
          </div>
        </div>
      </section>

      <section className="mt-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">任务队列与结果</h3>
            <div className="mt-1 text-sm text-gray-600 dark:text-gray-300">已完成 {progress.done} / {batch.items.length}，失败 {progress.error}，生成中 {progress.running}，等待 {progress.pending}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            {!isRunning && (batch.items.length === 0 || progress.pending > 0) && <button type="button" disabled={Boolean(startDisabledReason)} title={startDisabledReason} onClick={() => startItems(batch.items.filter((item) => item.status === 'pending').map((item) => item.id))} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">开始批量生成</button>}
            {isRunning && !batch.queuePaused && <button type="button" onClick={pauseQueue} className="h-10 rounded-xl border border-amber-200 bg-amber-50 px-3 text-sm font-semibold text-amber-700 transition hover:bg-amber-100 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-200">暂停队列</button>}
            {batch.queuePaused && (progress.stopped > 0 || (progress.pending > 0 && batch.items.some((item) => item.startedAt))) && <button type="button" disabled={Boolean(profileError || !batch.templateImageId)} onClick={resumeQueue} className="h-10 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:bg-gray-300 dark:disabled:bg-white/[0.12]">继续生成</button>}
            {progress.error > 0 && <button type="button" onClick={() => startItems(getFailedBatchTryOnItemIds(batch.items))} className="h-10 rounded-xl border border-gray-200 px-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.06]">重试失败任务</button>}
            {progress.done > 0 && <button type="button" onClick={() => void downloadAll()} className="h-10 rounded-xl border border-emerald-200 bg-emerald-50 px-3 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-100 dark:border-emerald-400/20 dark:bg-emerald-400/10 dark:text-emerald-200">下载成功结果</button>}
            <button type="button" onClick={requestClearBatch} className="h-10 rounded-xl px-3 text-sm font-medium text-red-600 transition hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-400/10">清空当前批次</button>
          </div>
        </div>
        {startDisabledReason && !isRunning && (batch.items.length === 0 || progress.pending > 0) && <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">暂时无法开始：{startDisabledReason}</div>}
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-white/[0.06]"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${batch.items.length ? ((progress.done + progress.error) / batch.items.length) * 100 : 0}%` }} /></div>
        <div className="mt-4">
          <BatchTryOnQueue items={batch.items} onView={(imageId) => setLightboxImageId(imageId, batch.items.flatMap((item) => item.outputImageId ? [item.outputImageId] : []))} onDownload={(item) => void downloadOne(item)} onRetry={(item) => startItems([item.id])} />
        </div>
      </section>
    </div>
  )
}

function FieldSelect({ label, value, options, disabled, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; disabled?: boolean; onChange: (value: string) => void }) {
  return <label className="min-w-0"><span className="mb-1 block text-xs text-gray-500 dark:text-gray-400">{label}</span><select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-gray-200 bg-gray-50 px-2 text-xs font-semibold text-gray-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-500/20 disabled:opacity-60 dark:border-white/[0.08] dark:bg-gray-900 dark:text-gray-100">{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
}

function createEmptyBatch(globalParams: TaskParams): BatchTryOnBatch {
  const now = Date.now()
  return {
    id: createId(),
    templateImageId: null,
    items: [],
    extraRequirements: '',
    aspectRatio: 'template',
    concurrency: 2,
    params: { ...globalParams, quality: 'high', n: 1 },
    queuePaused: true,
    createdAt: now,
    updatedAt: now,
  }
}

function createId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function validateImageFile(file: File) {
  if (!ACCEPTED_IMAGE_TYPES.has(file.type.toLowerCase())) throw new Error('图片格式不支持，请使用 PNG、JPG、JPEG 或 WEBP。')
  const maxBytes = runtimeConfig.isStandalone ? MAX_BATCH_TRY_ON_FILE_BYTES : MAX_MULTIUSER_FILE_BYTES
  if (file.size > maxBytes) throw new Error(`单张图片不能超过 ${maxBytes / 1024 / 1024} MB。`)
}

function resolveOutputSize(batch: BatchTryOnBatch) {
  const ratio = batch.aspectRatio === 'template'
    ? batch.templateWidth && batch.templateHeight ? `${batch.templateWidth}:${batch.templateHeight}` : '1:1'
    : batch.aspectRatio
  return calculateImageSize('2K', ratio) || 'auto'
}

function resetItemForNewRun(item: BatchTryOnItem): BatchTryOnItem {
  return { ...item, status: 'pending', taskId: undefined, outputImageId: undefined, error: undefined, startedAt: undefined, finishedAt: undefined }
}

function summarizeItems(items: BatchTryOnItem[]) {
  return items.reduce((summary, item) => {
    summary[item.status]++
    return summary
  }, { pending: 0, running: 0, done: 0, error: 0, stopped: 0 })
}

function friendlyError(error: unknown) {
  if (error instanceof DOMException && error.name === 'AbortError') return '请求超时或已中断，请重试。'
  const message = error instanceof Error ? error.message : String(error)
  if (/timeout|timed out|超时/i.test(message)) return `请求超时：${message}`
  if (/empty|没有返回|no image/i.test(message)) return `API 返回空图片：${message}`
  return message || '操作失败，请重试。'
}
