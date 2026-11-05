import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AssetPreviewDialog from './AssetPreviewDialog'
import type {Asset} from '../lib/contentApi'

const asset={id:'asset',filename:'product.png',url:'/api/v1/assets/asset/content',width:2048,height:3072,size:1048576} as Asset
it('previews the actual asset dimensions, with accessible modal and real download action',()=>{
  const download=vi.fn()
  const html=renderToStaticMarkup(<AssetPreviewDialog asset={asset} canDelete={false} onClose={vi.fn()} onDownload={download} onDelete={vi.fn()}/>)
  expect(html).toContain('role="dialog"');expect(html).toContain('aria-modal="true"')
  expect(html).toContain('2048×3072');expect(html).toContain('下载图片');expect(html).toContain('product.png')
  expect(html).not.toContain('删除素材');expect(download).not.toHaveBeenCalled()
})
it('only exposes delete when the caller has permission',()=>{
  const html=renderToStaticMarkup(<AssetPreviewDialog asset={asset} canDelete onClose={vi.fn()} onDownload={vi.fn()} onDelete={vi.fn()}/>)
  expect(html).toContain('删除素材')
})
