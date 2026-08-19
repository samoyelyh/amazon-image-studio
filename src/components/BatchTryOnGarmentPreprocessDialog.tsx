import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { ensureImageCached } from '../store'
import type {
  BatchTryOnGarment,
  BatchTryOnGarmentTransform,
  BatchTryOnGarmentView,
} from '../types'
import {
  FULL_GARMENT_RECT,
  compactGarmentTransform,
  normalizedRectFromPoints,
  renderGarmentReference,
} from '../lib/batchTryOnGarmentPreprocess'
import { BatchTryOnImage } from './BatchTryOnImage'

export interface GarmentReferencePreview {
  garmentId: string
  garmentView: BatchTryOnGarmentView
  transform: BatchTryOnGarmentTransform
  dataUrl: string
}

interface Props {
  open: boolean
  garments: BatchTryOnGarment[]
  initialGarmentId?: string
  saving?: boolean
  onClose: () => void
  onSave: (items: GarmentReferencePreview[]) => Promise<void>
  sourceUrls?: Record<string, string>
  title?: string
  description?: string
}

type Tool = 'crop' | 'keep' | 'erase'
type DraftMap = Record<string, Partial<Record<BatchTryOnGarmentView, BatchTryOnGarmentTransform>>>
type CropHandle = 'nw' | 'ne' | 'sw' | 'se'
type CropDrag = {
  kind: 'create' | 'move' | 'resize'
  start: { x: number; y: number }
  initial: BatchTryOnGarmentTransform['crop']
  handle?: CropHandle
}

const defaultTransform = (): BatchTryOnGarmentTransform => ({
  mode: 'crop', crop: { ...FULL_GARMENT_RECT }, eraseStrokes: [],
})

function cloneTransform(value: BatchTryOnGarmentTransform): BatchTryOnGarmentTransform {
  return JSON.parse(JSON.stringify(value)) as BatchTryOnGarmentTransform
}

function clampCropRect(rect: BatchTryOnGarmentTransform['crop']): BatchTryOnGarmentTransform['crop'] {
  const minSize = 0.02
  const width = Math.max(minSize, Math.min(1, rect.width))
  const height = Math.max(minSize, Math.min(1, rect.height))
  return {
    x: Math.max(0, Math.min(1 - width, rect.x)),
    y: Math.max(0, Math.min(1 - height, rect.y)),
    width,
    height,
  }
}

