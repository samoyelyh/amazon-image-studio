export type PrintDesignMaskType = 'replacement' | 'protect' | 'blend'

export interface PrintDesignStrokePoint { x: number; y: number }
export interface PrintDesignStroke {
  id: string
  maskType: PrintDesignMaskType
  mode: 'paint' | 'erase'
  size: number
  points: PrintDesignStrokePoint[]
}

export interface PrintDesignLayer {
  id: string
  kind: 'base' | 'print' | 'result'
  assetId: string
  libraryItemId?: string
  name: string
  url: string
  x: number
  y: number
  width: number
  height: number
  scaleX: number
  scaleY: number
  rotation: number
  opacity: number
  visible: boolean
  locked: boolean
  keepRatio: boolean
  zIndex: number
}

export interface PrintDesignMaskConfig {
  activeType: PrintDesignMaskType
  brushSize: number
  expand: number
  contract: number
  feather: number
  overlayOpacity: number
  protectCore?: boolean
  inverted?: Partial<Record<PrintDesignMaskType, boolean>>
  strokes: PrintDesignStroke[]
}

export interface PrintDesignDocument {
  schemaVersion: 2
  width: number
  height: number
  zoom: number
  layers: PrintDesignLayer[]
  mask: PrintDesignMaskConfig
  replacementPrompt: string
  blendPrompt: string
  debugAssetIds?: Record<string, string>
  latestJobId?: string
}

const imageCache = new Map<string, Promise<HTMLImageElement>>()

export function loadCanvasImage(url: string) {
  const existing = imageCache.get(url)
  if (existing) return existing
  const promise = new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => resolve(image)
    image.onerror = reject
    image.src = url
  })
  imageCache.set(url, promise)
  return promise
}

function drawTransformed(context: CanvasRenderingContext2D, image: CanvasImageSource, layer: PrintDesignLayer) {
  context.save()
  context.globalAlpha = layer.opacity
  context.translate(layer.x + layer.width / 2, layer.y + layer.height / 2)
  context.rotate(layer.rotation * Math.PI / 180)
  context.scale(layer.scaleX, layer.scaleY)
  context.drawImage(image, -layer.width / 2, -layer.height / 2, layer.width, layer.height)
  context.restore()
}

export async function renderDocument(document: PrintDesignDocument, options: { printsOnly?: boolean } = {}) {
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width
  canvas.height = document.height
  const context = canvas.getContext('2d', { willReadFrequently: true })!
  const layers = [...document.layers].filter((layer) => layer.visible && (!options.printsOnly || layer.kind === 'print')).sort((a, b) => a.zIndex - b.zIndex)
  for (const layer of layers) {
    const image = await loadCanvasImage(layer.url)
    drawTransformed(context, image, layer)
  }
  return canvas
}

function morphology(source: Uint8Array, width: number, height: number, radius: number, mode: 'dilate' | 'erode') {
  if (radius <= 0) return source.slice()
  const r = Math.min(128, Math.round(radius))
  const horizontal = new Uint8Array(source.length)
  const output = new Uint8Array(source.length)
  const filterLine = (length: number, read: (index: number) => number, write: (index: number, value: number) => void) => {
    const paddedLength = length + r * 2
    const window = r * 2 + 1
    const queue = new Int32Array(paddedLength)
    const values = new Uint8Array(paddedLength)
    for (let index = 0; index < length; index += 1) values[index + r] = read(index)
    let head = 0; let tail = 0
    for (let index = 0; index < paddedLength; index += 1) {
      while (head < tail && queue[head] <= index - window) head += 1
      while (head < tail && (mode === 'dilate' ? values[queue[tail - 1]] <= values[index] : values[queue[tail - 1]] >= values[index])) tail -= 1
      queue[tail] = index; tail += 1
      if (index >= window - 1) write(index - window + 1, values[queue[head]])
    }
  }
  for (let y = 0; y < height; y += 1) filterLine(width, (x) => source[y * width + x], (x, value) => { horizontal[y * width + x] = value })
  for (let x = 0; x < width; x += 1) filterLine(height, (y) => horizontal[y * width + x], (y, value) => { output[y * width + x] = value })
  return output
}

function drawStrokes(canvas: HTMLCanvasElement, strokes: PrintDesignStroke[], type: PrintDesignMaskType) {
  const context = canvas.getContext('2d')!
  for (const stroke of strokes.filter((item) => item.maskType === type)) {
    if (!stroke.points.length) continue
    context.save()
    context.globalCompositeOperation = stroke.mode === 'erase' ? 'destination-out' : 'source-over'
    context.strokeStyle = '#fff'; context.fillStyle = '#fff'
    context.lineCap = 'round'; context.lineJoin = 'round'; context.lineWidth = stroke.size
    context.beginPath()
    context.moveTo(stroke.points[0].x, stroke.points[0].y)
    stroke.points.slice(1).forEach((point) => context.lineTo(point.x, point.y))
    if (stroke.points.length === 1) context.arc(stroke.points[0].x, stroke.points[0].y, stroke.size / 2, 0, Math.PI * 2)
    stroke.points.length === 1 ? context.fill() : context.stroke()
    context.restore()
  }
}

async function printAlpha(document: PrintDesignDocument) {
  const canvas = await renderDocument(document, { printsOnly: true })
  const rgba = canvas.getContext('2d', { willReadFrequently: true })!.getImageData(0, 0, document.width, document.height).data
  const alpha = new Uint8Array(document.width * document.height)
  for (let index = 0; index < alpha.length; index += 1) alpha[index] = rgba[index * 4 + 3] > 8 ? 1 : 0
  return alpha
}

