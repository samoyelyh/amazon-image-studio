export interface RegionPoint { x: number; y: number }

export interface RegionStroke {
  action: 'paint' | 'erase'
  radius: number
  points: RegionPoint[]
}

export interface RegionBounds { x: number; y: number; width: number; height: number }

export const FULL_REGION_BOUNDS: RegionBounds = { x: 0, y: 0, width: 1, height: 1 }

export function normalizeRegionBounds(bounds: RegionBounds): RegionBounds {
  const left = clamp(Math.min(bounds.x, bounds.x + bounds.width))
  const top = clamp(Math.min(bounds.y, bounds.y + bounds.height))
  const right = clamp(Math.max(bounds.x, bounds.x + bounds.width))
  const bottom = clamp(Math.max(bounds.y, bounds.y + bounds.height))
  return {
    x: round(left),
    y: round(top),
    width: round(Math.max(0, right - left)),
    height: round(Math.max(0, bottom - top)),
  }
}

export function validRegionBounds(bounds: RegionBounds | null | undefined): bounds is RegionBounds {
  if (!bounds) return false
  const normalized = normalizeRegionBounds(bounds)
  return normalized.width >= 0.005 && normalized.height >= 0.005
}

export const DEFAULT_REGION_REPLACE_PROMPT = `Treat the already placed content as real, indivisible garment surface texture.

Keep the main internal visual structure, pattern layout, line relationships, proportions, colors and relative positions stable. Do not redesign or reconstruct the protected surface content.

Only make the minimum adjustments needed around the editable fusion boundary: edge transition, fabric attachment, folds, perspective, lighting, shadows and material consistency. Make the covered content look naturally integrated without changing the protected product surface.`

export function regionBounds(strokes: RegionStroke[]): RegionBounds | null {
  const painted = strokes.filter((stroke) => stroke.action === 'paint' && stroke.points.length)
  if (!painted.length) return null
  let left = 1
  let top = 1
  let right = 0
  let bottom = 0
  painted.forEach((stroke) => {
    stroke.points.forEach((point) => {
      left = Math.min(left, point.x - stroke.radius)
      top = Math.min(top, point.y - stroke.radius)
      right = Math.max(right, point.x + stroke.radius)
      bottom = Math.max(bottom, point.y + stroke.radius)
    })
  })
  left = clamp(left)
  top = clamp(top)
  right = clamp(right)
  bottom = clamp(bottom)
  if (right <= left || bottom <= top) return null
  return { x: round(left), y: round(top), width: round(right - left), height: round(bottom - top) }
}

export function normalizeRegionStrokes(strokes: RegionStroke[]) {
  return strokes.map((stroke) => ({
    action: stroke.action,
    radius: round(clamp(stroke.radius)),
    points: stroke.points.map((point) => ({ x: round(clamp(point.x)), y: round(clamp(point.y)) })),
  }))
}

export async function renderRegionReplaceFiles(
  baseBlob: Blob,
  imageCBlob: Blob,
  targetStrokes: RegionStroke[],
  sourceStrokes: RegionStroke[],
) {
  if (!regionBounds(targetStrokes)) throw new Error('请先在结果图上涂抹需要替换的目标区域。')
  const [base, imageC] = await Promise.all([loadImage(baseBlob), loadImage(imageCBlob)])
  const targetSelection = selectionCanvas(base.width, base.height, targetStrokes)
  const targetMask = document.createElement('canvas')
  targetMask.width = base.width
  targetMask.height = base.height
  const targetContext = requiredContext(targetMask)
  targetContext.fillStyle = '#fff'
  targetContext.fillRect(0, 0, base.width, base.height)
  targetContext.globalCompositeOperation = 'destination-out'
  targetContext.drawImage(targetSelection, 0, 0)
  targetContext.globalCompositeOperation = 'source-over'

  const sourceBounds = regionBounds(sourceStrokes)
  const sourceSelection = sourceBounds
    ? selectionCanvas(imageC.width, imageC.height, sourceStrokes)
    : fullSelectionCanvas(imageC.width, imageC.height)
  const sourceMask = document.createElement('canvas')
  sourceMask.width = imageC.width
  sourceMask.height = imageC.height
  const sourceMaskContext = requiredContext(sourceMask)
  sourceMaskContext.fillStyle = '#000'
  sourceMaskContext.fillRect(0, 0, imageC.width, imageC.height)
  sourceMaskContext.drawImage(sourceSelection, 0, 0)

  const bounds = sourceBounds ?? { x: 0, y: 0, width: 1, height: 1 }
  const left = Math.max(0, Math.floor(bounds.x * imageC.width))
  const top = Math.max(0, Math.floor(bounds.y * imageC.height))
  const right = Math.min(imageC.width, Math.ceil((bounds.x + bounds.width) * imageC.width))
  const bottom = Math.min(imageC.height, Math.ceil((bounds.y + bounds.height) * imageC.height))
  const patch = document.createElement('canvas')
  patch.width = Math.max(1, right - left)
  patch.height = Math.max(1, bottom - top)
  const patchContext = requiredContext(patch)
  patchContext.drawImage(imageC, -left, -top)
  patchContext.globalCompositeOperation = 'destination-in'
  patchContext.drawImage(sourceSelection, -left, -top)
  patchContext.globalCompositeOperation = 'source-over'

  return {
    targetMask: await canvasFile(targetMask, 'target-edit-mask.png'),
    sourceMask: sourceBounds ? await canvasFile(sourceMask, 'source-reference-mask.png') : null,
    referencePatch: await canvasFile(patch, 'image-c-reference-patch.png'),
    targetMetadata: {
      normalized_bounds: regionBounds(targetStrokes),
      strokes: normalizeRegionStrokes(targetStrokes),
      mask_semantics: 'transparent_is_editable',
    },
    sourceMetadata: {
      normalized_bounds: sourceBounds,
      strokes: normalizeRegionStrokes(sourceStrokes),
      full_image_fallback: !sourceBounds,
    },
  }
}

