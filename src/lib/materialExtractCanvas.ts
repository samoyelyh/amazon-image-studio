import type { MaterialStroke } from './materialExtractApi'

export interface SelectionBounds { x: number; y: number; width: number; height: number }

export function scaleSelectionBounds(
  bounds: SelectionBounds,
  sourceWidth: number,
  sourceHeight: number,
  workingWidth: number,
  workingHeight: number,
): SelectionBounds {
  return {
    x: bounds.x * sourceWidth / workingWidth,
    y: bounds.y * sourceHeight / workingHeight,
    width: bounds.width * sourceWidth / workingWidth,
    height: bounds.height * sourceHeight / workingHeight,
  }
}

export function scaleStrokes(
  strokes: MaterialStroke[],
  sourceWidth: number,
  sourceHeight: number,
  workingWidth: number,
  workingHeight: number,
): MaterialStroke[] {
  const scaleX = sourceWidth / workingWidth
  const scaleY = sourceHeight / workingHeight
  const brushScale = (scaleX + scaleY) / 2
  return strokes.map((stroke) => ({
    ...stroke,
    size: stroke.size * brushScale,
    points: stroke.points.map((point) => ({ x: point.x * scaleX, y: point.y * scaleY })),
  }))
}

export function workingImageSize(width: number, height: number, maxEdge = 1600) {
  const scale = Math.min(1, maxEdge / Math.max(width, height))
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

