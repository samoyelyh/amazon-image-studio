import { useEffect, useState } from 'react'
import { authenticatedFetch } from '../../lib/authApi'
import type { AgentRun } from '../../lib/agentControlApi'

export interface CapabilityCatalog {
  catalog_version: string; dynamic_enabled: boolean
  skills: Array<{id:string;version:string;description:string}>
  tools: Array<{id:string;description:string;source:string;risk:string;ready:boolean;blocked_reason?:string|null}>
  mcp_servers: Array<{id:string;version:string;state:string;max_calls_per_run:number;timeout_seconds:number}>
}
export function AgentToolTrace({run}:{run:AgentRun}) {
  const events=run.events.filter(e=>e.type.startsWith('capabilit'))
  if(!events.length)return null
  return <details className="my-3 rounded-xl border border-gray-200 p-3 text-xs dark:border-white/10"><summary className="cursor-pointer text-gray-500">能力选择与执行记录 · {events.length} 条</summary>
    {events.map(e=><div key={e.id} className="mt-3 border-t border-gray-100 pt-2 dark:border-white/5"><p className="font-medium">{e.type}</p><pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words text-gray-500">{JSON.stringify(e.payload,null,2)}</pre></div>)}</details>
}
export default function AgentCapabilityPanel(){
  const [data,setData]=useState<CapabilityCatalog|null>(null),[error,setError]=useState('')
  useEffect(()=>{const controller=new AbortController();void authenticatedFetch<CapabilityCatalog>('/agent/capabilities',{signal:controller.signal}).then(v=>{if(!controller.signal.aborted)setData(v)}).catch(e=>{if(!controller.signal.aborted)setError(e instanceof Error?e.message:'能力目录读取失败')});return()=>controller.abort()},[])
  return <details className="mt-5 text-xs"><summary className="cursor-pointer">Skill / MCP 能力目录</summary>
    {error&&<p role="alert" className="mt-2 text-red-600">{error}</p>}
    {data&&<><p className="my-2 text-gray-500">{data.dynamic_enabled?'按需选择能力':'旧版执行模式'} · 只读工具可自主查询；写操作和费用单独确认。</p>
      <p className="mt-3 font-medium">Skill（正文按需加载）</p>{data.skills.map(s=><div key={s.id} className="my-2 rounded-lg border p-2 dark:border-white/10"><p>{s.id} · {s.version}</p><p className="mt-1 text-gray-500">{s.description}</p></div>)}
      <p className="mt-3 font-medium">获准工具</p>{data.tools.map(t=><p key={t.id} className="my-2 break-all"><span>{t.ready?'✓':'—'} {t.id}</span><span className="block text-gray-500">{t.description}{!t.ready&&` · ${t.blocked_reason||'未开放'}`}</span></p>)}
      <p className="mt-3 font-medium">MCP 服务</p>{!data.mcp_servers.length&&<p className="mt-2 text-gray-500">尚未登记获准 MCP，不会自动访问外部服务。</p>}{data.mcp_servers.map(s=><p key={s.id} className="mt-2">{s.id} · {s.version} · 待按需连接 · {s.timeout_seconds}秒 / 最多{s.max_calls_per_run}次</p>)}
      <p className="mt-3 text-gray-500">由管理员维护服务端审批清单。实际连接、认证、调用结果在本次任务记录中显示；目录不代表连接成功。</p></>}
  </details>
}