export async function renderAssetAlphaMask(document: PrintDesignDocument) {
  const alpha = await printAlpha(document)
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width; canvas.height = document.height
  const context = canvas.getContext('2d')!
  const output = context.createImageData(document.width, document.height)
  for (let index = 0; index < alpha.length; index += 1) {
    const value = alpha[index] ? 255 : 0
    output.data[index * 4] = value; output.data[index * 4 + 1] = value; output.data[index * 4 + 2] = value; output.data[index * 4 + 3] = 255
  }
  context.putImageData(output, 0, 0)
  return canvas
}

function manualSelection(document: PrintDesignDocument, type: PrintDesignMaskType) {
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width; canvas.height = document.height
  drawStrokes(canvas, document.mask.strokes, type)
  const rgba = canvas.getContext('2d', { willReadFrequently: true })!.getImageData(0, 0, document.width, document.height).data
  const selection = new Uint8Array(document.width * document.height)
  for (let index = 0; index < selection.length; index += 1) selection[index] = rgba[index * 4 + 3] > 8 ? 1 : 0
  return selection
}

async function effectiveSelection(document: PrintDesignDocument, type: PrintDesignMaskType) {
  const assetAlpha = await printAlpha(document)
  const manual = manualSelection(document, type)
  const protectedManual = manualSelection(document, 'protect')
  const expand = Math.max(0, document.mask.expand)
  const contract = Math.max(0, document.mask.contract)
  const selection = new Uint8Array(assetAlpha.length)
  if (type === 'replacement') {
    selection.set(manual)
  } else if (type === 'protect') {
    for (let index = 0; index < selection.length; index += 1) selection[index] = assetAlpha[index] || manual[index] ? 1 : 0
  } else {
    const outer = morphology(assetAlpha, document.width, document.height, expand, 'dilate')
    const inner = document.mask.protectCore === false
      ? morphology(assetAlpha, document.width, document.height, contract, 'erode')
      : assetAlpha
    for (let index = 0; index < selection.length; index += 1) {
      selection[index] = ((outer[index] && !inner[index]) || manual[index]) && !protectedManual[index] ? 1 : 0
    }
  }
  if (document.mask.inverted?.[type]) {
    for (let index = 0; index < selection.length; index += 1) selection[index] = selection[index] ? 0 : 1
  }
  return selection
}

export async function renderMaskPreview(document: PrintDesignDocument, type: PrintDesignMaskType) {
  const selection = await effectiveSelection(document, type)
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width; canvas.height = document.height
  const context = canvas.getContext('2d')!
  const output = context.createImageData(document.width, document.height)
  const color = type === 'protect' ? [34, 197, 94] : type === 'blend' ? [245, 158, 11] : [239, 68, 68]
  for (let index = 0; index < selection.length; index += 1) {
    output.data[index * 4] = color[0]; output.data[index * 4 + 1] = color[1]; output.data[index * 4 + 2] = color[2]
    output.data[index * 4 + 3] = selection[index] ? 255 : 0
  }
  context.putImageData(output, 0, 0)
  return canvas
}

export async function renderDebugMask(document: PrintDesignDocument, type: PrintDesignMaskType) {
  const selection = await effectiveSelection(document, type)
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width; canvas.height = document.height
  const context = canvas.getContext('2d')!
  const output = context.createImageData(document.width, document.height)
  for (let index = 0; index < selection.length; index += 1) {
    const value = selection[index] ? 255 : 0
    output.data[index * 4] = value; output.data[index * 4 + 1] = value; output.data[index * 4 + 2] = value; output.data[index * 4 + 3] = 255
  }
  context.putImageData(output, 0, 0)
  return canvas
}

export async function renderProviderMask(document: PrintDesignDocument, type: PrintDesignMaskType) {
  const selection = await effectiveSelection(document, type)
  const canvas = window.document.createElement('canvas')
  canvas.width = document.width; canvas.height = document.height
  const context = canvas.getContext('2d')!
  const output = context.createImageData(document.width, document.height)
  const feather = Math.max(0, Math.min(30, Math.round(document.mask.feather)))
  const inner = feather ? morphology(selection, document.width, document.height, feather, 'erode') : selection
  const outer = feather ? morphology(selection, document.width, document.height, feather, 'dilate') : selection
  for (let index = 0; index < selection.length; index += 1) {
    const editableAlpha = inner[index] ? 255 : selection[index] ? 210 : outer[index] ? 80 : 0
    output.data[index * 4] = 0; output.data[index * 4 + 1] = 0; output.data[index * 4 + 2] = 0
    output.data[index * 4 + 3] = 255 - editableAlpha
  }
  context.putImageData(output, 0, 0)
  return canvas
}

export function canvasBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('PNG 导出失败')), 'image/png'))
}

export function pointInLayer(layer: PrintDesignLayer, x: number, y: number) {
  const angle = -layer.rotation * Math.PI / 180
  const cx = layer.x + layer.width / 2; const cy = layer.y + layer.height / 2
  const dx = x - cx; const dy = y - cy
  const localX = (dx * Math.cos(angle) - dy * Math.sin(angle)) / layer.scaleX + layer.width / 2
  const localY = (dx * Math.sin(angle) + dy * Math.cos(angle)) / layer.scaleY + layer.height / 2
  return localX >= 0 && localY >= 0 && localX <= layer.width && localY <= layer.height
}
