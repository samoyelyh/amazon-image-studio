import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  createProject, fetchAssetBlob, getAsset, getProject, linkProjectAsset, saveProjectVersion,
  uploadAsset, uploadPrintDesignReference, type Asset,
} from '../lib/contentApi'
import { getServerJob, isServerJobTerminal, resolveModelCode, submitServerJob, type ServerJob } from '../lib/jobsApi'
import {
  canvasBlob, loadCanvasImage, pointInLayer, renderAssetAlphaMask, renderDebugMask,
  renderDocument, renderMaskPreview, renderProviderMask, type PrintDesignDocument,
  type PrintDesignLayer, type PrintDesignMaskType, type PrintDesignStroke,
} from '../lib/printDesignCanvas'
import {
  archivePrintAsset, createPrintAssetGroup, createProductPrintMapping, findProductPrintMappings,
  listPrintAssetGroups, listPrintAssets, registerPrintAsset, updatePrintAsset,
  type PrintAssetGroup, type PrintAssetItem,
} from '../lib/printDesignApi'
import { randomUuid } from '../lib/randomUuid'

const REPLACE_PROMPT = 'Edit only the transparent masked region in the base image. Replace the selected content according to the user instruction. Preserve every unmasked pixel, the product structure, composition, lighting and background exactly as-is. Integrate the replacement naturally with the local perspective, texture, folds, lighting and shadows.'
const BLEND_PROMPT = 'The overlaid artwork is the correct real product asset. Keep its core pixels, shape, internal lines, colors, proportions and layout unchanged. Edit only the transparent blend ring in the mask. Blend only the boundary into the garment surface by matching fabric texture, folds, perspective, lighting and shadows. Do not redesign the artwork or modify any protected or unmasked area.'
const EMPTY: PrintDesignDocument = {
  schemaVersion: 2, width: 0, height: 0, zoom: 100, layers: [],
  mask: { activeType: 'blend', brushSize: 40, expand: 20, contract: 0, feather: 8, overlayOpacity: .42, protectCore: true, inverted: {}, strokes: [] },
  replacementPrompt: REPLACE_PROMPT, blendPrompt: BLEND_PROMPT,
}

type Tool = 'select' | 'mask-paint' | 'mask-erase'
type Handle = 'nw' | 'ne' | 'se' | 'sw'
type DragState = {
  kind: 'move' | 'resize' | 'rotate' | 'stroke'
  layerId?: string
  startX: number
  startY: number
  original?: PrintDesignLayer
  handle?: Handle
  startAngle?: number
  stroke?: PrintDesignStroke
}
type DebugImage = { key: string; label: string; assetId?: string; url: string }

const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试。'
const stem = (name: string) => name.replace(/\.[^.]+$/, '').trim() || 'print'
const pngFile = (blob: Blob, name: string) => new File([blob], name, { type: 'image/png' })
const cloneDocument = (value: PrintDesignDocument): PrintDesignDocument => structuredClone(value)

async function objectUrl(asset: Asset) {
  if (!asset.url) throw new Error(`${asset.filename} 暂无可访问地址。`)
  return URL.createObjectURL(await fetchAssetBlob(asset.url))
}

async function normalizeUpload(file: File) {
  if (file.type !== 'image/svg+xml') return file
  const url = URL.createObjectURL(file)
  try {
    const image = await loadCanvasImage(url)
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth || 2048
    canvas.height = image.naturalHeight || 2048
    canvas.getContext('2d')!.drawImage(image, 0, 0, canvas.width, canvas.height)
    return pngFile(await canvasBlob(canvas), `${stem(file.name)}.png`)
  } finally {
    URL.revokeObjectURL(url)
  }
}

function Num({ label, value, onChange, min }: { label: string; value: number; onChange: (value: number) => void; min?: number }) {
  return <label className="space-y-1 text-xs text-gray-500"><span>{label}</span><input type="number" min={min} value={Math.round(value * 100) / 100} onChange={(event) => onChange(Number(event.target.value))} className="w-full rounded-lg border border-gray-200 px-2 py-1.5 text-sm text-gray-800" /></label>
}

function transformedPoint(layer: PrintDesignLayer, localX: number, localY: number) {
  const angle = layer.rotation * Math.PI / 180
  const cx = layer.x + layer.width / 2
  const cy = layer.y + layer.height / 2
  const dx = (localX - layer.width / 2) * layer.scaleX
  const dy = (localY - layer.height / 2) * layer.scaleY
  return { x: cx + dx * Math.cos(angle) - dy * Math.sin(angle), y: cy + dx * Math.sin(angle) + dy * Math.cos(angle) }
}

function layerHandles(layer: PrintDesignLayer) {
  return {
    nw: transformedPoint(layer, 0, 0), ne: transformedPoint(layer, layer.width, 0),
    se: transformedPoint(layer, layer.width, layer.height), sw: transformedPoint(layer, 0, layer.height),
    rotate: transformedPoint(layer, layer.width / 2, -Math.max(36, layer.height * .08)),
    top: transformedPoint(layer, layer.width / 2, 0),
  }
}

function hitHandle(layer: PrintDesignLayer, x: number, y: number, radius: number): Handle | 'rotate' | null {
  const handles = layerHandles(layer)
  for (const key of ['nw', 'ne', 'se', 'sw', 'rotate'] as const) {
    if (Math.hypot(handles[key].x - x, handles[key].y - y) <= radius) return key
  }
  return null
}

