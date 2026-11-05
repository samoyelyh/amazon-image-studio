import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { createProject, listProjects, removeProject, saveProjectVersion, updateProject, type Project, type ProjectType } from '../lib/contentApi'
import { CloseIcon, PlusIcon } from '../components/icons'

const projectTypes: Array<[ProjectType, string]> = [['listing', 'Listing 图'], ['batch_tryon', '批量套图'], ['aplus', 'A+ 图']]

export default function ProjectsPage() {
  const queryClient = useQueryClient()
  const [type, setType] = useState<ProjectType | ''>('')
  const [name, setName] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draftText, setDraftText] = useState('{}')
  const [message, setMessage] = useState('')
  const [creating, setCreating] = useState(false)
  const projects = useQuery({ queryKey: ['projects', type], queryFn: () => listProjects(type || undefined) })
  const selected = projects.data?.items.find((item) => item.id === selectedId) ?? null
  useEffect(() => { if (selected) setDraftText(JSON.stringify(selected.latest_version.draft_json, null, 2)) }, [selected?.id, selected?.latest_version.version_number])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['projects'] })
  const create = useMutation({
    mutationFn: () => createProject({ project_type: type || 'listing', name, draft: {} }),
    onSuccess: (project) => { setName(''); setSelectedId(project.id); setMessage('项目已创建'); setCreating(false); refresh() },
    onError: (error) => setMessage(error instanceof Error ? error.message : '创建失败'),
  })
  const save = useMutation({
    mutationFn: ({ project, draft }: { project: Project; draft: Record<string, unknown> }) => saveProjectVersion(project.id, draft, project.latest_version.version_number, 'Workspace draft save'),
    onSuccess: () => { setMessage('草稿新版本已保存'); refresh() },
    onError: (error) => setMessage(error instanceof Error ? error.message : '保存失败'),
  })
  const archive = useMutation({ mutationFn: (project: Project) => updateProject(project.id, { status: project.status === 'draft' ? 'archived' : 'draft' }), onSuccess: () => refresh(), onError: (error) => setMessage(error instanceof Error ? error.message : '更新失败') })
  const remove = useMutation({ mutationFn: removeProject, onSuccess: () => { setSelectedId(null); setMessage('项目已删除，关联素材仍保留'); refresh() }, onError: (error) => setMessage(error instanceof Error ? error.message : '删除失败') })
  const submit = (event: FormEvent) => { event.preventDefault(); if (name.trim()) create.mutate() }
  const saveDraft = () => {
    if (!selected) return
    try {
      const draft = JSON.parse(draftText) as unknown
      if (!draft || Array.isArray(draft) || typeof draft !== 'object') throw new Error('invalid')
      save.mutate({ project: selected, draft: draft as Record<string, unknown> })
    } catch { setMessage('草稿必须是有效的 JSON 对象') }
  }

  return <div className="studio-page mx-auto max-w-[1500px]">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-medium tracking-[0.14em] text-gray-500">PROJECTS</p><h1 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-gray-950">项目与版本</h1><p className="mt-2 text-sm text-gray-500">集中管理创作项目、素材关联和不可变草稿版本。</p></div><button onClick={() => setCreating(!creating)} className="inline-flex min-h-10 items-center gap-2 rounded-full bg-stone-900 px-4 text-xs font-semibold text-white">{creating ? <CloseIcon className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}{creating ? '收起' : '新建项目'}</button></header>
    {creating && <form onSubmit={submit} className="mt-5 grid gap-3 rounded-2xl border border-black/[0.07] bg-white p-4 shadow-sm sm:grid-cols-[minmax(0,1fr)_220px_auto]"><input required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="项目名称" className="h-11 rounded-xl border border-black/10 bg-stone-50 px-3 text-sm outline-none focus:border-stone-400" /><select value={type} onChange={(event) => setType(event.target.value as ProjectType | '')} className="h-11 rounded-xl border border-black/10 bg-stone-50 px-3 text-sm"><option value="">Listing 图（默认）</option>{projectTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button disabled={create.isPending} className="rounded-xl bg-stone-900 px-5 text-sm font-semibold text-white disabled:opacity-50">创建项目</button></form>}
    <div className="mt-6 grid gap-5 xl:grid-cols-[330px_minmax(0,1fr)]">
      <aside className="overflow-hidden rounded-[20px] border border-black/[0.07] bg-white shadow-sm"><div className="border-b border-black/[0.06] p-4"><select aria-label="筛选项目类型" value={type} onChange={(event) => setType(event.target.value as ProjectType | '')} className="h-10 w-full rounded-xl border border-black/10 bg-stone-50 px-3 text-xs"><option value="">全部项目类型</option>{projectTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><div className="max-h-[620px] space-y-1 overflow-y-auto p-2">{projects.isLoading && <p className="p-4 text-sm text-gray-500">加载项目…</p>}{projects.data?.items.map((project) => <button key={project.id} onClick={() => setSelectedId(project.id)} className={`w-full rounded-xl border p-3 text-left transition ${selectedId === project.id ? 'border-stone-400 bg-stone-100' : 'border-transparent hover:bg-stone-50'}`}><div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium text-gray-900">{project.name}</span><span className="text-[10px] text-gray-400">v{project.latest_version.version_number}</span></div><p className="mt-1.5 text-[11px] text-gray-500">{projectTypes.find(([value]) => value === project.project_type)?.[1] || project.project_type} · {project.status === 'draft' ? '草稿' : '已归档'}</p></button>)}{!projects.isLoading && !projects.data?.items.length && <div className="py-12 text-center text-xs text-gray-500">暂无项目，点击右上角新建。</div>}</div></aside>
      <section className="overflow-hidden rounded-[20px] border border-black/[0.07] bg-white shadow-sm">
        {!selected ? <div className="flex min-h-[520px] flex-col items-center justify-center p-8 text-center"><div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-100 text-xl text-gray-400">＋</div><h2 className="mt-4 text-sm font-semibold text-gray-800">选择一个项目继续创作</h2><p className="mt-2 max-w-xs text-xs leading-5 text-gray-500">查看和编辑草稿内容，每次保存都会生成新的版本，不会覆盖历史记录。</p></div> : <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/[0.06] px-5 py-4"><div><div className="flex items-center gap-2"><h2 className="text-sm font-semibold text-gray-900">{selected.name}</h2><span className="rounded-full bg-stone-100 px-2 py-1 text-[10px] text-gray-500">v{selected.latest_version.version_number}</span></div><p className="mt-1 text-[11px] text-gray-500">保存将创建新版本，历史版本不会被覆盖。</p></div><div className="flex gap-2"><button onClick={() => archive.mutate(selected)} className="rounded-full border border-black/10 px-3 py-1.5 text-xs text-gray-600">{selected.status === 'draft' ? '归档' : '恢复'}</button><button onClick={() => { if (window.confirm('确认删除项目？关联素材不会被删除。')) remove.mutate(selected.id) }} className="rounded-full border border-red-200 px-3 py-1.5 text-xs text-red-600">删除</button></div></div>
          <div className="bg-stone-50 p-3 sm:p-4"><div className="mb-2 flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-stone-600"><span>项目草稿</span><span>当前内容可编辑，保存为新版本</span></div><textarea aria-label="项目草稿 JSON" value={draftText} onChange={(event) => setDraftText(event.target.value)} spellCheck={false} className="studio-input min-h-[320px] resize-y font-mono leading-6 lg:min-h-[460px]" /></div>
          <div className="flex flex-wrap items-center gap-3 border-t border-black/[0.06] px-5 py-4"><button onClick={saveDraft} disabled={save.isPending} className="rounded-full bg-stone-900 px-5 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{save.isPending ? '保存中…' : '保存为新版本'}</button>{message && <span className="text-xs text-gray-500">{message}</span>}</div>
        </>}
      </section>
    </div>
  </div>
}