export default function BatchTryOnGarmentPreprocessDialog({
  open, garments, initialGarmentId, saving, onClose, onSave, sourceUrls, title, description,
}: Props) {
  const [currentId, setCurrentId] = useState('')
  const [view, setView] = useState<BatchTryOnGarmentView>('front')
  const [tool, setTool] = useState<Tool>('crop')
  const [drafts, setDrafts] = useState<DraftMap>({})
  const [history, setHistory] = useState<BatchTryOnGarmentTransform[]>([])
  const [sourceUrl, setSourceUrl] = useState('')
  const [previews, setPreviews] = useState<GarmentReferencePreview[]>([])
  const [previewing, setPreviewing] = useState(false)
  const canvasRef = useRef<HTMLDivElement>(null)
  const draftsRef = useRef<DraftMap>({})
  const dialogInitializedRef = useRef(false)
  const drawingRef = useRef(false)
  const cropDragRef = useRef<CropDrag | null>(null)

  const currentGarment = garments.find((item) => item.id === currentId) || garments[0]
  const currentTransform = drafts[currentGarment?.id]?.[view] || defaultTransform()

  useEffect(() => {
    if (!open) {
      dialogInitializedRef.current = false
      drawingRef.current = false
      cropDragRef.current = null
      return
    }
    // Parent polling and autosave frequently replace `garments` with a new array.
    // Re-initializing on every new reference discards the user's unsaved crop/mask work.
    if (dialogInitializedRef.current) return
    dialogInitializedRef.current = true
    const initialDrafts = Object.fromEntries(garments.map((garment) => [garment.id, Object.fromEntries(
      Object.entries(garment.references || {}).map(([key, reference]) => [key, cloneTransform(reference!.transform)]),
    )])) as DraftMap
    setCurrentId(initialGarmentId && garments.some((item) => item.id === initialGarmentId) ? initialGarmentId : garments[0]?.id || '')
    draftsRef.current = initialDrafts
    setDrafts(initialDrafts)
    setPreviews([])
    setHistory([])
  }, [open, garments, initialGarmentId])

  useEffect(() => {
    let cancelled = false
    setSourceUrl('')
    if (!currentGarment) return
    const direct = sourceUrls?.[currentGarment.garmentImageId]
    const request = direct ? Promise.resolve(direct) : ensureImageCached(currentGarment.garmentImageId)
    void request.then((url) => {
      if (!cancelled) setSourceUrl(url || '')
    })
    return () => { cancelled = true }
  }, [currentGarment?.id, currentGarment?.garmentImageId, sourceUrls])

  const liveCurrentTransform = () => {
    if (!currentGarment) return defaultTransform()
    return draftsRef.current[currentGarment.id]?.[view] || defaultTransform()
  }

  const updateCurrent = (next: BatchTryOnGarmentTransform, remember = true) => {
    if (!currentGarment) return
    const previous = liveCurrentTransform()
    if (remember) setHistory((items) => [...items.slice(-29), cloneTransform(previous)])
    const nextDrafts = {
      ...draftsRef.current,
      [currentGarment.id]: { ...draftsRef.current[currentGarment.id], [view]: next },
    }
    // Pointer events can arrive faster than React renders. Keep the authoritative
    // drawing draft synchronous so each move appends to the immediately prior move.
    draftsRef.current = nextDrafts
    setDrafts(nextDrafts)
    setPreviews([])
  }

  const point = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    }
  }

  const pointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!sourceUrl) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const nextPoint = point(event)
    if (tool === 'erase') {
      const transform = liveCurrentTransform()
      setHistory((items) => [...items.slice(-29), cloneTransform(transform)])
      updateCurrent({
        ...transform,
        eraseStrokes: [...transform.eraseStrokes, { points: [nextPoint], radius: 0.025 }],
      }, false)
      drawingRef.current = true
      return
    }
    const transform = liveCurrentTransform()
    const nextDrag: CropDrag = { kind: 'create', start: nextPoint, initial: transform.crop }
    setHistory((items) => [...items.slice(-29), cloneTransform(transform)])
    cropDragRef.current = nextDrag
    updateCurrent({
      ...transform,
      mode: tool === 'keep' ? 'keep' : 'crop',
      crop: { x: nextPoint.x, y: nextPoint.y, width: 0.02, height: 0.02 },
    }, false)
  }

  const pointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const nextPoint = point(event)
    if (drawingRef.current && tool === 'erase') {
      const transform = liveCurrentTransform()
      const strokes = [...transform.eraseStrokes]
      const last = strokes[strokes.length - 1]
      if (!last) return
      const previousPoint = last.points[last.points.length - 1]
      if (previousPoint && Math.hypot(nextPoint.x - previousPoint.x, nextPoint.y - previousPoint.y) < 0.0025) return
      strokes[strokes.length - 1] = { ...last, points: [...last.points, nextPoint] }
      updateCurrent({ ...transform, eraseStrokes: strokes }, false)
      return
    }
    const activeCropDrag = cropDragRef.current
    if (!activeCropDrag) return
    const transform = liveCurrentTransform()
    const dx = nextPoint.x - activeCropDrag.start.x
    const dy = nextPoint.y - activeCropDrag.start.y
    let crop = activeCropDrag.initial
    if (activeCropDrag.kind === 'create') {
      crop = normalizedRectFromPoints(activeCropDrag.start, nextPoint)
    } else if (activeCropDrag.kind === 'move') {
      crop = clampCropRect({ ...activeCropDrag.initial, x: activeCropDrag.initial.x + dx, y: activeCropDrag.initial.y + dy })
    } else {
      const left = activeCropDrag.handle?.includes('w') ? activeCropDrag.initial.x + dx : activeCropDrag.initial.x
      const right = activeCropDrag.handle?.includes('e') ? activeCropDrag.initial.x + activeCropDrag.initial.width + dx : activeCropDrag.initial.x + activeCropDrag.initial.width
      const top = activeCropDrag.handle?.includes('n') ? activeCropDrag.initial.y + dy : activeCropDrag.initial.y
      const bottom = activeCropDrag.handle?.includes('s') ? activeCropDrag.initial.y + activeCropDrag.initial.height + dy : activeCropDrag.initial.y + activeCropDrag.initial.height
      crop = normalizedRectFromPoints(
        { x: Math.max(0, Math.min(1, left)), y: Math.max(0, Math.min(1, top)) },
        { x: Math.max(0, Math.min(1, right)), y: Math.max(0, Math.min(1, bottom)) },
      )
    }
    updateCurrent({ ...transform, mode: tool === 'keep' ? 'keep' : 'crop', crop: clampCropRect(crop) }, false)
  }

  const pointerUp = () => {
    drawingRef.current = false
    cropDragRef.current = null
  }

  const startCropDrag = (event: ReactPointerEvent<HTMLDivElement>, kind: 'move' | 'resize', handle?: CropHandle) => {
    if (tool === 'erase') return
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    const transform = liveCurrentTransform()
    const nextDrag: CropDrag = { kind, handle, start: point(event), initial: { ...transform.crop } }
    setHistory((items) => [...items.slice(-29), cloneTransform(transform)])
    cropDragRef.current = nextDrag
  }

  const buildPreviews = async () => {
    setPreviewing(true)
    try {
      const transformToApply = cloneTransform(liveCurrentTransform())
      const appliedDrafts: DraftMap = { ...draftsRef.current }
      for (const garment of garments) {
        appliedDrafts[garment.id] = {
          ...appliedDrafts[garment.id],
          [view]: cloneTransform(transformToApply),
        }
      }
      draftsRef.current = appliedDrafts
      setDrafts(appliedDrafts)
      const jobs: Array<Promise<GarmentReferencePreview>> = []
      for (const garment of garments) {
        const dataUrl = sourceUrls?.[garment.garmentImageId] || await ensureImageCached(garment.garmentImageId)
        if (!dataUrl) continue
        for (const [garmentView, transform] of Object.entries(appliedDrafts[garment.id] || {})) {
          if (!transform || !['front', 'back', 'detail'].includes(garmentView)) continue
          const compactTransform = compactGarmentTransform(transform)
          jobs.push(renderGarmentReference(dataUrl, compactTransform).then((result) => ({
            garmentId: garment.id,
            garmentView: garmentView as BatchTryOnGarmentView,
            transform: compactTransform,
            dataUrl: result,
          })))
        }
      }
      setPreviews(await Promise.all(jobs))
    } finally {
      setPreviewing(false)
    }
  }

  const cropStyle = useMemo(() => ({
    left: `${currentTransform.crop.x * 100}%`, top: `${currentTransform.crop.y * 100}%`,
    width: `${currentTransform.crop.width * 100}%`, height: `${currentTransform.crop.height * 100}%`,
  }), [currentTransform.crop])

  if (!open) return null
  return <div className="fixed inset-0 z-[120] flex items-center justify-center bg-gray-950/55 p-3 backdrop-blur-sm">
    <div className="flex max-h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-gray-950">
      <header className="flex items-center justify-between border-b border-gray-200 px-5 py-4 dark:border-white/[0.08]">
        <div><h2 className="text-base font-bold">{title || '服装参考图预处理'}</h2><p className="mt-1 text-xs text-gray-500">{description || '原图永久保留；这里生成的是 Luna 与生图共同使用的干净参考图，不是 Provider 编辑 Mask。'}</p></div>
        <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-white/[0.06]">关闭</button>
      </header>
      <div className="grid min-h-0 flex-1 lg:grid-cols-[250px_minmax(0,1fr)_260px]">
        <aside className="overflow-y-auto border-r border-gray-200 p-3 dark:border-white/[0.08]">
          <div className="mb-2"><b className="text-xs">已勾选服装（{garments.length}）</b><p className="mt-1 text-[11px] text-gray-400">范围来自上传区的服装勾选状态</p></div>
          <div className="space-y-2">{garments.map((garment) => <div key={garment.id} className={`flex items-center gap-2 rounded-xl border p-2 ${currentGarment?.id === garment.id ? 'border-blue-400 bg-blue-50/60 dark:bg-blue-500/10' : 'border-gray-200 dark:border-white/[0.08]'}`}>
            <button type="button" onClick={() => { setCurrentId(garment.id); setHistory([]) }} className="flex min-w-0 flex-1 items-center gap-2 text-left">{sourceUrls?.[garment.garmentImageId] ? <img src={sourceUrls[garment.garmentImageId]} alt="" className="h-10 w-10 rounded-lg object-cover" /> : <BatchTryOnImage imageId={garment.garmentImageId} alt="" className="h-10 w-10 rounded-lg object-cover" />}<span className="min-w-0 flex-1 truncate text-xs" title={garment.garmentFileName}>{garment.garmentFileName}</span></button>
          </div>)}</div>
        </aside>
        <main className="flex min-h-[520px] flex-col bg-gray-100 p-4 dark:bg-gray-900">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {(['front', 'back', 'detail'] as const).map((item) => <button key={item} type="button" onClick={() => { setView(item); setHistory([]) }} className={`rounded-lg px-3 py-2 text-xs font-semibold ${view === item ? 'bg-blue-600 text-white' : 'bg-white dark:bg-gray-800'}`}>{item === 'front' ? '正面参考' : item === 'back' ? '背面参考' : '细节参考'}</button>)}
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden">
            <div ref={canvasRef} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp} className="relative max-h-full max-w-full touch-none select-none overflow-hidden bg-[linear-gradient(45deg,#eee_25%,transparent_25%),linear-gradient(-45deg,#eee_25%,transparent_25%),linear-gradient(45deg,transparent_75%,#eee_75%),linear-gradient(-45deg,transparent_75%,#eee_75%)] bg-[length:20px_20px] bg-[position:0_0,0_10px,10px_-10px,-10px_0]">
              {sourceUrl && <img src={sourceUrl} alt="当前服装原图" draggable={false} className="max-h-[66vh] max-w-full object-contain" />}
              {sourceUrl && <div onPointerDown={(event) => startCropDrag(event, 'move')} className={`absolute border-2 border-blue-500 bg-blue-500/10 ${tool === 'erase' ? 'pointer-events-none' : 'cursor-move'}`} style={cropStyle}>
                {(['nw', 'ne', 'sw', 'se'] as const).map((handle) => <div key={handle} onPointerDown={(event) => startCropDrag(event, 'resize', handle)} className={`absolute h-4 w-4 rounded-full border-2 border-white bg-blue-600 shadow ${handle.includes('n') ? '-top-2' : '-bottom-2'} ${handle.includes('w') ? '-left-2' : '-right-2'} ${handle === 'nw' || handle === 'se' ? 'cursor-nwse-resize' : 'cursor-nesw-resize'}`} />)}
              </div>}
              {sourceUrl && <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1000 1000" preserveAspectRatio="none">{currentTransform.eraseStrokes.map((stroke, index) => <polyline key={index} points={stroke.points.map((p) => `${p.x * 1000},${p.y * 1000}`).join(' ')} fill="none" stroke="rgba(239,68,68,.72)" strokeWidth={stroke.radius * 2000} strokeLinecap="round" strokeLinejoin="round" />)}</svg>}
            </div>
          </div>
          <p className="mt-3 text-center text-xs text-gray-500">拖动画布可重新框选；拖动框体可移动，拖动四角可调整大小。擦除轨迹不会传为图片编辑 Mask。</p>
        </main>
        <aside className="overflow-y-auto border-l border-gray-200 p-4 dark:border-white/[0.08]">
          <b className="text-sm">处理工具</b>
          <div className="mt-3 grid gap-2">{([['crop','裁剪'],['keep','保留区域'],['erase','擦除区域']] as const).map(([key,label]) => <button key={key} type="button" onClick={() => setTool(key)} className={`rounded-lg border px-3 py-2 text-left text-xs font-semibold ${tool === key ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200' : 'border-gray-200 dark:border-white/[0.08]'}`}>{label}</button>)}</div>
          <div className="mt-3 grid grid-cols-2 gap-2"><button type="button" disabled={!history.length} onClick={() => { const previous = history[history.length - 1]; if (previous) { updateCurrent(previous, false); setHistory((items) => items.slice(0,-1)) } }} className="rounded-lg border px-3 py-2 text-xs disabled:opacity-40">撤销</button><button type="button" onClick={() => updateCurrent(defaultTransform())} className="rounded-lg border px-3 py-2 text-xs">重置</button></div>
          <div className="mt-4 rounded-xl bg-gray-50 p-3 text-xs text-gray-600 dark:bg-white/[0.04] dark:text-gray-300"><b>当前区域</b><div className="mt-2 font-mono text-[11px]">x {currentTransform.crop.x.toFixed(4)}<br/>y {currentTransform.crop.y.toFixed(4)}<br/>w {currentTransform.crop.width.toFixed(4)}<br/>h {currentTransform.crop.height.toFixed(4)}</div></div>
          <button type="button" disabled={previewing || !garments.length} onClick={() => void buildPreviews()} className="mt-4 w-full rounded-lg bg-blue-600 px-3 py-2.5 text-xs font-semibold text-white disabled:opacity-40">{previewing ? '正在生成预览…' : '批量预览并应用'}</button>
        </aside>
      </div>
      {previews.length > 0 && <section className="max-h-72 space-y-4 overflow-y-auto border-t border-gray-200 p-4 dark:border-white/[0.08]">
        <div className="flex items-center justify-between"><b className="text-sm">保存前批量预览（{previews.length} 张）</b><span className="text-xs text-gray-500">正面、背面和细节参考分区显示</span></div>
        {(['front', 'back', 'detail'] as const).map((previewView) => {
          const viewPreviews = previews.filter((preview) => preview.garmentView === previewView)
          if (!viewPreviews.length) return null
          return <div key={previewView}><div className="mb-2 text-xs font-bold text-gray-700 dark:text-gray-200">{previewView === 'front' ? '正面参考' : previewView === 'back' ? '背面参考' : '细节参考'} · {viewPreviews.length} 张</div><div className="grid grid-cols-4 gap-3 sm:grid-cols-6 lg:grid-cols-10">{viewPreviews.map((preview) => { const garment = garments.find((item) => item.id === preview.garmentId); return <button type="button" key={`${preview.garmentId}:${preview.garmentView}`} onClick={() => { setCurrentId(preview.garmentId); setView(preview.garmentView); setPreviews([]) }} className="overflow-hidden rounded-lg border text-left"><img src={preview.dataUrl} alt="处理预览" className="aspect-square w-full object-contain"/><span className="block truncate px-1 py-1 text-[10px]">{garment?.garmentFileName}</span></button>})}</div></div>
        })}
      </section>}
      <footer className="flex items-center justify-end gap-2 border-t border-gray-200 px-5 py-4 dark:border-white/[0.08]"><button type="button" onClick={onClose} className="rounded-lg border px-4 py-2 text-sm">取消</button><button type="button" disabled={!previews.length || saving} onClick={() => void onSave(previews)} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{saving ? '正在保存…' : '确认并保存参考图'}</button></footer>
    </div>
  </div>
}
