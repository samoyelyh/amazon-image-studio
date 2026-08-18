import { useCallback, useEffect, useRef } from 'react'
import { getBatchTryOnWorkflow, type BatchTryOnWorkflowResponse } from '../lib/batchTryOnWorkflowApi'

interface Options {
  enabled: boolean
  workflowJobId?: string
  onStatus: (message: string | null) => void
  onAnalysis: (workflow: BatchTryOnWorkflowResponse) => void
  onBatchReady: (batchId: string, workflowJobId: string) => Promise<void> | void
  onFailed: (message: string, workflowJobId: string) => void
}

export function useBatchTryOnWorkflowPolling(options: Options) {
  const optionsRef = useRef(options)
  optionsRef.current = options
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const deliveredBatchRef = useRef<string | null>(null)

  const stop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = null
  }, [])

  const poll = useCallback(async (workflowJobId: string) => {
    stop()
    try {
      const workflow = await getBatchTryOnWorkflow(workflowJobId)
      const current = optionsRef.current
      current.onAnalysis(workflow)
      if (workflow.status === 'failed' || workflow.status === 'cancelled') {
        current.onStatus(null)
        current.onFailed(workflow.error_message || '服务端批量套图工作流失败。', workflowJobId)
        return
      }
      if (workflow.status === 'awaiting_prompt_confirmation') {
        current.onStatus('AI 已生成最终换衣提示词，请确认或编辑后再开始图片生成。')
        return
      }
      const completedAnalysis = workflow.analysis_jobs.filter((job) => job.status === 'succeeded').length
      current.onStatus(
        workflow.batch_id
          ? `Luna 正在并发分析；已完成 ${completedAnalysis}/${workflow.analysis_call_target}，每张分析完成后会立即进入生图。`
          : `服务端正在生成模板最终换衣提示词 ${completedAnalysis}/${workflow.analysis_call_target}…`,
      )
      if (workflow.batch_id) {
        if (deliveredBatchRef.current !== workflow.batch_id) {
          deliveredBatchRef.current = workflow.batch_id
          await current.onBatchReady(workflow.batch_id, workflow.workflow_job_id)
        }
        return
      }
      timerRef.current = setTimeout(() => { void poll(workflowJobId) }, 2_000)
    } catch {
      optionsRef.current.onStatus('工作流状态同步失败，正在自动重试…')
      timerRef.current = setTimeout(() => { void poll(workflowJobId) }, 5_000)
    }
  }, [stop])

  useEffect(() => {
    deliveredBatchRef.current = null
    if (options.enabled && options.workflowJobId) void poll(options.workflowJobId)
    return stop
  }, [options.enabled, options.workflowJobId, poll, stop])

  return { pollBatchTryOnWorkflow: poll, stopBatchTryOnWorkflowPolling: stop }
}
