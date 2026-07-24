import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, type Project } from '../lib/contentApi'
import { sendListingOutputToBatchTryOn } from '../lib/listingTransferApi'
import { randomUuid } from '../lib/randomUuid'
import type { TaskRecord } from '../types'
import { getServerJob } from '../lib/jobsApi'
import { updateTaskInStore } from '../store'
import AuthenticatedImage from './AuthenticatedImage'
import { BatchTryOnImage } from './BatchTryOnImage'


interface Props {
  task: TaskRecord
  outputIndex?: number
  onClose: () => void
}


function templateLink(project: Project) {
  return project.assets.find((link) => link.role === 'model_template')
}


export default function SendToBatchTryOnDialog({ task, outputIndex = 0, onClose }: Props) {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'create_project' | 'existing_project'>('create_project')
  const [projects, setProjects] = useState<Project[]>([])
  const [projectName, setProjectName] = useState(`${task.category?.productTitle?.trim() || 'Listing项目'}-批量套图`)
  const [description, setDescription] = useState('')
  const [targetProjectId, setTargetProjectId] = useState('')
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [confirmReplace, setConfirmReplace] = useState(false)
  const idempotencyKey = useRef(`listing-transfer:${randomUuid()}`)
  const [resolvedOutputId, setResolvedOutputId] = useState(task.serverGeneratedOutputIds?.[outputIndex] || '')
  const outputId = resolvedOutputId
  const imageId = task.outputImages[outputIndex]
  const assetId = task.serverOutputAssetIds?.[outputIndex]
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === targetProjectId),
    [projects, targetProjectId],
  )
  const existingTemplate = selectedProject ? templateLink(selectedProject) : undefined
  const width = task.actualWidth ?? task.requestedWidth
  const height = task.actualHeight ?? task.requestedHeight

  useEffect(() => {
    let active = true
    void listProjects('batch_tryon')
      .then((page) => {
        if (!active) return
        const editable = page.items.filter((project) => project.status === 'draft')
        setProjects(editable)
        setTargetProjectId((current) => current || editable[0]?.id || '')
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : '批量套图项目读取失败')
      })
      .finally(() => {
        if (active) setLoadingProjects(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (outputId || !task.serverJobId) return
    let active = true
    void getServerJob(task.serverJobId).then((job) => {
      if (!active) return
      const matched = job.outputs.find((output) => output.asset_id === assetId) ?? job.outputs[outputIndex]
      if (!matched) throw new Error('服务端生成结果记录不存在')
      setResolvedOutputId(matched.id)
      updateTaskInStore(task.id, {
        serverOutputAssetIds: job.outputs.map((output) => output.asset_id),
        serverGeneratedOutputIds: job.outputs.map((output) => output.id),
      })
    }).catch((reason) => {
      if (active) setError(reason instanceof Error ? reason.message : '服务端生成结果读取失败')
    })
    return () => { active = false }
  }, [assetId, outputId, outputIndex, task.id, task.serverJobId])

  const submit = async (replaceExisting = false) => {
    if (!outputId || !assetId) {
      setError('当前结果没有完整的服务端生成记录，无法发送。')
      return
    }
    if (mode === 'create_project' && !projectName.trim()) {
      setError('请输入批量套图项目名称。')
      return
    }
    if (mode === 'existing_project' && !selectedProject) {
      setError('请选择目标批量套图项目。')
      return
    }
    if (mode === 'existing_project' && existingTemplate && existingTemplate.asset.id !== assetId && !replaceExisting) {
      setConfirmReplace(true)
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const result = await sendListingOutputToBatchTryOn(outputId, {
        target_mode: mode,
        project_name: mode === 'create_project' ? projectName.trim() : undefined,
        project_description: mode === 'create_project' ? description.trim() || undefined : undefined,
        target_project_id: mode === 'existing_project' ? selectedProject?.id : undefined,
        replace_existing_template: mode === 'existing_project' ? replaceExisting : false,
        idempotency_key: idempotencyKey.current,
      })
      onClose()
      navigate(result.redirect_path, {
        state: { source: 'listing', templateUpdated: true, warnings: result.warnings },
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发送失败，请稍后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-4" role="dialog" aria-modal="true" aria-label="发送到批量套图">
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white shadow-2xl dark:bg-gray-900">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 dark:border-white/[0.08]">
          <div><h2 className="text-lg font-bold text-gray-950 dark:text-white">发送到批量套图</h2><p className="mt-1 text-xs text-gray-500">直接复用服务端 Asset，不会复制或移动原 Listing 图片。</p></div>
          <button type="button" disabled={submitting} onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-white/[0.06]">关闭</button>
        </div>

        <div className="grid gap-5 p-5 lg:grid-cols-[220px_minmax(0,1fr)]">
          <section>
            <div className="aspect-[4/3] overflow-hidden rounded-xl bg-gray-100 dark:bg-gray-950">
              {imageId ? <BatchTryOnImage imageId={imageId} alt="Listing生成结果" className="h-full w-full object-contain" /> : <div className="flex h-full items-center justify-center text-xs text-gray-400">图片不可用</div>}
            </div>
            <div className="mt-3 space-y-1 text-xs text-gray-500 dark:text-gray-400">
              <div className="font-semibold text-gray-800 dark:text-gray-200">{task.category?.productTitle || 'Listing 图生成结果'}</div>
              <div>发送版本：v{outputIndex + 1}</div>
              <div>图片尺寸：{width && height ? `${width} × ${height}` : '等待读取'}</div>
              <div>图片比例：{task.requestedAspectRatio || (width && height ? `${width}:${height}` : '未知')}</div>
              <div>文件格式：{String(task.params.output_format || 'png').toUpperCase()}</div>
            </div>
          </section>

          <section>
            <div className="grid grid-cols-2 gap-2 rounded-xl bg-gray-100 p-1 dark:bg-white/[0.05]">
              <button type="button" onClick={() => { setMode('create_project'); setConfirmReplace(false) }} className={`rounded-lg px-3 py-2 text-sm font-semibold ${mode === 'create_project' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800 dark:text-blue-300' : 'text-gray-500'}`}>创建新项目</button>
              <button type="button" onClick={() => { setMode('existing_project'); setConfirmReplace(false) }} className={`rounded-lg px-3 py-2 text-sm font-semibold ${mode === 'existing_project' ? 'bg-white text-blue-700 shadow-sm dark:bg-gray-800 dark:text-blue-300' : 'text-gray-500'}`}>发送到已有项目</button>
            </div>

            {mode === 'create_project' ? (
              <div className="mt-4 space-y-3">
                <label className="block"><span className="text-xs font-semibold text-gray-700 dark:text-gray-300">批量项目名称</span><input value={projectName} maxLength={160} onChange={(event) => setProjectName(event.target.value)} className="mt-1.5 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" /></label>
                <label className="block"><span className="text-xs font-semibold text-gray-700 dark:text-gray-300">项目备注（可选）</span><textarea value={description} maxLength={500} onChange={(event) => setDescription(event.target.value)} className="mt-1.5 min-h-24 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" /></label>
              </div>
            ) : (
              <div className="mt-4">
                {loadingProjects ? <div className="py-10 text-center text-sm text-gray-400">正在读取可编辑项目…</div> : projects.length === 0 ? <div className="rounded-xl border border-dashed border-gray-200 py-10 text-center text-sm text-gray-500 dark:border-white/[0.1]">暂无可编辑的批量套图项目</div> : <div className="max-h-72 space-y-2 overflow-y-auto pr-1">{projects.map((project) => {
                  const template = templateLink(project)
                  return <button key={project.id} type="button" onClick={() => { setTargetProjectId(project.id); setConfirmReplace(false) }} className={`grid w-full grid-cols-[56px_minmax(0,1fr)] gap-3 rounded-xl border p-2.5 text-left transition ${targetProjectId === project.id ? 'border-blue-500 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-200 hover:border-gray-300 dark:border-white/[0.1]'}`}>
                    <div className="h-14 w-14 overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-950">{template?.asset.url ? <AuthenticatedImage src={template.asset.url} alt="当前模板" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-gray-400">无模板</div>}</div>
                    <div className="min-w-0"><div className="truncate text-sm font-semibold text-gray-900 dark:text-white">{project.name}</div><div className="mt-1 text-xs text-gray-500">创建人 {project.created_by} · 更新 {new Date(project.updated_at).toLocaleString('zh-CN', { hour12: false })}</div><div className="mt-1 text-[11px] text-gray-400">状态：{project.status === 'draft' ? '可编辑' : project.status}</div></div>
                  </button>
                })}</div>}
              </div>
            )}

            {confirmReplace && selectedProject && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"><div className="font-semibold">该项目已经设置了模特模板图。</div><p className="mt-1 text-xs leading-relaxed">继续操作会把模板替换为当前 Listing 生成图，但不会删除原图片或原 Listing 生成记录。</p><div className="mt-3 flex gap-2"><button type="button" onClick={() => setConfirmReplace(false)} className="rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-semibold">取消替换</button><button type="button" disabled={submitting} onClick={() => void submit(true)} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">替换并进入项目</button></div></div>}
            {error && <div className="mt-4 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-200">{error}</div>}
          </section>
        </div>

        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4 dark:border-white/[0.08]">
          <button type="button" disabled={submitting} onClick={onClose} className="rounded-xl border border-gray-200 px-4 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200">取消</button>
          <button type="button" disabled={submitting || !outputId || (mode === 'existing_project' && !targetProjectId)} onClick={() => void submit(false)} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{submitting ? '正在发送…' : mode === 'create_project' ? '创建并进入项目' : '确认发送'}</button>
        </div>
      </div>
    </div>
  )
}
