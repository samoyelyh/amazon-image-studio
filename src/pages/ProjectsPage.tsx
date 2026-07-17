import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { createProject, listProjects, removeProject, saveProjectVersion, updateProject, type Project, type ProjectType } from '../lib/contentApi'

const projectTypes: Array<[ProjectType, string]> = [['listing', 'Listing 图'], ['batch_tryon', '批量套图'], ['aplus', 'A+ 图']]

export default function ProjectsPage() {
  const queryClient = useQueryClient()
  const [type, setType] = useState<ProjectType | ''>('')
  const [name, setName] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draftText, setDraftText] = useState('{}')
  const [message, setMessage] = useState('')
  const projects = useQuery({ queryKey: ['projects', type], queryFn: () => listProjects(type || undefined) })
  const selected = projects.data?.items.find((item) => item.id === selectedId) ?? null
  useEffect(() => { if (selected) setDraftText(JSON.stringify(selected.latest_version.draft_json, null, 2)) }, [selected?.id, selected?.latest_version.version_number])
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['projects'] })
  const create = useMutation({
    mutationFn: () => createProject({ project_type: type || 'listing', name, draft: {} }),
    onSuccess: (project) => { setName(''); setSelectedId(project.id); setMessage('项目已创建'); refresh() },
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

  return (
    <div className="mt-6 grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <aside className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">项目系统</h1><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">统一管理三个工作台的草稿与素材关联。</p>
        <form onSubmit={submit} className="mt-5 space-y-3"><input required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="新项目名称" className="w-full rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" /><select value={type} onChange={(event) => setType(event.target.value as ProjectType | '')} className="w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"><option value="">Listing 图（默认）</option>{projectTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button disabled={create.isPending} className="w-full rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">创建项目</button></form>
        <div className="mt-5 space-y-2">{projects.isLoading && <div className="text-sm text-gray-500">加载项目…</div>}{projects.data?.items.map((project) => <button key={project.id} onClick={() => setSelectedId(project.id)} className={`w-full rounded-xl border p-3 text-left ${selectedId === project.id ? 'border-blue-500 bg-blue-50 dark:bg-blue-500/10' : 'border-gray-200 dark:border-white/[0.08]'}`}><div className="truncate text-sm font-semibold text-gray-900 dark:text-white">{project.name}</div><div className="mt-1 text-xs text-gray-500">{projectTypes.find(([value]) => value === project.project_type)?.[1]} · v{project.latest_version.version_number} · {project.status === 'draft' ? '草稿' : '已归档'}</div></button>)}{!projects.isLoading && !projects.data?.items.length && <div className="rounded-xl border border-dashed border-gray-200 py-8 text-center text-sm text-gray-500 dark:border-white/[0.08]">暂无项目</div>}</div>
      </aside>
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        {!selected ? <div className="flex min-h-80 items-center justify-center text-sm text-gray-500">选择项目后编辑草稿</div> : <><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-bold text-gray-950 dark:text-white">{selected.name}</h2><p className="mt-1 text-xs text-gray-500">当前版本 v{selected.latest_version.version_number}；保存会创建新版本，不覆盖旧数据。</p></div><div className="flex gap-2"><button onClick={() => archive.mutate(selected)} className="rounded-xl border border-gray-200 px-3 py-2 text-xs font-semibold dark:border-white/[0.1] dark:text-gray-200">{selected.status === 'draft' ? '归档' : '恢复'}</button><button onClick={() => { if (window.confirm('确认删除项目？关联素材不会被删除。')) remove.mutate(selected.id) }} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-semibold text-red-600">删除</button></div></div><textarea value={draftText} onChange={(event) => setDraftText(event.target.value)} spellCheck={false} className="mt-5 min-h-[420px] w-full rounded-xl border border-gray-200 bg-gray-950 p-4 font-mono text-sm leading-6 text-gray-100 outline-none focus:border-blue-500 dark:border-white/[0.1]" /><div className="mt-3 flex items-center gap-3"><button onClick={saveDraft} disabled={save.isPending} className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">{save.isPending ? '保存中…' : '保存为新版本'}</button>{message && <span className="text-sm text-gray-500 dark:text-gray-300">{message}</span>}</div></>}
      </section>
    </div>
  )
}
