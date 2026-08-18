import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { runtimeConfig } from '../app/runtimeConfig'
import AuthenticatedImage from '../components/AuthenticatedImage'
import { uploadAsset } from '../lib/contentApi'
import { cancelServerJob, getServerJob, type JobOutput, type ServerJob } from '../lib/jobsApi'
import { scaleSelectionBounds, scaleStrokes, workingImageSize, type SelectionBounds } from '../lib/materialExtractCanvas'
import { submitMaterialExtract, type MaterialPoint, type MaterialStroke } from '../lib/materialExtractApi'
import { randomUuid } from '../lib/randomUuid'
import { downloadServerOutput } from '../lib/serverDownloads'
import { useImagePaste } from '../hooks/useImagePaste'

type Tool = 'select' | 'erase'
type PreviewBackground = 'checker' | 'white' | 'black'

const activeStatuses = new Set(['queued', 'dispatching', 'running', 'retrying', 'waiting_resource'])
const acceptedTypes = new Set(['image/jpeg', 'image/png', 'image/webp'])

function statusText(job: ServerJob | null) {
  if (!job) return ''
  if (job.status === 'succeeded') return '素材提取完成'
  if (job.status === 'failed') return '素材提取失败'
  if (job.status === 'cancelled') return '任务已取消'
  if (job.status === 'waiting_resource') return '正在等待可用图片通道'
  if (job.status === 'retrying') return '上游暂时不可用，正在自动重试'
  if (job.status === 'queued' || job.status === 'dispatching') return '任务已提交，正在排队'
  if (job.progress >= 80) return '图片已返回，正在生成透明通道'
  return 'AI 正在提取目标素材'
}

function friendlyError(job: ServerJob | null, fallback: string) {
  if (!job) return fallback
  const known: Record<string, string> = {
    'resource_pool.operation_not_bound': '素材提取尚未绑定图片编辑资源池，请联系管理员。',
    'material_extract.background_not_detected': '没有检测到可安全移除的纯色背景，请扩大涂抹区域并补充目标描述后重试。',
    'material_extract.empty_result': '提取结果为空，请重新涂抹目标区域。',
    'provider.timeout': '上游图片服务响应超时，系统已停止本次任务。',
  }
  return known[job.error_code || ''] || job.error_message || fallback
}

function drawStroke(context: CanvasRenderingContext2D, stroke: MaterialStroke) {
  if (!stroke.points.length) return
  context.save()
  context.globalCompositeOperation = stroke.tool === 'erase' ? 'destination-out' : 'source-over'
  context.strokeStyle = 'rgba(37, 99, 235, 0.48)'
  context.fillStyle = 'rgba(37, 99, 235, 0.48)'
  context.lineWidth = stroke.size
  context.lineCap = 'round'
  context.lineJoin = 'round'
  if (stroke.points.length === 1) {
    context.beginPath()
    context.arc(stroke.points[0].x, stroke.points[0].y, stroke.size / 2, 0, Math.PI * 2)
    context.fill()
  } else {
    context.beginPath()
    context.moveTo(stroke.points[0].x, stroke.points[0].y)
    stroke.points.slice(1).forEach((point) => context.lineTo(point.x, point.y))
    context.stroke()
  }
  context.restore()
}

function scanSelection(canvas: HTMLCanvasElement): SelectionBounds | null {
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return null
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
  let left = canvas.width
  let top = canvas.height
  let right = -1
  let bottom = -1
  for (let y = 0; y < canvas.height; y += 1) {
    for (let x = 0; x < canvas.width; x += 1) {
      if (pixels[(y * canvas.width + x) * 4 + 3] < 8) continue
      left = Math.min(left, x)
      top = Math.min(top, y)
      right = Math.max(right, x)
      bottom = Math.max(bottom, y)
    }
  }
  return right < left ? null : { x: left, y: top, width: right - left + 1, height: bottom - top + 1 }
}

function ToolIcon({ children }: { children: string }) {
  return <span aria-hidden="true" className="text-base leading-none">{children}</span>
}

