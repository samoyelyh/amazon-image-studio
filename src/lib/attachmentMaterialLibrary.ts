import type { AttachmentMaterialVersion } from './attachmentMaterialApi'

export const attachmentMaterialModuleOrder = [
  'pure_white', 'custom_process', 'stadium_scene', 'gift_scene', 'detail_display', 'casual_scene',
] as const

export const attachmentMaterialModuleLabels: Record<string, string> = {
  pure_white: '纯白底主图',
  custom_process: '定制流程图',
  stadium_scene: '观赛场景图',
  gift_scene: '礼品场景图',
  detail_display: '细节展示图',
  casual_scene: '休闲场景图',
}

export function attachmentMaterialCompletionLabel(moduleCount: number, targetModuleCount: number, isComplete?: boolean) {
  const complete = isComplete ?? (moduleCount >= targetModuleCount && targetModuleCount > 0)
  if (complete) {
    const extra = moduleCount > targetModuleCount ? ` · 已保存 ${moduleCount} 张` : ''
    return `完整套图 · 目标 ${targetModuleCount}/${targetModuleCount}${extra}`
  }
  return `未完整 · 已保存 ${moduleCount} 张 / 目标 ${targetModuleCount}`
}

export function attachmentMaterialVersionLabel(version: AttachmentMaterialVersion) {
  const changed = version.changed_module_keys.map((key) => attachmentMaterialModuleLabels[key] || key)
  return `V${version.version_number}${changed.length ? ` · ${changed.join('、')}` : ''}`
}

export function materialVersionByNumber(versions: AttachmentMaterialVersion[], versionNumber: number | null) {
  return versions.find((item) => item.version_number === versionNumber) || versions[0] || null
}