export async function renderRegionReplaceFrameFiles(
  baseBlob: Blob,
  imageCBlob: Blob,
  targetFrame: RegionBounds,
  sourceFrame: RegionBounds,
  options: {
    editMode?: 'texture_protect' | 'normal_edit'
    edgeFeatherPx?: number
    coreInsetPx?: number
  } = {},
) {
  if (!validRegionBounds(targetFrame)) throw new Error('请先在结果图上框选需要替换的目标区域。')
  if (!validRegionBounds(sourceFrame)) throw new Error('请先在图C上框选需要完整迁移的来源图案。')
  const [base, imageC] = await Promise.all([loadImage(baseBlob), loadImage(imageCBlob)])
  const targetBounds = normalizeRegionBounds(targetFrame)
  const sourceBounds = normalizeRegionBounds(sourceFrame)

  const targetMask = document.createElement('canvas')
  targetMask.width = base.width
  targetMask.height = base.height
  const targetContext = requiredContext(targetMask)
  targetContext.fillStyle = '#fff'
  targetContext.fillRect(0, 0, base.width, base.height)
  const targetPixels = pixelBounds(targetBounds, base.width, base.height)
  const editMode = options.editMode ?? 'texture_protect'
  const edgeFeatherPx = Math.max(0, Math.min(128, Math.round(options.edgeFeatherPx ?? 24)))
  const coreInsetPx = Math.max(0, Math.min(128, Math.round(options.coreInsetPx ?? 12)))
  const fusionPixels = expandPixelBounds(targetPixels, edgeFeatherPx, base.width, base.height)
  const corePixels = insetPixelBounds(targetPixels, coreInsetPx)
  if (editMode === 'texture_protect') {
    targetContext.clearRect(fusionPixels.left, fusionPixels.top, fusionPixels.width, fusionPixels.height)
    if (corePixels.width > 0 && corePixels.height > 0) {
      targetContext.fillRect(corePixels.left, corePixels.top, corePixels.width, corePixels.height)
    }
  } else {
    targetContext.clearRect(targetPixels.left, targetPixels.top, targetPixels.width, targetPixels.height)
  }

  const sourceMask = document.createElement('canvas')
  sourceMask.width = imageC.width
  sourceMask.height = imageC.height
  const sourceMaskContext = requiredContext(sourceMask)
  sourceMaskContext.fillStyle = '#000'
  sourceMaskContext.fillRect(0, 0, imageC.width, imageC.height)
  sourceMaskContext.fillStyle = '#fff'
  const sourcePixels = pixelBounds(sourceBounds, imageC.width, imageC.height)
  sourceMaskContext.fillRect(sourcePixels.left, sourcePixels.top, sourcePixels.width, sourcePixels.height)

  const patch = document.createElement('canvas')
  patch.width = sourcePixels.width
  patch.height = sourcePixels.height
  requiredContext(patch).drawImage(
    imageC,
    sourcePixels.left,
    sourcePixels.top,
    sourcePixels.width,
    sourcePixels.height,
    0,
    0,
    sourcePixels.width,
    sourcePixels.height,
  )

  const intermediate = document.createElement('canvas')
  intermediate.width = base.width
  intermediate.height = base.height
  const intermediateContext = requiredContext(intermediate)
  intermediateContext.drawImage(base, 0, 0)
  intermediateContext.drawImage(
    patch, 0, 0, patch.width, patch.height,
    targetPixels.left, targetPixels.top, targetPixels.width, targetPixels.height,
  )

  return {
    targetMask: await canvasFile(targetMask, 'target-edit-frame-mask.png'),
    sourceMask: await canvasFile(sourceMask, 'source-reference-frame-mask.png'),
    referencePatch: await canvasFile(patch, 'image-c-exact-reference-patch.png'),
    intermediatePreview: await canvasFile(intermediate, 'pixel-precomposed-preview.png'),
    targetMetadata: {
      selection_mode: 'resizable_frame',
      normalized_bounds: targetBounds,
      pixel_bounds: targetPixels,
      fusion_pixel_bounds: editMode === 'texture_protect' ? fusionPixels : targetPixels,
      core_pixel_bounds: editMode === 'texture_protect' ? corePixels : null,
      mask_semantics: 'transparent_is_editable',
      transfer_mode: 'stretch_to_target_frame',
      edit_mode: editMode,
      edge_feather_px: edgeFeatherPx,
      core_inset_px: coreInsetPx,
    },
    sourceMetadata: {
      selection_mode: 'resizable_frame',
      normalized_bounds: sourceBounds,
      pixel_bounds: sourcePixels,
      full_image_fallback: false,
    },
  }
}

