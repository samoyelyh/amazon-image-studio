// @ts-expect-error Vitest runs in Node; browser typings intentionally exclude Node.
import {readFileSync} from 'node:fs'
import {expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {ResponsiveToolsPanel,StudioButton,StudioEmptyState} from './Studio'

it('controls do not submit forms accidentally and expose disabled semantics',()=>{
  const html=renderToStaticMarkup(<StudioButton variant="primary" disabled>开始</StudioButton>)
  expect(html).toContain('type="button"');expect(html).toContain('disabled=""');expect(html).toContain('data-variant="primary"')
})
it('collapsed tools keep their upload controls and edits mounted',()=>{
  const html=renderToStaticMarkup(<ResponsiveToolsPanel title="参考设置"><input type="file"/><textarea defaultValue="已编辑内容"/></ResponsiveToolsPanel>)
  expect(html).toContain('<summary>参考设置</summary>');expect(html).toContain('type="file"');expect(html).toContain('已编辑内容')
  expect(renderToStaticMarkup(<StudioEmptyState>暂无结果</StudioEmptyState>)).toContain('role="status"')
})
it('shared light tokens retain readable text, selected controls and error/warning contrast',()=>{
  const css=readFileSync(new URL('../../styles/design-system.css',import.meta.url),'utf8')
  const color=(name:string)=>css.match(new RegExp(`--studio-${name}:\\s*(#[a-f0-9]{6})`))![1]
  const luminance=(hex:string)=>hex.slice(1).match(/../g)!.map(n=>parseInt(n,16)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4).reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0)
  const contrast=(a:string,b:string)=>{const x=luminance(color(a)),y=luminance(color(b));return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
  for(const [text,bg] of [['ink','canvas'],['muted','surface'],['on-accent','accent'],['on-accent','accent-hover'],['muted','raised'],['danger','danger-bg'],['warning','warning-bg'],['success','success-bg']])expect(contrast(text,bg)).toBeGreaterThanOrEqual(4.5)
  expect(css).toContain('color-scheme: light');expect(css).toContain(':focus-visible')
})