export default function PrintDesignPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const baseInputRef = useRef<HTMLInputElement>(null)
  const printInputRef = useRef<HTMLInputElement>(null)
  const versionInputRef = useRef<HTMLInputElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const [params, setParams] = useSearchParams()
  const [doc, setDoc] = useState<PrintDesignDocument>(EMPTY)
  const docRef = useRef(doc)
  const [undo, setUndo] = useState<PrintDesignDocument[]>([])
  const [redo, setRedo] = useState<PrintDesignDocument[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tool, setTool] = useState<Tool>('select')
  const [groups, setGroups] = useState<PrintAssetGroup[]>([])
  const [library, setLibrary] = useState<PrintAssetItem[]>([])
  const [search, setSearch] = useState('')
  const [groupId, setGroupId] = useState('')
  const [sku, setSku] = useState('')
  const [versionSource, setVersionSource] = useState<PrintAssetItem | null>(null)
  const [projectId, setProjectId] = useState(params.get('project_id') || '')
  const [version, setVersion] = useState(0)
  const [projectName, setProjectName] = useState('未命名印花设计')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [job, setJob] = useState<ServerJob | null>(null)
  const [resultUrl, setResultUrl] = useState('')
  const [resultAssetId, setResultAssetId] = useState('')
  const [debugImages, setDebugImages] = useState<DebugImage[]>([])
  const [showDebug, setShowDebug] = useState(false)
  const selected = doc.layers.find((layer) => layer.id === selectedId) ?? null
  const base = doc.layers.find((layer) => layer.kind === 'base') ?? null

  useEffect(() => { docRef.current = doc }, [doc])

  const commit = useCallback((next: PrintDesignDocument) => {
    setUndo((items) => [...items.slice(-39), cloneDocument(docRef.current)])
    setRedo([])
    docRef.current = next
    setDoc(next)
  }, [])

  const patchSelected = useCallback((patch: Partial<PrintDesignLayer>) => {
    if (!selectedId) return
    commit({ ...docRef.current, layers: docRef.current.layers.map((layer) => layer.id === selectedId ? { ...layer, ...patch } : layer) })
  }, [commit, selectedId])

  const refreshLibrary = useCallback(async () => {
    try {
      const [groupRows, page] = await Promise.all([listPrintAssetGroups(), listPrintAssets(search, groupId)])
      setGroups(groupRows)
      setLibrary(page.items)
    } catch (error) {
      setMessage(errorText(error))
    }
  }, [groupId, search])

  useEffect(() => {
    const timer = window.setTimeout(() => void refreshLibrary(), 180)
    return () => window.clearTimeout(timer)
  }, [refreshLibrary])

  useEffect(() => {
    const id = params.get('project_id')
    if (!id) return
    let active = true
    void (async () => {
      try {
        setBusy(true)
        const project = await getProject(id)
        const draft = project.latest_version.draft_json as unknown as PrintDesignDocument
        const urls = new Map<string, string>()
        for (const layer of draft.layers || []) urls.set(layer.assetId, await objectUrl(await getAsset(layer.assetId)))
        const debugRows: DebugImage[] = []
        for (const [key, assetId] of Object.entries(draft.debugAssetIds || {})) {
          const asset = await getAsset(assetId)
          debugRows.push({ key, label: key.replace(/_/g, ' '), assetId, url: await objectUrl(asset) })
        }
        if (!active) return
        setDoc({ ...EMPTY, ...draft, mask: { ...EMPTY.mask, ...(draft.mask || {}) }, layers: (draft.layers || []).map((layer) => ({ ...layer, url: urls.get(layer.assetId) || '' })) })
        setDebugImages(debugRows)
        setProjectId(id)
        setVersion(project.latest_version.version_number)
        setProjectName(project.name)
        if (draft.latestJobId) {
          const previousJob = await getServerJob(draft.latestJobId)
          setJob(previousJob)
          if (previousJob.status === 'succeeded' && previousJob.outputs[0]) {
            setResultUrl(previousJob.outputs[0].url); setResultAssetId(previousJob.outputs[0].asset_id)
            setDebugImages((items) => [...items.filter((item) => item.key !== '08_ai_output'), { key: '08_ai_output', label: '08 AI Output', assetId: previousJob.outputs[0].asset_id, url: previousJob.outputs[0].url }])
          }
        }
      } catch (error) {
        if (active) setMessage(errorText(error))
      } finally {
        if (active) setBusy(false)
      }
    })()
    return () => { active = false }
  }, [params])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !doc.width) return
    let active = true
    void (async () => {
      const rendered = await renderDocument(doc)
      if (!active) return
      canvas.width = doc.width
      canvas.height = doc.height
      const context = canvas.getContext('2d')!
      context.drawImage(rendered, 0, 0)
      if (tool !== 'select') {
        const overlay = await renderMaskPreview(doc, doc.mask.activeType)
        context.save()
        context.globalAlpha = doc.mask.overlayOpacity
        context.drawImage(overlay, 0, 0)
        context.restore()
      }
      if (selected && tool === 'select') {
        const handles = layerHandles(selected)
        const radius = Math.max(6, doc.width / 260)
        context.save()
        context.strokeStyle = '#2563eb'
        context.lineWidth = Math.max(2, doc.width / 800)
        context.translate(selected.x + selected.width / 2, selected.y + selected.height / 2)
        context.rotate(selected.rotation * Math.PI / 180)
        context.scale(selected.scaleX, selected.scaleY)
        context.strokeRect(-selected.width / 2, -selected.height / 2, selected.width, selected.height)
        context.restore()
        context.beginPath()
        context.moveTo(handles.top.x, handles.top.y)
        context.lineTo(handles.rotate.x, handles.rotate.y)
        context.stroke()
        for (const point of [handles.nw, handles.ne, handles.se, handles.sw]) {
          context.fillStyle = '#fff'; context.strokeStyle = '#2563eb'; context.lineWidth = 2
          context.fillRect(point.x - radius, point.y - radius, radius * 2, radius * 2)
          context.strokeRect(point.x - radius, point.y - radius, radius * 2, radius * 2)
        }
        context.beginPath(); context.arc(handles.rotate.x, handles.rotate.y, radius * 1.15, 0, Math.PI * 2)
        context.fillStyle = '#fff'; context.fill(); context.stroke()
      }
    })().catch((error) => setMessage(errorText(error)))
    return () => { active = false }
  }, [doc, selected, tool])

  useEffect(() => {
    if (!job || isServerJobTerminal(job.status)) return
    const timer = window.setInterval(() => void getServerJob(job.id).then((next) => {
      setJob(next)
      if (next.status === 'succeeded' && next.outputs[0]) {
        setResultUrl(next.outputs[0].url)
        setResultAssetId(next.outputs[0].asset_id)
        setDebugImages((items) => [...items.filter((item) => item.key !== '08_ai_output'), { key: '08_ai_output', label: '08 AI Output', assetId: next.outputs[0].asset_id, url: next.outputs[0].url }])
      }
      if (next.status === 'failed') setMessage(next.error_message || 'AI 编辑失败，编辑项目仍已保留。')
    }).catch((error) => setMessage(errorText(error))), 1800)
    return () => window.clearInterval(timer)
  }, [job])

  async function uploadBase(file: File) {
    try {
      setBusy(true); setMessage('')
      const asset = await uploadAsset(await normalizeUpload(file), 'product_reference')
      const layer: PrintDesignLayer = { id: randomUuid(), kind: 'base', assetId: asset.id, name: asset.filename, url: await objectUrl(asset), x: 0, y: 0, width: asset.width, height: asset.height, scaleX: 1, scaleY: 1, rotation: 0, opacity: 1, visible: true, locked: true, keepRatio: true, zIndex: 0 }
      commit({ ...EMPTY, width: asset.width, height: asset.height, layers: [layer] })
      setSelectedId(layer.id)
      setProjectName(`${stem(file.name)} 印花设计`)
      setProjectId(''); setVersion(0); setParams({}, { replace: true }); setDebugImages([]); setResultUrl(''); setResultAssetId('')
    } catch (error) {
      setMessage(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  async function addItem(item: PrintAssetItem, at?: { x: number; y: number }) {
    const current = docRef.current
    if (!current.width) { setMessage('请先上传产品底图。'); return }
    try {
      const naturalWidth = current.width * .35
      const defaultPosition = item.default_position || {}
      const width = Number(defaultPosition.width) || naturalWidth
      const height = Number(defaultPosition.height) || width * item.asset.height / item.asset.width
      const layer: PrintDesignLayer = {
        id: randomUuid(), kind: 'print', assetId: item.asset.id, libraryItemId: item.id,
        name: item.asset_name, url: await objectUrl(item.asset),
        x: at ? at.x - width / 2 : Number(defaultPosition.x) || current.width * .325,
        y: at ? at.y - height / 2 : Number(defaultPosition.y) || current.height * .32,
        width, height, scaleX: 1, scaleY: 1, rotation: Number(defaultPosition.rotation) || 0,
        opacity: 1, visible: true, locked: false, keepRatio: item.keep_ratio_default,
        zIndex: Math.max(0, ...current.layers.map((entry) => entry.zIndex)) + 1,
      }
      commit({ ...current, layers: [...current.layers, layer] })
      setSelectedId(layer.id)
    } catch (error) {
      setMessage(errorText(error))
    }
  }

  async function uploadPrint(file: File, source?: PrintAssetItem) {
    try {
      setBusy(true)
      const asset = await uploadAsset(await normalizeUpload(file), 'print_asset')
      const code = source?.asset_code || `${stem(file.name).replace(/[^A-Za-z0-9_.-]+/g, '-')}-${Date.now().toString(36)}`
      const item = await registerPrintAsset({
        asset_id: asset.id, asset_group_id: source?.asset_group_id || groupId || undefined,
        asset_code: code, asset_name: source?.asset_name || stem(file.name),
        asset_type: source?.asset_type, category: source?.category || undefined, tags: source?.tags,
        allow_rotate: source?.allow_rotate, allow_stretch: source?.allow_stretch,
        keep_ratio_default: source?.keep_ratio_default, version: source ? source.version + 1 : 1,
      })
      await refreshLibrary()
      await addItem(item)
      setMessage(source ? `${source.asset_code} 的 v${item.version} 已创建并加入画布。` : '素材已入库并加入画布。')
    } catch (error) {
      setMessage(errorText(error))
    } finally {
      setBusy(false); setVersionSource(null)
    }
  }

  const point = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: (event.clientX - rect.left) * docRef.current.width / rect.width, y: (event.clientY - rect.top) * docRef.current.height / rect.height }
  }

  function pointerDown(event: ReactPointerEvent<HTMLCanvasElement>) {
    const currentDoc = docRef.current
    if (!currentDoc.width) return
    event.currentTarget.setPointerCapture(event.pointerId)
    const current = point(event)
    if (tool !== 'select') {
      const stroke: PrintDesignStroke = { id: randomUuid(), maskType: currentDoc.mask.activeType, mode: tool === 'mask-erase' ? 'erase' : 'paint', size: currentDoc.mask.brushSize, points: [current] }
      dragRef.current = { kind: 'stroke', startX: current.x, startY: current.y, stroke }
      const next = { ...currentDoc, mask: { ...currentDoc.mask, strokes: [...currentDoc.mask.strokes, stroke] } }
      docRef.current = next; setDoc(next)
      return
    }
    if (selected && !selected.locked) {
      const handle = hitHandle(selected, current.x, current.y, Math.max(12, currentDoc.width / 100))
      if (handle) {
        const center = { x: selected.x + selected.width / 2, y: selected.y + selected.height / 2 }
        dragRef.current = {
          kind: handle === 'rotate' ? 'rotate' : 'resize', layerId: selected.id,
          startX: current.x, startY: current.y, original: { ...selected },
          handle: handle === 'rotate' ? undefined : handle,
          startAngle: Math.atan2(current.y - center.y, current.x - center.x),
        }
        return
      }
    }
    const layer = [...currentDoc.layers].sort((a, b) => b.zIndex - a.zIndex).find((entry) => entry.visible && !entry.locked && pointInLayer(entry, current.x, current.y))
    if (!layer) { setSelectedId(null); return }
    setSelectedId(layer.id)
    dragRef.current = { kind: 'move', layerId: layer.id, startX: current.x, startY: current.y, original: { ...layer } }
  }

  function pointerMove(event: ReactPointerEvent<HTMLCanvasElement>) {
    const drag = dragRef.current
    if (!drag) return
    const current = point(event)
    if (drag.kind === 'stroke' && drag.stroke) {
      drag.stroke = { ...drag.stroke, points: [...drag.stroke.points, current] }
      const stroke = drag.stroke
      setDoc((value) => {
        const next = { ...value, mask: { ...value.mask, strokes: value.mask.strokes.map((item) => item.id === stroke.id ? stroke : item) } }
        docRef.current = next; return next
      })
      return
    }
    if (!drag.original || !drag.layerId) return
    const original = drag.original
    let patch: Partial<PrintDesignLayer> = {}
    if (drag.kind === 'move') {
      patch = { x: original.x + current.x - drag.startX, y: original.y + current.y - drag.startY }
    } else if (drag.kind === 'rotate') {
      const center = { x: original.x + original.width / 2, y: original.y + original.height / 2 }
      const angle = Math.atan2(current.y - center.y, current.x - center.x)
      patch = { rotation: original.rotation + (angle - (drag.startAngle || 0)) * 180 / Math.PI }
    } else {
      const center = { x: original.x + original.width / 2, y: original.y + original.height / 2 }
      const startDistanceX = Math.max(1, Math.abs(drag.startX - center.x))
      const startDistanceY = Math.max(1, Math.abs(drag.startY - center.y))
      const nextX = Math.max(.05, original.scaleX * Math.abs(current.x - center.x) / startDistanceX)
      const nextY = Math.max(.05, original.scaleY * Math.abs(current.y - center.y) / startDistanceY)
      const uniform = Math.max(nextX, nextY)
      patch = original.keepRatio ? { scaleX: uniform, scaleY: uniform } : { scaleX: nextX, scaleY: nextY }
    }
    setDoc((value) => {
      const next = { ...value, layers: value.layers.map((layer) => layer.id === drag.layerId ? { ...layer, ...patch } : layer) }
      docRef.current = next; return next
    })
  }

  function pointerUp() {
    const drag = dragRef.current
    dragRef.current = null
    if (!drag) return
    const current = docRef.current
    const prior = drag.kind === 'stroke'
      ? { ...current, mask: { ...current.mask, strokes: current.mask.strokes.filter((item) => item.id !== drag.stroke?.id) } }
      : { ...current, layers: current.layers.map((layer) => layer.id === drag.layerId && drag.original ? drag.original : layer) }
    setUndo((items) => [...items.slice(-39), cloneDocument(prior)])
    setRedo([])
  }

  async function saveDocument(value: PrintDesignDocument = docRef.current, expectedVersion = version) {
    const baseLayer = value.layers.find((layer) => layer.kind === 'base')
    if (!baseLayer) throw new Error('请先上传产品底图。')
    const draft = { ...value, layers: value.layers.map((layer) => ({ ...layer, url: '' })) }
    if (!projectId) {
      const project = await createProject({ project_type: 'print_design', name: projectName, draft })
      for (const layer of value.layers) {
        const role = layer.kind === 'base' ? 'base_image' : layer.kind === 'result' ? 'ai_result' : 'print_layer'
        await linkProjectAsset(project.id, layer.assetId, role, layer.zIndex, layer.name, layer.kind === 'base')
      }
      setProjectId(project.id); setVersion(project.latest_version.version_number)
      setParams({ project_id: project.id }, { replace: true })
      return { id: project.id, version: project.latest_version.version_number }
    }
    const current = await getProject(projectId)
    const linked = new Set(current.assets.map((item) => `${item.asset.id}:${item.role}`))
    for (const layer of value.layers) {
      const role = layer.kind === 'base' ? 'base_image' : layer.kind === 'result' ? 'ai_result' : 'print_layer'
      if (!linked.has(`${layer.assetId}:${role}`)) await linkProjectAsset(projectId, layer.assetId, role, layer.zIndex, layer.name, layer.kind === 'base')
    }
    const actualVersion = current.latest_version.version_number
    const saved = await saveProjectVersion(projectId, draft, Math.max(expectedVersion, actualVersion), '保存印花图层、变换、Mask 与调试文件')
    setVersion(saved.version_number)
    return { id: projectId, version: saved.version_number }
  }

  async function runAi(mode: 'replace' | 'blend') {
    const current = docRef.current
    const baseLayer = current.layers.find((layer) => layer.kind === 'base')
    const prints = current.layers.filter((layer) => layer.kind === 'print' && layer.visible)
    if (!baseLayer) { setMessage('请先上传底图。'); return }
    if (mode === 'blend' && !prints.length) { setMessage('AI 融合需要至少一个真实印花素材图层。'); return }
    try {
      setBusy(true); setResultUrl(''); setResultAssetId(''); setMessage('正在构建原分辨率输入、Alpha 与三类 Mask…')
      const saved = await saveDocument(current)
      const composite = await renderDocument(current)
      const assetAlpha = await renderAssetAlphaMask(current)
      const providerMask = await renderProviderMask(current, mode === 'blend' ? 'blend' : 'replacement')
      const debugMask = await renderDebugMask(current, mode === 'blend' ? 'blend' : 'replacement')
      const protect = await renderDebugMask(current, 'protect')
      const providerPixels = providerMask.getContext('2d')!.getImageData(0, 0, current.width, current.height).data
      if (!Array.from(providerPixels).some((value, index) => index % 4 === 3 && value < 250)) throw new Error(mode === 'replace' ? '请先用 Replacement Mask 画笔涂抹需要替换的区域。' : '当前印花没有可用的边缘融合区域。')
      const uploaded = await Promise.all([
        uploadPrintDesignReference(pngFile(await canvasBlob(assetAlpha), '03-asset-alpha-mask.png'), { sourceAssetId: baseLayer.assetId, assetRole: 'asset_alpha_mask', metadata: { project_id: saved.id, mode, debug_order: 3 } }),
        uploadPrintDesignReference(pngFile(await canvasBlob(composite), '04-composite.png'), { sourceAssetId: baseLayer.assetId, assetRole: 'composite_input', metadata: { project_id: saved.id, mode, debug_order: 4 } }),
        uploadPrintDesignReference(pngFile(await canvasBlob(protect), '05-protect-mask.png'), { sourceAssetId: baseLayer.assetId, assetRole: 'protect_mask', metadata: { project_id: saved.id, mode, debug_order: 5 } }),
        uploadPrintDesignReference(pngFile(await canvasBlob(providerMask), mode === 'blend' ? '06-blend-provider-mask.png' : '06-replacement-provider-mask.png'), { sourceAssetId: baseLayer.assetId, assetRole: mode === 'blend' ? 'blend_mask' : 'replacement_mask', metadata: { project_id: saved.id, mode, mask_config: current.mask, debug_order: 6 } }),
      ])
      const [alphaAsset, compositeAsset, protectAsset, maskAsset] = uploaded
      const debugRows: DebugImage[] = [
        { key: '01_base', label: '01 Base', assetId: baseLayer.assetId, url: baseLayer.url },
        ...prints.slice(-1).map((layer) => ({ key: '02_asset', label: '02 Asset', assetId: layer.assetId, url: layer.url })),
        { key: '03_asset_alpha_mask', label: '03 Asset Alpha Mask', assetId: alphaAsset.id, url: alphaAsset.url || '' },
        { key: '04_composite', label: '04 Composite / AI Input', assetId: compositeAsset.id, url: compositeAsset.url || '' },
        { key: '05_protect_mask', label: '05 Protect Mask', assetId: protectAsset.id, url: protectAsset.url || '' },
        { key: '06_edit_mask', label: mode === 'blend' ? '06 Blend Mask' : '06 Replacement Mask', assetId: maskAsset.id, url: maskAsset.url || '' },
        { key: '06_mask_preview', label: 'Mask Selection Preview', url: URL.createObjectURL(await canvasBlob(debugMask)) },
        { key: '07_ai_input', label: '07 AI Input', assetId: compositeAsset.id, url: compositeAsset.url || '' },
      ]
      setDebugImages(debugRows)
      const operation = `print_design.${mode}` as const
      const model = await resolveModelCode('mask_edit', operation)
      const submitted = await submitServerJob({
        operation_code: operation, workspace_type: 'print_design', queue_name: 'batch_tryon_queue',
        capability: 'mask_edit', model_code: model, idempotency_key: `print-design:${mode}:${saved.id}:${Date.now()}`,
        project_id: saved.id,
        input: {
          prompt: mode === 'blend' ? current.blendPrompt : current.replacementPrompt,
          reference_asset_ids: [compositeAsset.id], mask_asset_id: maskAsset.id,
          n: 1, size: 'auto', aspect_ratio: 'auto', requested_width: current.width, requested_height: current.height,
          output_format: 'png', quality: 'high', metadata: {
            workflow: `print_design_${mode}`, project_id: saved.id, composite_asset_id: compositeAsset.id,
            asset_alpha_mask_asset_id: alphaAsset.id, protect_mask_asset_id: protectAsset.id,
            edit_mask_asset_id: maskAsset.id, blend_ring_only: mode === 'blend', protect_core: current.mask.protectCore !== false,
          },
        },
      })
      const debugAssetIds = Object.fromEntries(debugRows.filter((item) => item.assetId).map((item) => [item.key, item.assetId!]))
      const nextDoc = { ...current, debugAssetIds, latestJobId: submitted.id }
      const savedVersion = await saveProjectVersion(saved.id, { ...nextDoc, layers: nextDoc.layers.map((layer) => ({ ...layer, url: '' })) }, saved.version, `记录 ${mode} AI 输入与调试文件`)
      setDoc(nextDoc); setVersion(savedVersion.version_number); setJob(submitted)
      setMessage(mode === 'blend' ? 'AI 融合已提交：核心印花受保护，仅编辑边缘融合环。' : 'AI 局部替换已提交：只编辑人工 Replacement Mask。')
    } catch (error) {
      setMessage(`${errorText(error)} 编辑项目和中间文件不会丢失。`)
    } finally {
      setBusy(false)
    }
  }

  async function applyAiResult() {
    if (!resultAssetId) return
    try {
      const asset = await getAsset(resultAssetId)
      const layer: PrintDesignLayer = {
        id: randomUuid(), kind: 'result', assetId: asset.id, name: `AI结果 · ${asset.filename}`,
        url: await objectUrl(asset), x: 0, y: 0, width: docRef.current.width, height: docRef.current.height,
        scaleX: 1, scaleY: 1, rotation: 0, opacity: 1, visible: true, locked: true, keepRatio: true,
        zIndex: Math.max(0, ...docRef.current.layers.map((item) => item.zIndex)) + 100,
      }
      const next = { ...docRef.current, layers: [...docRef.current.layers.filter((item) => item.kind !== 'result'), layer] }
      commit(next); setSelectedId(layer.id); setMessage('AI 结果已作为独立结果图层加入画布，原底图与印花图层仍保留。')
    } catch (error) {
      setMessage(errorText(error))
    }
  }

  async function addGroup() {
    const name = window.prompt('素材组名称')?.trim()
    if (!name) return
    const code = window.prompt('素材组编码', `group-${Date.now().toString(36)}`)?.trim()
    if (!code) return
    try {
      const group = await createPrintAssetGroup({ code, name })
      setGroups((items) => [...items, group]); setGroupId(group.id)
    } catch (error) { setMessage(errorText(error)) }
  }

  async function bindSku() {
    if (!sku.trim() || !groupId) { setMessage('请填写 SKU 并选择素材组。'); return }
    try {
      await createProductPrintMapping({ sku: sku.trim(), asset_group_id: groupId })
      setMessage(`SKU ${sku.trim()} 已绑定到当前素材组。`)
    } catch (error) { setMessage(errorText(error)) }
  }

  async function loadSkuGroup() {
    if (!sku.trim()) { setMessage('请输入 SKU、款号或模板编号。'); return }
    try {
      const mappings = await findProductPrintMappings(sku.trim())
      if (!mappings.length) { setMessage(`没有找到 ${sku.trim()} 对应的素材组。`); return }
      setGroupId(mappings[0].asset_group_id)
      setMessage(`已匹配素材组，可点击素材或“一键加载整组”。`)
    } catch (error) { setMessage(errorText(error)) }
  }

  function editLibraryItem(item: PrintAssetItem) {
    const name = window.prompt('素材名称', item.asset_name)?.trim()
    if (!name) return
    const tags = window.prompt('标签（用逗号分隔）', item.tags.join(',')) ?? item.tags.join(',')
    void updatePrintAsset(item.id, { asset_name: name, tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean) })
      .then(() => refreshLibrary()).catch((error) => setMessage(errorText(error)))
  }

  function duplicateSelected() {
    if (!selected || selected.kind === 'base') return
    const maxZ = Math.max(0, ...docRef.current.layers.map((item) => item.zIndex))
    const copy = { ...selected, id: randomUuid(), name: `${selected.name} 副本`, x: selected.x + 24, y: selected.y + 24, locked: false, zIndex: maxZ + 1 }
    commit({ ...docRef.current, layers: [...docRef.current.layers, copy] }); setSelectedId(copy.id)
  }

  function reorderSelected(where: 'front' | 'back' | 'up' | 'down') {
    if (!selected || selected.kind === 'base') return
    const prints = docRef.current.layers.filter((item) => item.kind !== 'base')
    const min = Math.min(...prints.map((item) => item.zIndex), 1)
    const max = Math.max(...prints.map((item) => item.zIndex), 1)
    const zIndex = where === 'front' ? max + 1 : where === 'back' ? Math.max(1, min - 1) : where === 'up' ? selected.zIndex + 1 : Math.max(1, selected.zIndex - 1)
    patchSelected({ zIndex })
  }

  function undoAction() {
    const prior = undo[undo.length - 1]
    if (!prior) return
    setRedo((items) => [cloneDocument(docRef.current), ...items])
    setUndo((items) => items.slice(0, -1)); setDoc(prior)
  }

  function redoAction() {
    const next = redo[0]
    if (!next) return
    setUndo((items) => [...items, cloneDocument(docRef.current)])
    setRedo((items) => items.slice(1)); setDoc(next)
  }

  const scale = doc.width ? Math.min(1, 920 / doc.width, 720 / doc.height) * doc.zoom / 100 : 1
  const status = useMemo(() => !job ? '' : ({ succeeded: 'AI 处理完成', failed: 'AI 处理失败', waiting_resource: '等待可用通道', queued: '排队中', dispatching: '正在调度', running: 'AI 处理中', retrying: '自动重试中' }[job.status] || job.status), [job])

  return <div className="min-h-[calc(100vh-88px)] overflow-hidden rounded-2xl border border-gray-200 bg-[#F6F7F9] shadow-sm">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-3">
      <div><h1 className="text-lg font-semibold text-gray-950">印花素材与 AI 局部融合</h1><p className="text-xs text-gray-500">真实素材决定内容 · 人工变换决定位置 · Mask 决定 AI 可编辑范围</p></div>
      <div className="flex gap-2"><input value={projectName} onChange={(event) => setProjectName(event.target.value)} className="w-52 rounded-lg border border-gray-200 px-3 py-2 text-sm"/><button disabled={busy || !base} onClick={() => void saveDocument().then(() => setMessage('项目版本已保存。')).catch((error) => setMessage(errorText(error)))} className="rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-40">保存项目</button></div>
    </header>
    <div className="grid min-h-[760px] grid-cols-1 xl:grid-cols-[290px_minmax(0,1fr)_330px]">
      <aside className="border-r border-gray-200 bg-white p-3">
        <div className="mb-3 flex justify-between"><h2 className="text-sm font-semibold">印花素材库</h2><button onClick={() => void addGroup()} className="text-xs text-blue-600">+ 素材组</button></div>
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索编号、名称或标签" className="mb-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"/>
        <select value={groupId} onChange={(event) => setGroupId(event.target.value)} className="mb-2 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm"><option value="">全部素材组</option>{groups.map((group) => <option key={group.id} value={group.id}>{group.name} · {group.code}</option>)}</select>
        <div className="mb-2 grid grid-cols-[1fr_auto_auto] gap-1"><input value={sku} onChange={(event) => setSku(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void loadSkuGroup() }} placeholder="SKU / 款号 / 模板编号" className="min-w-0 rounded-lg border border-gray-200 px-2 py-1.5 text-xs"/><button onClick={() => void loadSkuGroup()} className="rounded-lg border border-gray-200 px-2 text-xs">匹配</button><button onClick={() => void bindSku()} className="rounded-lg border border-gray-200 px-2 text-xs">绑定</button></div>
        <button disabled={!groupId || !library.length || !base} onClick={() => void Promise.all(library.map((item) => addItem(item)))} className="mb-2 w-full rounded-lg border border-gray-200 py-2 text-xs disabled:opacity-40">一键加载当前素材组（{library.length}）</button>
        <button onClick={() => printInputRef.current?.click()} className="mb-3 w-full rounded-lg border border-dashed border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-700">上传印花 PNG / WEBP / JPG / SVG</button>
        <input ref={printInputRef} hidden multiple type="file" accept="image/png,image/webp,image/jpeg,image/svg+xml" onChange={(event) => { const files = [...(event.target.files || [])]; files.reduce((chain, file) => chain.then(() => uploadPrint(file)), Promise.resolve()); event.target.value = '' }}/>
        <input ref={versionInputRef} hidden type="file" accept="image/png,image/webp,image/jpeg,image/svg+xml" onChange={(event) => { const file = event.target.files?.[0]; if (file && versionSource) void uploadPrint(file, versionSource); event.target.value = '' }}/>
        <div className="grid grid-cols-2 gap-2">{library.map((item) => <div key={item.id} draggable onDragStart={(event) => event.dataTransfer.setData('application/x-print-asset', item.id)} className="group rounded-xl border border-gray-200 p-2 hover:border-blue-400">
          <button onClick={() => void addItem(item)} className="w-full text-left"><img src={item.asset.url || ''} className="aspect-square w-full rounded-lg bg-gray-50 object-contain" alt=""/><div className="mt-1 truncate text-xs font-medium">{item.asset_name}</div><div className="truncate text-[10px] text-gray-400">{item.asset_code} · v{item.version}</div></button>
          <div className="mt-1 hidden grid-cols-3 gap-1 group-hover:grid"><button onClick={() => editLibraryItem(item)} className="rounded border px-1 text-[10px]">编辑</button><button onClick={() => { setVersionSource(item); versionInputRef.current?.click() }} className="rounded border px-1 text-[10px]">新版</button><button onClick={() => { if (window.confirm(`归档素材“${item.asset_name}”？历史项目不受影响。`)) void archivePrintAsset(item.id).then(refreshLibrary).catch((error) => setMessage(errorText(error))) }} className="rounded border border-red-200 px-1 text-[10px] text-red-600">归档</button></div>
        </div>)}</div>
      </aside>
      <main className="min-w-0 bg-[#E9ECF1]">
        <div className="flex flex-wrap items-center gap-1 border-b border-gray-300 bg-white px-3 py-2 text-xs">
          {([['select', '选择 / 移动'], ['mask-paint', 'Mask 画笔'], ['mask-erase', 'Mask 橡皮擦']] as const).map(([id, label]) => <button key={id} onClick={() => setTool(id)} className={`rounded-lg px-3 py-2 ${tool === id ? 'bg-blue-600 text-white' : ''}`}>{label}</button>)}
          <button disabled={!undo.length} onClick={undoAction} className="ml-2 disabled:opacity-30">撤销</button><button disabled={!redo.length} onClick={redoAction} className="disabled:opacity-30">重做</button>
          <span className="ml-auto">{doc.width ? `${doc.width} × ${doc.height}px` : '未上传底图'}</span><button onClick={() => setDoc({ ...doc, zoom: Math.max(25, doc.zoom - 10) })}>−</button><span>{doc.zoom}%</span><button onClick={() => setDoc({ ...doc, zoom: Math.min(200, doc.zoom + 10) })}>+</button>
        </div>
        <div className="flex min-h-[704px] items-center justify-center overflow-auto p-6" onDragOver={(event) => event.preventDefault()} onDrop={(event: DragEvent<HTMLDivElement>) => { event.preventDefault(); const id = event.dataTransfer.getData('application/x-print-asset'); const item = library.find((entry) => entry.id === id); const canvas = canvasRef.current; if (!item || !canvas) return; const rect = canvas.getBoundingClientRect(); void addItem(item, { x: (event.clientX - rect.left) * doc.width / rect.width, y: (event.clientY - rect.top) * doc.height / rect.height }) }}>
          {!base ? <button onClick={() => baseInputRef.current?.click()} className="rounded-2xl border-2 border-dashed border-gray-400 bg-white/70 px-12 py-16"><b>上传产品底图</b><span className="mt-2 block text-xs text-gray-500">保留原始分辨率与坐标</span></button> : <canvas ref={canvasRef} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp} style={{ width: doc.width * scale, height: doc.height * scale, touchAction: 'none' }} className="max-w-none bg-white shadow-2xl"/>}
          <input ref={baseInputRef} hidden type="file" accept="image/jpeg,image/png,image/webp,image/svg+xml" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadBase(file); event.target.value = '' }}/>
        </div>
      </main>
      <aside className="space-y-4 border-l border-gray-200 bg-white p-3">
        <section><div className="mb-2 flex justify-between"><h2 className="text-sm font-semibold">图层</h2>{base && <button onClick={() => baseInputRef.current?.click()} className="text-xs text-blue-600">新建底图项目</button>}</div><div className="space-y-1">{[...doc.layers].sort((a, b) => b.zIndex - a.zIndex).map((layer) => <button key={layer.id} onClick={() => setSelectedId(layer.id)} className={`flex w-full rounded-lg border px-2 py-2 text-left text-xs ${selectedId === layer.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}><span className="mr-2 text-gray-400">{layer.kind === 'base' ? '底图' : layer.kind === 'result' ? '结果' : '印花'}</span><span className="min-w-0 flex-1 truncate">{layer.name}</span><span>{!layer.visible ? '◌' : layer.locked ? '🔒' : ''}</span></button>)}</div></section>
        {selected && <section className="rounded-xl border border-gray-200 p-3"><h3 className="mb-3 text-xs font-semibold">变换属性</h3><div className="grid grid-cols-2 gap-2"><Num label="X" value={selected.x} onChange={(x) => patchSelected({ x })}/><Num label="Y" value={selected.y} onChange={(y) => patchSelected({ y })}/><Num label="宽度" min={1} value={selected.width * selected.scaleX} onChange={(value) => patchSelected({ scaleX: value / selected.width, scaleY: selected.keepRatio ? value / selected.width : selected.scaleY })}/><Num label="高度" min={1} value={selected.height * selected.scaleY} onChange={(value) => patchSelected({ scaleY: value / selected.height, scaleX: selected.keepRatio ? value / selected.height : selected.scaleX })}/><Num label="旋转" value={selected.rotation} onChange={(rotation) => patchSelected({ rotation })}/><Num label="透明度%" value={selected.opacity * 100} onChange={(value) => patchSelected({ opacity: Math.max(0, Math.min(1, value / 100)) })}/></div><div className="mt-3 flex flex-wrap gap-1 text-[11px]"><label className="mr-1"><input type="checkbox" checked={selected.keepRatio} onChange={(event) => patchSelected({ keepRatio: event.target.checked })}/> 锁定比例</label><button onClick={() => patchSelected({ locked: !selected.locked })} className="rounded border px-2">{selected.locked ? '解锁' : '锁定'}</button><button onClick={() => patchSelected({ visible: !selected.visible })} className="rounded border px-2">{selected.visible ? '隐藏' : '显示'}</button><button disabled={selected.kind === 'base'} onClick={duplicateSelected} className="rounded border px-2 disabled:opacity-30">复制</button><button disabled={selected.kind === 'base'} onClick={() => reorderSelected('front')} className="rounded border px-2 disabled:opacity-30">置顶</button><button disabled={selected.kind === 'base'} onClick={() => reorderSelected('up')} className="rounded border px-2 disabled:opacity-30">前移</button><button disabled={selected.kind === 'base'} onClick={() => reorderSelected('down')} className="rounded border px-2 disabled:opacity-30">后移</button><button disabled={selected.kind === 'base'} onClick={() => reorderSelected('back')} className="rounded border px-2 disabled:opacity-30">置底</button><button disabled={selected.kind === 'base'} onClick={() => { commit({ ...docRef.current, layers: docRef.current.layers.filter((layer) => layer.id !== selected.id) }); setSelectedId(null) }} className="rounded border border-red-200 px-2 text-red-600 disabled:opacity-30">删除</button></div></section>}
        <section className="rounded-xl border border-gray-200 p-3"><h3 className="mb-2 text-xs font-semibold">Mask 图层</h3><select value={doc.mask.activeType} onChange={(event) => commit({ ...doc, mask: { ...doc.mask, activeType: event.target.value as PrintDesignMaskType } })} className="mb-2 w-full rounded-lg border border-gray-200 p-2 text-xs"><option value="replacement">Replacement · 人工局部替换</option><option value="protect">Protect · 核心保护</option><option value="blend">Blend · Alpha 边缘融合</option></select><div className="grid grid-cols-2 gap-2"><Num label="画笔px" min={1} value={doc.mask.brushSize} onChange={(value) => commit({ ...doc, mask: { ...doc.mask, brushSize: Math.max(1, value) } })}/><Num label="扩展px" min={0} value={doc.mask.expand} onChange={(value) => commit({ ...doc, mask: { ...doc.mask, expand: Math.max(0, value) } })}/><Num label="收缩px" min={0} value={doc.mask.contract} onChange={(value) => commit({ ...doc, mask: { ...doc.mask, contract: Math.max(0, value) } })}/><Num label="羽化px" min={0} value={doc.mask.feather} onChange={(value) => commit({ ...doc, mask: { ...doc.mask, feather: Math.max(0, Math.min(30, value)) } })}/><Num label="叠加透明度%" min={0} value={doc.mask.overlayOpacity * 100} onChange={(value) => commit({ ...doc, mask: { ...doc.mask, overlayOpacity: Math.max(0, Math.min(1, value / 100)) } })}/></div><label className="mt-2 block text-xs"><input type="checkbox" checked={doc.mask.protectCore !== false} onChange={(event) => commit({ ...doc, mask: { ...doc.mask, protectCore: event.target.checked } })}/> AI 融合时保护素材核心</label><div className="mt-2 flex gap-2"><button onClick={() => commit({ ...doc, mask: { ...doc.mask, inverted: { ...doc.mask.inverted, [doc.mask.activeType]: !doc.mask.inverted?.[doc.mask.activeType] } } })} className="rounded border px-2 py-1 text-xs">反选</button><button onClick={() => commit({ ...doc, mask: { ...doc.mask, strokes: doc.mask.strokes.filter((item) => item.maskType !== doc.mask.activeType) } })} className="rounded border px-2 py-1 text-xs">清空当前 Mask</button></div><p className="mt-2 text-[10px] text-gray-500">Replacement 只认人工涂抹；Protect 默认包含真实印花核心；Blend 由素材 Alpha 自动生成外围融合环。红/绿/橙仅为界面预览。</p></section>
        <section className="rounded-xl border border-gray-200 p-3"><h3 className="text-xs font-semibold">AI 操作</h3><label className="mt-2 block text-[10px] text-gray-500">AI 局部替换附加要求</label><textarea value={doc.replacementPrompt} onChange={(event) => setDoc({ ...doc, replacementPrompt: event.target.value })} rows={3} className="mt-1 w-full rounded-lg border border-gray-200 p-2 text-xs"/><button disabled={busy || !base} onClick={() => void runAi('replace')} className="mt-2 w-full rounded-lg border border-blue-600 py-2 text-sm font-semibold text-blue-700 disabled:opacity-40">AI 局部替换</button><label className="mt-3 block text-[10px] text-gray-500">AI 商品融合附加要求</label><textarea value={doc.blendPrompt} onChange={(event) => setDoc({ ...doc, blendPrompt: event.target.value })} rows={3} className="mt-1 w-full rounded-lg border border-gray-200 p-2 text-xs"/><button disabled={busy || !base} onClick={() => void runAi('blend')} className="mt-2 w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white disabled:opacity-40">AI 商品融合</button></section>
        {(message || status) && <div className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">{message}{status && <div>{status}{job && ` · ${job.progress}%`}</div>}</div>}
        {resultUrl && <section className="rounded-xl border border-gray-200 p-2"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold">08 AI Output</h3><button onClick={() => void applyAiResult()} className="rounded border border-blue-300 px-2 py-1 text-[10px] text-blue-700">作为结果图层</button></div><img src={resultUrl} className="w-full rounded-lg border" alt="AI输出"/></section>}
        {debugImages.length > 0 && <section className="rounded-xl border border-gray-200 p-2"><button onClick={() => setShowDebug(!showDebug)} className="flex w-full items-center justify-between text-xs font-semibold"><span>调试中间图（{debugImages.length}）</span><span>{showDebug ? '收起' : '展开'}</span></button>{showDebug && <div className="mt-2 grid grid-cols-2 gap-2">{debugImages.map((item) => <figure key={item.key}><img src={item.url} className="aspect-square w-full rounded border bg-gray-50 object-contain" alt={item.label}/><figcaption className="mt-1 truncate text-[9px] text-gray-500">{item.label}</figcaption></figure>)}</div>}</section>}
      </aside>
    </div>
  </div>
}