export async function loadImageElement(blob: Blob) {
  return loadImage(blob)
}

export function drawSelectionOverlay(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  strokes: RegionStroke[],
  color: string,
) {
  const selection = selectionCanvas(width, height, strokes)
  const overlay = document.createElement('canvas')
  overlay.width = width
  overlay.height = height
  const overlayContext = requiredContext(overlay)
  overlayContext.fillStyle = color
  overlayContext.fillRect(0, 0, width, height)
  overlayContext.globalCompositeOperation = 'destination-in'
  overlayContext.drawImage(selection, 0, 0)
  context.save()
  context.globalAlpha = 0.45
  context.drawImage(overlay, 0, 0)
  context.restore()
}

function selectionCanvas(width: number, height: number, strokes: RegionStroke[]) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = requiredContext(canvas)
  const scale = Math.min(width, height)
  strokes.forEach((stroke) => {
    context.save()
    context.globalCompositeOperation = stroke.action === 'erase' ? 'destination-out' : 'source-over'
    context.strokeStyle = '#fff'
    context.fillStyle = '#fff'
    context.lineWidth = Math.max(2, stroke.radius * scale * 2)
    context.lineCap = 'round'
    context.lineJoin = 'round'
    const points = stroke.points
    if (points.length === 1) {
      context.beginPath()
      context.arc(points[0].x * width, points[0].y * height, Math.max(1, stroke.radius * scale), 0, Math.PI * 2)
      context.fill()
    } else if (points.length > 1) {
      context.beginPath()
      context.moveTo(points[0].x * width, points[0].y * height)
      points.slice(1).forEach((point) => context.lineTo(point.x * width, point.y * height))
      context.stroke()
    }
    context.restore()
  })
  return canvas
}

function fullSelectionCanvas(width: number, height: number) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = requiredContext(canvas)
  context.fillStyle = '#fff'
  context.fillRect(0, 0, width, height)
  return canvas
}

function pixelBounds(bounds: RegionBounds, width: number, height: number) {
  const left = Math.max(0, Math.floor(bounds.x * width))
  const top = Math.max(0, Math.floor(bounds.y * height))
  const right = Math.min(width, Math.max(left + 1, Math.ceil((bounds.x + bounds.width) * width)))
  const bottom = Math.min(height, Math.max(top + 1, Math.ceil((bounds.y + bounds.height) * height)))
  return { left, top, width: right - left, height: bottom - top }
}

function expandPixelBounds(bounds: { left: number; top: number; width: number; height: number }, amount: number, width: number, height: number) {
  const left = Math.max(0, bounds.left - amount)
  const top = Math.max(0, bounds.top - amount)
  const right = Math.min(width, bounds.left + bounds.width + amount)
  const bottom = Math.min(height, bounds.top + bounds.height + amount)
  return { left, top, width: right - left, height: bottom - top }
}

function insetPixelBounds(bounds: { left: number; top: number; width: number; height: number }, amount: number) {
  const inset = Math.min(amount, Math.floor((bounds.width - 1) / 2), Math.floor((bounds.height - 1) / 2))
  return {
    left: bounds.left + inset,
    top: bounds.top + inset,
    width: Math.max(1, bounds.width - inset * 2),
    height: Math.max(1, bounds.height - inset * 2),
  }
}

function requiredContext(canvas: HTMLCanvasElement) {
  const context = canvas.getContext('2d')
  if (!context) throw new Error('当前浏览器无法创建图片处理画布。')
  return context
}

function loadImage(blob: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const image = new Image()
    image.onload = () => { URL.revokeObjectURL(url); resolve(image) }
    image.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片加载失败。')) }
    image.src = url
  })
}

function canvasFile(canvas: HTMLCanvasElement, filename: string): Promise<File> {
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (!blob) reject(new Error('图片区域处理失败。'))
    else resolve(new File([blob], filename, { type: 'image/png' }))
  }, 'image/png'))
}

function clamp(value: number) { return Math.max(0, Math.min(1, value)) }
function round(value: number) { return Math.round(value * 100000) / 100000 }
