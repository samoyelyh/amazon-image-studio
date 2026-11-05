// @ts-expect-error Vitest runs in Node; browser typings intentionally exclude Node.
import {existsSync} from 'node:fs'
import {expect,it} from 'vitest'
import {submitCreativeTool,type CreativeToolCapability} from './creativeToolApi'
import {inspirationAsset,inspirationItems} from './creationInspiration'

it.each(['material_extract','mask_edit','product_mockup','image_outpaint','image_upscale','video_extend'] as CreativeToolCapability[])('unconnected %s never returns a fake task receipt',async capability=>{
  await expect(submitCreativeTool({capability,fileName:'reference.png',instruction:'测试'})).rejects.toThrow('接口尚未接入')
})
it('inspiration remains separate from local creative image assets, without external hotlinks',()=>{
  for(const item of inspirationItems){
    expect(item.path.startsWith('creative-assets/')||item.path.startsWith('style-presets/')).toBe(true)
    expect(inspirationAsset(item.path)).not.toMatch(/^https?:/)
    expect(existsSync(new URL(`../../public/${item.path}`,import.meta.url))).toBe(true)
  }
})
