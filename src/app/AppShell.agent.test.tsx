import { expect,it,vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import AppShell from './AppShell'
vi.mock('./AuthContext',()=>({useAuth:()=>({hasPermission:()=>true})}))
it('gives the agent a full-width viewport while retaining mobile navigation',()=>{
  const html=renderToStaticMarkup(<MemoryRouter initialEntries={['/workspaces/agent-control']}><AppShell/></MemoryRouter>)
  expect(html).toContain('h-dvh flex-col overflow-hidden')
  expect(html).toContain('max-w-none flex-1 items-stretch')
  expect(html).toContain('移动端主导航')
})
it('does not apply the chat viewport lock to the professional workbench',()=>{
  const html=renderToStaticMarkup(<MemoryRouter initialEntries={['/workspaces/batch-tryon']}><AppShell/></MemoryRouter>)
  expect(html).not.toContain('h-dvh flex-col overflow-hidden')
  expect(html).toContain('min-h-screen')
})
