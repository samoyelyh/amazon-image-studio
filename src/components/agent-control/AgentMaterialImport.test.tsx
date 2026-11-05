import {expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import AgentMaterialImport from './AgentMaterialImport'

it('renders separate role-scoped template and garment cards with all three file pickers',()=>{
 const html=renderToStaticMarkup(<AgentMaterialImport variant="cards" onImport={vi.fn()}/>)
 expect(html).toContain('上传模板图卡片')
 expect(html).toContain('上传服装卡片')
 for(const title of ['上传模板图','上传服装']){
  expect(html).toContain(`aria-label="${title}图片文件"`)
  expect(html).toContain(`aria-label="${title}文件夹"`)
  expect(html).toContain(`aria-label="${title}ZIP压缩包"`)
 }
 expect(html).toContain('data-import-source="template"')
 expect(html).toContain('data-import-source="garment"')
 expect(html).toContain('<details')
 expect(html).toContain('混合素材：自动识别')
 expect(html).toContain('sm:grid-cols-2')
})

it('disables every picker while another import is transferring',()=>{
 const html=renderToStaticMarkup(<AgentMaterialImport variant="cards" disabled onImport={vi.fn()}/>)
 expect(html.match(/<input[^>]*disabled=""/g)).toHaveLength(9)
 expect(html.match(/<button[^>]*disabled=""/g)).toHaveLength(9)
})

it('retains compact source-specific entrances without a generic combined upload',()=>{
 const html=renderToStaticMarkup(<AgentMaterialImport onImport={vi.fn()}/>)
 expect(html).toContain('导入模板</button>')
 expect(html).toContain('导入服装</button>')
 expect(html).toContain('自动识别</button>')
 expect(html).not.toContain('上传模板与服装</button>')
})
