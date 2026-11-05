export type CreativeToolCapability = 'material_extract' | 'mask_edit' | 'product_mockup' | 'image_outpaint' | 'image_upscale' | 'video_extend'

export interface CreativeToolRequest {
  capability: CreativeToolCapability
  fileName: string
  instruction: string
}

export interface CreativeToolReceipt {
  taskId: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  workspaceUrl: string | null
}

export async function submitCreativeTool(request: CreativeToolRequest): Promise<CreativeToolReceipt> {
  throw new Error(`${request.capability} 工具接口尚未接入，当前仅保存了页面输入。`)
}