export default function MaterialExtractPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const baseCanvasRef = useRef<HTMLCanvasElement>(null)
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [localUrl, setLocalUrl] = useState<string | null>(null)
  const [sourceAssetId, setSourceAssetId] = useState<string | null>(null)
  const [sourceSize, setSourceSize] = useState({ width: 0, height: 0 })
  const [workingSize, setWorkingSize] = useState({ width: 0, height: 0 })
  const [strokes, setStrokes] = useState<MaterialStroke[]>([])
  const [redoStrokes, setRedoStrokes] = useState<MaterialStroke[]>([])
  const [activeStroke, setActiveStroke] = useState<MaterialStroke | null>(null)
  const [selectionBounds, setSelectionBounds] = useState<SelectionBounds | null>(null)
  const [tool, setTool] = useState<Tool>('select')
  const [brushSize, setBrushSize] = useState(36)
  const [zoom, setZoom] = useState(100)
  const [targetDescription, setTargetDescription] = useState('')
  const [job, setJob] = useState<ServerJob | null>(null)
  const [result, setResult] = useState<JobOutput | null>(null)
  const [previewBackground, setPreviewBackground] = useState<PreviewBackground>('checker')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const resetEditor = useCallback(() => {
    setStrokes([])
    setRedoStrokes([])
    setActiveStroke(null)
    setSelectionBounds(null)
    setZoom(100)
  }, [])

  const loadFile = useCallback((nextFile: File) => {
    if (!acceptedTypes.has(nextFile.type)) {
      setMessage('仅支持 JPG、PNG 和 WEBP 图片。')
      return
    }
    if (nextFile.size > 20 * 1024 * 1024) {
      setMessage('图片不能超过 20MB。')
      return
    }
    setFile(nextFile)
    setSourceAssetId(null)
    setJob(null)
    setMessage('')
    resetEditor()
  }, [resetEditor])

  useEffect(() => {
    if (!file) {
      setLocalUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setLocalUrl(url)
    const image = new Image()
    image.onload = () => {
      const size = workingImageSize(image.naturalWidth, image.naturalHeight)
      setSourceSize({ width: image.naturalWidth, height: image.naturalHeight })
      setWorkingSize(size)
      const canvas = baseCanvasRef.current
      if (!canvas) return
      canvas.width = size.width
      canvas.height = size.height
      canvas.getContext('2d')?.drawImage(image, 0, 0, size.width, size.height)
    }
    image.onerror = () => setMessage('图片无法读取，请更换文件。')
    image.src = url
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    const canvas = overlayCanvasRef.current
    if (!canvas || !workingSize.width || !workingSize.height) return
    canvas.width = workingSize.width
    canvas.height = workingSize.height
    const context = canvas.getContext('2d')
    if (!context) return
    context.clearRect(0, 0, canvas.width, canvas.height)
    strokes.forEach((stroke) => drawStroke(context, stroke))
    if (activeStroke) drawStroke(context, activeStroke)
    if (!activeStroke) setSelectionBounds(scanSelection(canvas))
  }, [strokes, activeStroke, workingSize])

  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return
    let disposed = false
    const poll = async () => {
      try {
        const next = await getServerJob(job.id)
        if (disposed) return
        setJob(next)
        if (next.status === 'succeeded' && next.outputs[0]) {
          setResult(next.outputs[0])
          setBusy(false)
          setMessage('素材已提取为透明 PNG，并保存到素材中心。')
        } else if (next.status === 'failed' || next.status === 'cancelled') {
          setBusy(false)
          setMessage(friendlyError(next, '素材提取失败，请重试。'))
        }
      } catch (error) {
        if (!disposed) setMessage(error instanceof Error ? error.message : '读取任务状态失败')
      }
    }
    void poll()
    const timer = window.setInterval(() => void poll(), 2000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [job?.id, job?.status])

  const pointFromEvent = (event: ReactPointerEvent<HTMLCanvasElement>): MaterialPoint => {
    const rect = event.currentTarget.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(workingSize.width, (event.clientX - rect.left) * workingSize.width / rect.width)),
      y: Math.max(0, Math.min(workingSize.height, (event.clientY - rect.top) * workingSize.height / rect.height)),
    }
  }

  const startStroke = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!file || busy) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setActiveStroke({ tool, size: brushSize, points: [pointFromEvent(event)] })
  }

  const continueStroke = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!activeStroke || !event.currentTarget.hasPointerCapture(event.pointerId)) return
    const point = pointFromEvent(event)
    setActiveStroke((current) => current ? { ...current, points: [...current.points, point] } : null)
  }

  const finishStroke = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (!activeStroke) return
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    setStrokes((current) => [...current, activeStroke])
    setRedoStrokes([])
    setActiveStroke(null)
  }

  const submit = async () => {
    if (runtimeConfig.isStandalone) {
      setMessage('素材提取需要多人版后端任务系统，当前独立模式暂不可用。')
      return
    }
    if (!file || !selectionBounds || !workingSize.width || !sourceSize.width) {
      setMessage('请先上传图片，并涂抹需要提取的素材。')
      return
    }
    setBusy(true)
    setMessage('正在上传并创建素材提取任务…')
    try {
      const assetId = sourceAssetId || (await uploadAsset(file, 'temporary')).id
      setSourceAssetId(assetId)
      const response = await submitMaterialExtract({
        source_asset_id: assetId,
        target_description: targetDescription,
        selection_bounds: scaleSelectionBounds(selectionBounds, sourceSize.width, sourceSize.height, workingSize.width, workingSize.height),
        brush_strokes: scaleStrokes(strokes, sourceSize.width, sourceSize.height, workingSize.width, workingSize.height),
        idempotency_key: `material-extract:${randomUuid()}`,
      })
      setJob(response.job)
      setMessage(statusText(response.job))
    } catch (error) {
      setBusy(false)
      setMessage(error instanceof Error ? error.message : '素材提取任务提交失败')
    }
  }

  const undo = () => setStrokes((current) => {
    if (!current.length) return current
    setRedoStrokes((redo) => [current[current.length - 1], ...redo])
    return current.slice(0, -1)
  })
  const redo = () => setRedoStrokes((current) => {
    if (!current.length) return current
    setStrokes((value) => [...value, current[0]])
    return current.slice(1)
  })
  const clear = () => { setStrokes([]); setRedoStrokes([]); setSelectionBounds(null) }
  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0]
    if (next) loadFile(next)
    event.target.value = ''
  }
  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const next = event.dataTransfer.files?.[0]
    if (next) loadFile(next)
  }
  const sourcePasteZoneProps = useImagePaste({
    maxFiles: 1,
    onPasteFiles: (files) => {
      if (files[0]) loadFile(files[0])
    },
  })

  const previewClass = previewBackground === 'white' ? 'bg-white' : previewBackground === 'black' ? 'bg-black' : ''
  const checkerStyle = previewBackground === 'checker' ? {
    backgroundColor: '#f8fafc',
    backgroundImage: 'linear-gradient(45deg,#e2e8f0 25%,transparent 25%),linear-gradient(-45deg,#e2e8f0 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#e2e8f0 75%),linear-gradient(-45deg,transparent 75%,#e2e8f0 75%)',
    backgroundSize: '24px 24px',
    backgroundPosition: '0 0,0 12px,12px -12px,-12px 0px',
  } : undefined

  return (
    <div className="mt-6 space-y-4 pb-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-950 dark:text-white">素材提取</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">涂抹定位目标，AI 提取后生成带真实透明通道的高清 PNG。</p>
        </div>
        <div className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 shadow-sm dark:border-white/10 dark:bg-gray-900 dark:text-gray-300">异步任务 · 高清输出 · 自动透明化</div>
      </header>

      <div className="grid min-h-[680px] gap-4 xl:grid-cols-[310px_minmax(420px,1fr)_330px]">
        <aside className="space-y-4 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-gray-900">
          <section {...sourcePasteZoneProps} className="rounded-xl outline-none focus:ring-2 focus:ring-blue-500/20">
            <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold dark:text-white">1. 上传图片</h2>{file && <button type="button" onClick={() => fileInputRef.current?.click()} className="text-xs font-semibold text-blue-600">更换</button>}</div>
            <input ref={fileInputRef} type="file" className="hidden" accept="image/jpeg,image/png,image/webp" onChange={onFileChange} />
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={onDrop}
              className="flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-gray-300 bg-gray-50 px-4 text-center transition hover:border-blue-400 hover:bg-blue-50/40 dark:border-white/15 dark:bg-white/[0.03]"
            >
              <span className="text-2xl">＋</span>
              <span className="mt-1 text-sm font-semibold text-gray-800 dark:text-gray-100">上传或拖入参考图</span>
              <span className="mt-1 text-xs text-gray-500">JPG / PNG / WEBP，最大 20MB</span>
              <span className="mt-1 text-[11px] font-medium text-blue-600">点击本卡片后可 Ctrl/⌘+V 粘贴</span>
              {file && <span className="mt-2 max-w-full truncate text-xs font-medium text-blue-600">{file.name}</span>}
            </div>
          </section>

          <section className="border-t border-gray-100 pt-4 dark:border-white/10">
            <h2 className="text-sm font-semibold dark:text-white">2. 涂抹目标</h2>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button type="button" onClick={() => setTool('select')} className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${tool === 'select' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 dark:border-white/10 dark:text-gray-300'}`}><ToolIcon>✎</ToolIcon>选择画笔</button>
              <button type="button" onClick={() => setTool('erase')} className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold ${tool === 'erase' ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-600 dark:border-white/10 dark:text-gray-300'}`}><ToolIcon>◇</ToolIcon>橡皮擦</button>
            </div>
            <label className="mt-4 block text-xs font-medium text-gray-500">画笔大小：{brushSize}px</label>
            <input type="range" min="5" max="100" value={brushSize} onChange={(event) => setBrushSize(Number(event.target.value))} className="mt-2 w-full accent-blue-600" />
            <div className="mt-3 grid grid-cols-3 gap-2">
              <button type="button" disabled={!strokes.length || busy} onClick={undo} className="rounded-lg border border-gray-200 px-2 py-2 text-xs font-semibold disabled:opacity-35 dark:border-white/10">↶ 撤销</button>
              <button type="button" disabled={!redoStrokes.length || busy} onClick={redo} className="rounded-lg border border-gray-200 px-2 py-2 text-xs font-semibold disabled:opacity-35 dark:border-white/10">↷ 重做</button>
              <button type="button" disabled={!strokes.length || busy} onClick={clear} className="rounded-lg border border-gray-200 px-2 py-2 text-xs font-semibold disabled:opacity-35 dark:border-white/10">清空</button>
            </div>
            <p className="mt-3 text-xs leading-5 text-gray-500">只需大致涂过目标主体，不必精确描边。蓝色区域用于定位，最终边缘由 AI 与透明算法处理。</p>
          </section>

          <section className="border-t border-gray-100 pt-4 dark:border-white/10">
            <label htmlFor="material-description" className="text-sm font-semibold dark:text-white">3. 目标说明 <span className="font-normal text-gray-400">（可选）</span></label>
            <textarea id="material-description" value={targetDescription} onChange={(event) => setTargetDescription(event.target.value)} rows={4} maxLength={1000} placeholder="例如：只提取红色球衣，保留号码、文字和袖口细节" className="mt-2 w-full resize-none rounded-xl border border-gray-200 px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-white/10 dark:bg-gray-950" />
          </section>

          <button type="button" disabled={busy || !file || !selectionBounds} onClick={() => void submit()} className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40">{busy ? '正在提取…' : result ? '重新提取素材' : '开始提取素材'}</button>
          {job && activeStatuses.has(job.status) && <button type="button" onClick={() => void cancelServerJob(job.id).then((next) => setJob(next))} className="w-full rounded-xl border border-red-200 px-4 py-2 text-sm font-semibold text-red-600">取消任务</button>}
        </aside>

        <main className="flex min-h-[620px] flex-col overflow-hidden rounded-2xl border border-gray-200 bg-[#eef1f5] shadow-sm dark:border-white/10 dark:bg-gray-950">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3 dark:border-white/10 dark:bg-gray-900">
            <div><h2 className="text-sm font-semibold dark:text-white">画布编辑</h2><p className="mt-0.5 text-xs text-gray-500">在图片上涂抹需要保留的素材</p></div>
            <div className="flex items-center gap-2 text-xs text-gray-500"><button type="button" onClick={() => setZoom((value) => Math.max(50, value - 25))} className="rounded-md border border-gray-200 px-2 py-1 dark:border-white/10">−</button><span className="w-10 text-center">{zoom}%</span><button type="button" onClick={() => setZoom((value) => Math.min(200, value + 25))} className="rounded-md border border-gray-200 px-2 py-1 dark:border-white/10">＋</button><button type="button" onClick={() => setZoom(100)} className="rounded-md border border-gray-200 px-2 py-1 dark:border-white/10">适应</button></div>
          </div>
          <div className="flex flex-1 items-center justify-center overflow-auto p-5">
            {!file && <div className="max-w-xs text-center"><div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-2xl shadow-sm dark:bg-gray-900">✣</div><div className="mt-4 text-sm font-semibold text-gray-700 dark:text-gray-200">上传图片后开始涂抹</div><p className="mt-2 text-xs leading-5 text-gray-500">支持鼠标、触控笔和触摸操作。画布仅用于定位，不会直接修改原图。</p></div>}
            {file && localUrl && <div className="relative shrink-0 overflow-hidden rounded-lg bg-white shadow-xl" style={{ width: `${zoom}%`, maxWidth: zoom === 100 ? '100%' : 'none', aspectRatio: `${workingSize.width}/${workingSize.height}` }}>
              <canvas ref={baseCanvasRef} className="absolute inset-0 h-full w-full" aria-label="原始图片画布" />
              <canvas ref={overlayCanvasRef} className="absolute inset-0 h-full w-full cursor-crosshair touch-none" aria-label="素材选择画布" onPointerDown={startStroke} onPointerMove={continueStroke} onPointerUp={finishStroke} onPointerCancel={finishStroke} />
            </div>}
          </div>
          <div className="border-t border-gray-200 bg-white px-4 py-2 text-xs text-gray-500 dark:border-white/10 dark:bg-gray-900">{sourceSize.width ? `原图 ${sourceSize.width} × ${sourceSize.height}` : '等待上传'}{selectionBounds ? ` · 已选择约 ${Math.round(selectionBounds.width)} × ${Math.round(selectionBounds.height)} px` : ' · 尚未涂抹目标'}</div>
        </main>

        <aside className="flex flex-col rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/10 dark:bg-gray-900">
          <div className="flex items-start justify-between gap-3"><div><h2 className="text-sm font-semibold dark:text-white">提取结果</h2><p className="mt-1 text-xs text-gray-500">透明 PNG 预览</p></div>{result && <span className="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700">已完成</span>}</div>
          <div className="mt-4 grid grid-cols-3 gap-2 rounded-lg bg-gray-100 p-1 dark:bg-white/[0.05]">
            {(['checker', 'white', 'black'] as PreviewBackground[]).map((value) => <button key={value} type="button" onClick={() => setPreviewBackground(value)} className={`rounded-md px-2 py-1.5 text-xs font-semibold ${previewBackground === value ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-800 dark:text-white' : 'text-gray-500'}`}>{value === 'checker' ? '透明格' : value === 'white' ? '白底' : '黑底'}</button>)}
          </div>
          <div className={`mt-4 flex aspect-square items-center justify-center overflow-hidden rounded-xl border border-gray-200 ${previewClass}`} style={checkerStyle}>
            {result ? <AuthenticatedImage src={result.url} alt="提取后的透明素材" className="saveable-image h-full w-full object-contain" /> : <div className="px-6 text-center text-xs leading-5 text-gray-500">生成完成后，这里会显示透明背景素材。开始新任务时会保留上一次结果。</div>}
          </div>
          {job && <div className={`mt-4 rounded-xl px-3 py-3 text-sm ${job.status === 'failed' ? 'bg-red-50 text-red-700' : job.status === 'succeeded' ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'}`}><div className="font-semibold">{statusText(job)}</div><div className="mt-1 text-xs opacity-80">任务 #{job.id.slice(0, 8)} · 进度 {job.progress}%</div></div>}
          {message && <div role="status" className="mt-3 text-xs leading-5 text-gray-600 dark:text-gray-300">{message}</div>}
          <div className="mt-auto pt-4">
            {result && <div className="mb-3 grid grid-cols-2 gap-2 text-xs text-gray-500"><div className="rounded-lg bg-gray-50 p-2 dark:bg-white/[0.04]">尺寸<br /><strong className="text-gray-800 dark:text-gray-200">{result.width} × {result.height}</strong></div><div className="rounded-lg bg-gray-50 p-2 dark:bg-white/[0.04]">格式<br /><strong className="text-gray-800 dark:text-gray-200">PNG / RGBA</strong></div></div>}
            <button type="button" disabled={!result} onClick={() => result && void downloadServerOutput(result)} className="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold text-gray-800 shadow-sm hover:bg-gray-50 disabled:opacity-40 dark:border-white/10 dark:bg-gray-950 dark:text-white">下载透明 PNG</button>
          </div>
        </aside>
      </div>
    </div>
  )
}
