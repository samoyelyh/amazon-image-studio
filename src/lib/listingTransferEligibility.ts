import type { TaskRecord } from '../types'


export interface ListingTransferAccess {
  isStandalone: boolean
  canReadGeneratedOutputs: boolean
  canWriteProjects: boolean
}


export function isListingTransferTask(task: TaskRecord): boolean {
  return task.serverWorkspaceType === 'listing' || task.category?.workflow === 'amazon-listing'
}


export function listingTransferDisabledReason(task: TaskRecord, access: ListingTransferAccess): string {
  if (access.isStandalone) return '仅多人模式下可直接发送服务端生成结果'
  if (task.status !== 'done') return task.status === 'running' ? '图片仍在生成中' : '生成失败的结果不能发送'
  if (!task.outputImages[0]) return '当前任务没有生成图片'
  if (!task.serverJobId || !task.serverOutputAssetIds?.[0]) return '当前图片没有完整的服务端 Asset 记录'
  if (!access.canReadGeneratedOutputs) return '没有读取 Listing 生成结果的权限'
  if (!access.canWriteProjects) return '没有创建或编辑批量套图项目的权限'
  return ''
}
