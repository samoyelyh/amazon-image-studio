import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useAuth } from '../app/AuthContext'
import UserManagementPanel from '../components/admin/UserManagementPanel'
import CategoryListingManagementPanel from '../components/admin/CategoryListingManagementPanel'
import CreativePresetManagementPanel from '../components/admin/CreativePresetManagementPanel'
import AttachmentReferenceLibraryManagementPanel from '../components/admin/AttachmentReferenceLibraryManagementPanel'
import {
  adjustAdminQuota,
  attachApiKey,
  createAdminOrganization,
  createApiKey,
  createProvider,
  createProviderModel,
  createResourcePool,
  getAdminAudits,
  getAdminJobs,
  getAdminLoginAudits,
  getAdminOrganizations,
  getAdminOverview,
  getAdminQueues,
  getAdminResources,
  getGenerationResourceDiagnostics,
  testAdminProvider,
  toggleAdminResource,
  updateAdminOrganization,
  type AdminOrganization,
  type AdminProviderTest,
  type AdminResources,
} from '../lib/adminApi'
import { randomUuid } from '../lib/randomUuid'
import { formatDuration } from '../lib/taskDuration'

type Tab = 'overview' | 'users' | 'organizations' | 'categories' | 'creative' | 'reference-library' | 'resources' | 'diagnostics' | 'tasks' | 'audits'

const tabs: Array<{ id: Tab; label: string }> = [
  { id: 'overview', label: '总览' },
  { id: 'users', label: '用户' },
  { id: 'organizations', label: '团队与额度' },
  { id: 'categories', label: '品类与 Skill' },
  { id: 'creative', label: 'AI生图配置' },
  { id: 'reference-library', label: '参考图库' },
  { id: 'resources', label: 'API 与资源池' },
  { id: 'diagnostics', label: '生成资源诊断' },
  { id: 'tasks', label: '队列与任务' },
  { id: 'audits', label: '系统日志' },
]

const panelClass = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const inputClass = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const primaryButton = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50'
const secondaryButton = 'rounded-xl border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50 disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.05]'

function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
function number(value: number) { return new Intl.NumberFormat('zh-CN').format(value) }

function useCurrentTime() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => window.clearInterval(timer)
  }, [])
  return now
}

function countdown(until: string | null, now: number) {
  if (!until) return '—'
  const seconds = Math.max(0, Math.ceil((new Date(until).getTime() - now) / 1_000))
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes > 0 ? `${minutes}分${String(remainder).padStart(2, '0')}秒` : `${remainder}秒`
}

const recoveryLabels = {
  healthy: '健康',
  cooling: '冷却中',
  waiting_probe: '等待探测',
  probing: '探测中',
  disabled: '已停用',
} as const

function RecoveryBadge({ state }: { state: keyof typeof recoveryLabels }) {
  const classes = {
    healthy: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200',
    cooling: 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-200',
    waiting_probe: 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-200',
    probing: 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-200',
    disabled: 'bg-gray-100 text-gray-600 dark:bg-white/[0.08] dark:text-gray-300',
  } as const
  return <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${classes[state]}`}>{recoveryLabels[state]}</span>
}
function errorMessage(error: unknown) { return error instanceof Error ? error.message : '操作失败，请稍后重试' }

function Section({ title, description, children, action }: { title: string; description?: string; children: ReactNode; action?: ReactNode }) {
  return <section className={panelClass}>
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-white/[0.06]">
      <div><h2 className="font-bold text-gray-950 dark:text-white">{title}</h2>{description && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>}</div>
      {action}
    </div>
    <div className="p-5">{children}</div>
  </section>
}

function StatusPill({ active, children }: { active: boolean; children: ReactNode }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${active ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-gray-100 text-gray-600 dark:bg-white/[0.08] dark:text-gray-300'}`}>{children}</span>
}

function LoadingOrError({ loading, error }: { loading: boolean; error: Error | null }) {
  if (loading) return <div className="py-10 text-center text-sm text-gray-500">正在加载…</div>
  if (error) return <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{error.message}</div>
  return null
}

function OverviewTab() {
  const overview = useQuery({ queryKey: ['admin', 'overview'], queryFn: getAdminOverview, refetchInterval: 15_000 })
  if (!overview.data) return <LoadingOrError loading={overview.isLoading} error={overview.error} />
  const cards = [
    ['用户', overview.data.users_active, `${overview.data.users_total} 个账号`],
    ['团队', overview.data.organizations_active, `${overview.data.organizations_total} 个团队`],
    ['运行中任务', overview.data.jobs_active, `${overview.data.jobs_total} 个任务`],
    ['失败任务', overview.data.jobs_failed, `${overview.data.jobs_succeeded} 个成功`],
    ['可用额度', overview.data.quota_balance_total - overview.data.quota_reserved_total, `冻结 ${number(overview.data.quota_reserved_total)}`],
    ['可用资源', overview.data.keys_enabled, `${overview.data.providers_enabled} Provider · ${overview.data.pools_enabled} 池`],
  ]
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
    {cards.map(([label, value, detail]) => <div key={String(label)} className={`${panelClass} p-5`}><div className="text-xs font-medium text-gray-500">{label}</div><div className="mt-2 text-3xl font-bold text-gray-950 dark:text-white">{number(Number(value))}</div><div className="mt-2 text-xs text-gray-500">{detail}</div></div>)}
  </div>
}

function UsersTab({ notify }: { notify: (message: string) => void }) {
  const auth = useAuth()
  return <UserManagementPanel notify={notify} platformAdmin={auth.hasPermission('platform.admin')} />
}

function OrganizationsTab({ notify }: { notify: (message: string) => void }) {
  const queryClient = useQueryClient()
  const organizations = useQuery({ queryKey: ['admin', 'organizations'], queryFn: getAdminOrganizations })
  const [newOrganization, setNewOrganization] = useState({ name: '', slug: '' })
  const [adjustments, setAdjustments] = useState<Record<string, { amount: number; reason: string }>>({})
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin'] })
  const createMutation = useMutation({ mutationFn: createAdminOrganization, onSuccess: () => { setNewOrganization({ name: '', slug: '' }); notify('团队已创建'); refresh() }, onError: (error) => notify(errorMessage(error)) })
  const updateMutation = useMutation({ mutationFn: ({ id, status }: { id: string; status: 'active' | 'disabled' }) => updateAdminOrganization(id, { status }), onSuccess: () => { notify('团队状态已更新'); refresh() }, onError: (error) => notify(errorMessage(error)) })
  const quotaMutation = useMutation({ mutationFn: ({ id, amount, reason }: { id: string; amount: number; reason: string }) => adjustAdminQuota(id, { transaction_type: 'adjust', amount, reason, idempotency_key: `admin:${randomUuid()}` }), onSuccess: () => { notify('团队额度已调整'); refresh() }, onError: (error) => notify(errorMessage(error)) })
  const submitCreate = (event: FormEvent) => { event.preventDefault(); createMutation.mutate(newOrganization) }
  return <div className="space-y-5">
    <Section title="新建团队" description="创建后会自动建立独立额度账户，数据和任务按团队隔离。"><form onSubmit={submitCreate} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"><input className={inputClass} placeholder="团队名称" value={newOrganization.name} onChange={(event) => setNewOrganization((value) => ({ ...value, name: event.target.value }))} /><input className={inputClass} placeholder="唯一标识，例如 studio-a" value={newOrganization.slug} onChange={(event) => setNewOrganization((value) => ({ ...value, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') }))} /><button className={primaryButton} disabled={!newOrganization.name.trim() || !newOrganization.slug.trim() || createMutation.isPending}>创建团队</button></form></Section>
    <Section title="团队与额度" description="正数增加额度，负数扣减额度；所有调整都会写入统一额度流水和审计日志。">
      {!organizations.data ? <LoadingOrError loading={organizations.isLoading} error={organizations.error} /> : <div className="space-y-3">{organizations.data.items.map((organization) => { const adjustment = adjustments[organization.id] ?? { amount: 1000, reason: '管理员额度调整' }; return <div key={organization.id} className="rounded-2xl border border-gray-200 p-4 dark:border-white/[0.08]"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="font-semibold text-gray-950 dark:text-white">{organization.name}</span><StatusPill active={organization.status === 'active'}>{organization.status === 'active' ? '启用' : '停用'}</StatusPill></div><div className="mt-1 text-xs text-gray-500">{organization.slug} · {organization.member_count} 名成员 · {organization.active_job_count}/{organization.job_count} 个活跃/总任务</div></div><button className={secondaryButton} disabled={updateMutation.isPending} onClick={() => updateMutation.mutate({ id: organization.id, status: organization.status === 'active' ? 'disabled' : 'active' })}>{organization.status === 'active' ? '停用团队' : '恢复团队'}</button></div><div className="mt-4 grid gap-3 lg:grid-cols-[180px_180px_minmax(220px,1fr)_auto]"><div className="rounded-xl bg-gray-50 px-3 py-2 dark:bg-gray-950"><div className="text-xs text-gray-500">可用 / 冻结</div><div className="mt-1 text-sm font-bold dark:text-white">{number(organization.quota_balance - organization.quota_reserved)} / {number(organization.quota_reserved)}</div></div><input type="number" className={inputClass} aria-label={`${organization.name}额度`} value={adjustment.amount} onChange={(event) => setAdjustments((values) => ({ ...values, [organization.id]: { ...adjustment, amount: Number(event.target.value) } }))} /><input className={inputClass} aria-label={`${organization.name}原因`} value={adjustment.reason} onChange={(event) => setAdjustments((values) => ({ ...values, [organization.id]: { ...adjustment, reason: event.target.value } }))} /><button className={primaryButton} disabled={!adjustment.amount || !adjustment.reason.trim() || quotaMutation.isPending} onClick={() => quotaMutation.mutate({ id: organization.id, ...adjustment })}>调整额度</button></div></div> })}</div>}
    </Section>
  </div>
}

function ResourceForms({ resources, organizations, notify }: { resources: AdminResources; organizations: AdminOrganization[]; notify: (message: string) => void }) {
  const queryClient = useQueryClient()
  const [provider, setProvider] = useState({ code: '', name: '', provider_type: 'openai_compatible', base_url: '' })
  const [model, setModel] = useState({ provider_id: resources.providers[0]?.id ?? '', code: '', upstream_model: '', name: '', capabilities: 'image_generation,image_edit' })
  const [pool, setPool] = useState({ model_id: resources.models[0]?.id ?? '', code: '', name: '', organization_id: '', priority: 100, weight: 100 })
  const [key, setKey] = useState({ provider_id: resources.providers[0]?.id ?? '', label: '', secret: '', organization_id: '', max_concurrency: 2, rpm_limit: '', daily_limit: '' })
  const [keyEntryUnlocked, setKeyEntryUnlocked] = useState(false)
  const [attachment, setAttachment] = useState({ pool_id: resources.pools[0]?.id ?? '', api_key_id: resources.keys[0]?.id ?? '' })
  useEffect(() => {
    if (keyEntryUnlocked) return
    const clearCredentialAutofill = () => setKey((value) => ({ ...value, label: '', secret: '' }))
    const timers = [0, 100, 500, 1000, 2000].map((delay) => window.setTimeout(clearCredentialAutofill, delay))
    return () => timers.forEach(window.clearTimeout)
  }, [keyEntryUnlocked])
  const unlockKeyEntry = () => {
    setKey((value) => ({ ...value, label: '', secret: '' }))
    setKeyEntryUnlocked(true)
  }
  const success = (message: string) => { notify(message); queryClient.invalidateQueries({ queryKey: ['admin', 'resources'] }); queryClient.invalidateQueries({ queryKey: ['admin', 'overview'] }) }
  const providerMutation = useMutation({ mutationFn: () => createProvider({ ...provider, config: {} }), onSuccess: () => { setProvider({ code: '', name: '', provider_type: 'openai_compatible', base_url: '' }); success('Provider 已创建') }, onError: (error) => notify(errorMessage(error)) })
  const modelMutation = useMutation({ mutationFn: () => createProviderModel(model.provider_id, { code: model.code, upstream_model: model.upstream_model, name: model.name, capabilities: model.capabilities.split(',').map((item) => item.trim()).filter(Boolean), config: {} }), onSuccess: () => { setModel((value) => ({ ...value, code: '', upstream_model: '', name: '' })); success('模型已创建') }, onError: (error) => notify(errorMessage(error)) })
  const poolMutation = useMutation({ mutationFn: () => createResourcePool({ ...pool, organization_id: pool.organization_id || undefined }), onSuccess: () => { setPool((value) => ({ ...value, code: '', name: '' })); success('资源池已创建') }, onError: (error) => notify(errorMessage(error)) })
  const keyMutation = useMutation({ mutationFn: () => createApiKey({ provider_id: key.provider_id, label: key.label, secret: key.secret, organization_id: key.organization_id || undefined, max_concurrency: key.max_concurrency, rpm_limit: key.rpm_limit ? Number(key.rpm_limit) : undefined, daily_limit: key.daily_limit ? Number(key.daily_limit) : undefined }), onSuccess: () => { setKey((value) => ({ ...value, label: '', secret: '' })); setKeyEntryUnlocked(false); success('API Key 已加密保存') }, onError: (error) => notify(errorMessage(error)) })
  const attachMutation = useMutation({ mutationFn: () => attachApiKey(attachment.pool_id, attachment.api_key_id), onSuccess: () => success('API Key 已绑定到资源池'), onError: (error) => notify(errorMessage(error)) })
  const organizationOptions = <><option value="">平台共享资源</option>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</>
  return <div className="grid gap-5 xl:grid-cols-2">
    <Section title="1. 添加 Provider" description="中转站通常选择 OpenAI Compatible，并填写它的 API Base URL。"><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); providerMutation.mutate() }}><div className="grid gap-3 sm:grid-cols-2"><input className={inputClass} placeholder="唯一编码，例如 relay-main" value={provider.code} onChange={(event) => setProvider((value) => ({ ...value, code: event.target.value }))} /><input className={inputClass} placeholder="显示名称" value={provider.name} onChange={(event) => setProvider((value) => ({ ...value, name: event.target.value }))} /></div><select className={inputClass} value={provider.provider_type} onChange={(event) => setProvider((value) => ({ ...value, provider_type: event.target.value }))}><option value="openai_compatible">OpenAI Compatible</option><option value="new_api">New API 中转站</option><option value="custom">自定义适配器</option></select><input className={inputClass} placeholder="https://relay.example.com/v1" value={provider.base_url} onChange={(event) => setProvider((value) => ({ ...value, base_url: event.target.value }))} /><button className={primaryButton} disabled={!provider.code || !provider.name || !provider.base_url || providerMutation.isPending}>保存 Provider</button></form></Section>
    <Section title="2. 添加模型" description="上游模型名必须与中转站实际支持的 model 参数一致。"><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); modelMutation.mutate() }}><select className={inputClass} value={model.provider_id} onChange={(event) => setModel((value) => ({ ...value, provider_id: event.target.value }))}><option value="">选择 Provider</option>{resources.providers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><div className="grid gap-3 sm:grid-cols-2"><input className={inputClass} placeholder="内部模型编码" value={model.code} onChange={(event) => setModel((value) => ({ ...value, code: event.target.value }))} /><input className={inputClass} placeholder="上游 model，例如 gpt-image-1" value={model.upstream_model} onChange={(event) => setModel((value) => ({ ...value, upstream_model: event.target.value }))} /></div><input className={inputClass} placeholder="显示名称" value={model.name} onChange={(event) => setModel((value) => ({ ...value, name: event.target.value }))} /><input className={inputClass} placeholder="能力，逗号分隔" value={model.capabilities} onChange={(event) => setModel((value) => ({ ...value, capabilities: event.target.value }))} /><button className={primaryButton} disabled={!model.provider_id || !model.code || !model.upstream_model || !model.name || modelMutation.isPending}>保存模型</button></form></Section>
    <Section title="3. 创建资源池" description="资源池决定任务可使用的模型和 Key；留空团队表示平台共享池。"><form className="grid gap-3" onSubmit={(event) => { event.preventDefault(); poolMutation.mutate() }}><select className={inputClass} value={pool.model_id} onChange={(event) => setPool((value) => ({ ...value, model_id: event.target.value }))}><option value="">选择模型</option>{resources.models.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select><div className="grid gap-3 sm:grid-cols-2"><input className={inputClass} placeholder="资源池编码" value={pool.code} onChange={(event) => setPool((value) => ({ ...value, code: event.target.value }))} /><input className={inputClass} placeholder="资源池名称" value={pool.name} onChange={(event) => setPool((value) => ({ ...value, name: event.target.value }))} /></div><select className={inputClass} value={pool.organization_id} onChange={(event) => setPool((value) => ({ ...value, organization_id: event.target.value }))}>{organizationOptions}</select><div className="grid gap-3 sm:grid-cols-2"><input type="number" className={inputClass} aria-label="资源池优先级" value={pool.priority} onChange={(event) => setPool((value) => ({ ...value, priority: Number(event.target.value) }))} /><input type="number" className={inputClass} aria-label="资源池权重" value={pool.weight} onChange={(event) => setPool((value) => ({ ...value, weight: Number(event.target.value) }))} /></div><button className={primaryButton} disabled={!pool.model_id || !pool.code || !pool.name || poolMutation.isPending}>创建资源池</button></form></Section>
    <Section title="4. 保存 API Key" description="Key 只在此处提交一次，服务端加密存储，之后页面仅显示掩码。"><form autoComplete="off" data-form-type="other" className="grid gap-3" onSubmit={(event) => { event.preventDefault(); keyMutation.mutate() }}><select className={inputClass} value={key.provider_id} onChange={(event) => setKey((value) => ({ ...value, provider_id: event.target.value }))}><option value="">选择 Provider</option>{resources.providers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><select className={inputClass} value={key.organization_id} onChange={(event) => setKey((value) => ({ ...value, organization_id: event.target.value }))}>{organizationOptions}</select><input readOnly={!keyEntryUnlocked} onFocus={unlockKeyEntry} name="provider-api-key-label" autoComplete="off" data-1p-ignore="true" data-lpignore="true" className={inputClass} placeholder="Key 标签，例如 主账号" value={key.label} onChange={(event) => setKey((value) => ({ ...value, label: event.target.value }))} /><textarea readOnly={!keyEntryUnlocked} onFocus={unlockKeyEntry} rows={1} name="provider-secret-value" autoComplete="off" data-1p-ignore="true" data-lpignore="true" data-form-type="other" spellCheck={false} className={`${inputClass} resize-none overflow-hidden [-webkit-text-security:disc]`} placeholder="sk-…" value={key.secret} onChange={(event) => setKey((value) => ({ ...value, secret: event.target.value.replace(/[\r\n]/g, '') }))} /><div className="grid gap-3 sm:grid-cols-3"><input type="number" min={1} className={inputClass} aria-label="最大并发" placeholder="最大并发" value={key.max_concurrency} onChange={(event) => setKey((value) => ({ ...value, max_concurrency: Number(event.target.value) }))} /><input type="number" className={inputClass} placeholder="每分钟限制" value={key.rpm_limit} onChange={(event) => setKey((value) => ({ ...value, rpm_limit: event.target.value }))} /><input type="number" className={inputClass} placeholder="每日限制" value={key.daily_limit} onChange={(event) => setKey((value) => ({ ...value, daily_limit: event.target.value }))} /></div><button className={primaryButton} disabled={!key.provider_id || !key.label || !key.secret.startsWith('sk-') || keyMutation.isPending}>加密保存 Key</button></form></Section>
    <div className="xl:col-span-2"><Section title="5. 绑定 Key 到资源池" description="只有 Provider 匹配的 Key 才能绑定；服务端会再次校验。"><form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" onSubmit={(event) => { event.preventDefault(); attachMutation.mutate() }}><select className={inputClass} value={attachment.pool_id} onChange={(event) => setAttachment((value) => ({ ...value, pool_id: event.target.value }))}><option value="">选择资源池</option>{resources.pools.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.model_code}</option>)}</select><select className={inputClass} value={attachment.api_key_id} onChange={(event) => setAttachment((value) => ({ ...value, api_key_id: event.target.value }))}><option value="">选择 API Key</option>{resources.keys.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.masked_secret}</option>)}</select><button className={primaryButton} disabled={!attachment.pool_id || !attachment.api_key_id || attachMutation.isPending}>绑定</button></form></Section></div>
  </div>
}

function providerTestLabel(testType: AdminProviderTest['test_type']) {
  return ({
    base: '基础连接测试',
    text_generation: '文本模型测试',
    image_generation: '图片生成测试',
    image_edit: '图片编辑测试',
    multi_image_reference: '多参考图测试',
  } as const)[testType]
}

function ProviderTestResult({ result }: { result: AdminProviderTest }) {
  return <div className={`mt-2 rounded-lg px-3 py-2 text-xs ${result.success ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300' : 'bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300'}`}><div className="font-semibold">{providerTestLabel(result.test_type)}：{result.message}</div>{result.models.length > 0 && <div className="mt-1 break-words">模型：{result.models.join('、')}</div>}{result.error_code && <div className="mt-1">{result.error_code}{result.status_code ? ` · HTTP ${result.status_code}` : ''}</div>}</div>
}

function ResourcesTab({ notify }: { notify: (message: string) => void }) {
  const queryClient = useQueryClient()
  const resources = useQuery({ queryKey: ['admin', 'resources'], queryFn: getAdminResources })
  const organizations = useQuery({ queryKey: ['admin', 'organizations'], queryFn: getAdminOrganizations })
  const [providerTests, setProviderTests] = useState<Record<string, AdminProviderTest>>({})
  const testProvider = useMutation({
    mutationFn: ({ providerId, testType, modelId }: { providerId: string; testType: AdminProviderTest['test_type']; modelId?: string }) => testAdminProvider(providerId, testType, modelId),
    onSuccess: (result) => { setProviderTests((items) => ({ ...items, [`${result.provider_id}:${result.model_id ?? 'base'}:${result.test_type}`]: result })); notify(result.message) },
    onError: (error) => notify(errorMessage(error)),
  })
  const toggle = useMutation({ mutationFn: ({ type, id, enabled }: { type: 'providers' | 'models' | 'resource-pools' | 'api-keys'; id: string; enabled: boolean }) => toggleAdminResource(type, id, enabled), onSuccess: () => { notify('资源状态已更新'); queryClient.invalidateQueries({ queryKey: ['admin'] }) }, onError: (error) => notify(errorMessage(error)) })
  if (!resources.data || !organizations.data) return <LoadingOrError loading={resources.isLoading || organizations.isLoading} error={resources.error ?? organizations.error} />
  return <div className="space-y-5"><ResourceForms resources={resources.data} organizations={organizations.data.items} notify={notify} /><Section title="资源清单" description="关闭 Provider、模型、池或 Key 后，新任务不会再选择该资源。API Key 原文不会返回前端。"><div className="grid gap-4 xl:grid-cols-2">
    <div>
      <h3 className="mb-2 text-sm font-bold dark:text-white">Provider 与模型</h3>
      <div className="space-y-2">{resources.data.providers.map((provider) => {
        const baseResult = providerTests[`${provider.id}:base:base`]
        return <div key={provider.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]">
          <div className="flex justify-between gap-3"><div><div className="text-sm font-semibold dark:text-white">{provider.name}</div><div className="mt-1 break-all text-xs text-gray-500">{provider.code} · {provider.base_url}</div></div><div className="flex gap-2"><button className={secondaryButton} disabled={testProvider.isPending} onClick={() => testProvider.mutate({ providerId: provider.id, testType: 'base' })}>基础连接测试</button><button className={secondaryButton} onClick={() => toggle.mutate({ type: 'providers', id: provider.id, enabled: !provider.enabled })}>{provider.enabled ? '停用' : '启用'}</button></div></div>
          {baseResult && <ProviderTestResult result={baseResult} />}
          <div className="mt-3 space-y-2">{resources.data.models.filter((model) => model.provider_id === provider.id).map((model) => {
            const testTypes = model.capabilities.filter((item): item is AdminProviderTest['test_type'] => ['text_generation', 'image_generation', 'image_edit', 'multi_image_reference'].includes(item))
            return <div key={model.id} className="rounded-lg bg-gray-50 p-2 text-xs dark:bg-gray-950"><div className="flex items-start justify-between gap-3"><div><div className="font-semibold dark:text-white">{model.name} · {model.upstream_model}</div><div className="mt-1 text-gray-500">{model.capabilities.join('、') || '未声明能力'}</div></div><button className={secondaryButton} onClick={() => toggle.mutate({ type: 'models', id: model.id, enabled: !model.enabled })}>{model.enabled ? '停用' : '启用'}</button></div><div className="mt-2 flex flex-wrap gap-2">{testTypes.map((testType) => <button key={testType} className={secondaryButton} disabled={testProvider.isPending} onClick={() => testProvider.mutate({ providerId: provider.id, testType, modelId: model.id })}>{providerTestLabel(testType)}</button>)}</div>{testTypes.map((testType) => { const result = providerTests[`${provider.id}:${model.id}:${testType}`]; return result ? <ProviderTestResult key={testType} result={result} /> : null })}</div>
          })}</div>
        </div>
      })}</div>
    </div>
    <div><h3 className="mb-2 text-sm font-bold dark:text-white">资源池与 API Key</h3><div className="space-y-2">{resources.data.pools.map((pool) => <div key={pool.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><div className="flex justify-between gap-3"><div><div className="text-sm font-semibold dark:text-white">{pool.name}</div><div className="mt-1 text-xs text-gray-500">{pool.code} · {pool.model_code} · {pool.organization_name ?? '平台共享'} · {pool.key_ids.length} 个 Key</div><div className="mt-1 text-xs text-blue-600 dark:text-blue-300">{Object.entries(pool.operation_bindings).map(([operation, capabilities]) => `${operation} → ${capabilities.join('/')}`).join('；') || '尚未绑定业务操作'}</div></div><button className={secondaryButton} onClick={() => toggle.mutate({ type: 'resource-pools', id: pool.id, enabled: !pool.enabled })}>{pool.enabled ? '停用' : '启用'}</button></div></div>)}{resources.data.keys.map((key) => <div key={key.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><div className="flex justify-between gap-3"><div><div className="text-sm font-semibold dark:text-white">{key.label} · {key.masked_secret}</div><div className="mt-1 text-xs text-gray-500">并发 {key.current_concurrency}/{key.max_concurrency} · RPM {key.rpm_limit ?? '不限'} · {key.status}</div></div><button className={secondaryButton} onClick={() => toggle.mutate({ type: 'api-keys', id: key.id, enabled: !key.enabled })}>{key.enabled ? '停用' : '启用'}</button></div></div>)}</div></div>
  </div></Section></div>
}

function TasksTab() {
  const queues = useQuery({ queryKey: ['admin', 'queues'], queryFn: getAdminQueues, refetchInterval: 5_000 })
  const jobs = useQuery({ queryKey: ['admin', 'jobs'], queryFn: getAdminJobs, refetchInterval: 5_000 })
  return <div className="space-y-5"><Section title="Celery 队列" description="队列深度来自 Redis，任务状态来自统一任务表；服务重启后仍可恢复。" action={queues.data && <StatusPill active={queues.data.redis_ok}>{queues.data.redis_ok ? 'Redis 正常' : 'Redis 不可用'}</StatusPill>}>
    {!queues.data ? <LoadingOrError loading={queues.isLoading} error={queues.error} /> : <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{queues.data.items.map((queue) => <div key={queue.name} className="rounded-xl bg-gray-50 p-3 dark:bg-gray-950"><div className="text-sm font-bold dark:text-white">{queue.name}</div><div className="mt-3 grid grid-cols-2 gap-2 text-xs text-gray-500"><span>Broker {queue.broker_depth}</span><span>排队 {queue.queued_jobs}</span><span>等待通道 {queue.waiting_for_resource_jobs}</span><span>运行 {queue.running_jobs}</span><span>技术重试 {queue.retry_waiting_jobs}</span></div>{queue.failed_jobs > 0 && <div className="mt-2 text-xs font-semibold text-red-600">失败 {queue.failed_jobs}</div>}</div>)}</div>}
  </Section><Section title="全平台任务" description="显示最近 100 个任务，用于定位上游限流、超时、Worker 异常和部分失败。">
    {!jobs.data ? <LoadingOrError loading={jobs.isLoading} error={jobs.error} /> : <div className="overflow-x-auto"><table className="w-full min-w-[1320px] text-left text-sm"><thead className="text-xs text-gray-500"><tr><th className="pb-3">任务</th><th className="pb-3">团队</th><th className="pb-3">队列/模型</th><th className="pb-3">状态/耗时</th><th className="pb-3">尺寸诊断</th><th className="pb-3">Worker/上游</th><th className="pb-3">错误</th><th className="pb-3">创建时间</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-white/[0.06]">{jobs.data.items.map((job) => <tr key={job.id}><td className="py-3 pr-4"><div className="font-semibold dark:text-white">{job.operation_code}</div><div className="mt-1 max-w-[180px] truncate text-xs text-gray-500">{job.id}</div></td><td className="py-3 pr-4 text-xs dark:text-gray-300">{job.organization_name}</td><td className="py-3 pr-4 text-xs text-gray-500">{job.queue_name}<br />{job.model_code}</td><td className="py-3 pr-4"><StatusPill active={job.status === 'succeeded'}>{job.status} · {Math.round(job.progress)}%</StatusPill><div className="mt-1 font-mono text-xs text-gray-500">{formatDuration(job.generation_duration_ms)}</div></td><td className="max-w-[300px] py-3 pr-4 text-xs text-gray-500"><div>用户：{job.requested_aspect_ratio ?? '—'} · {job.requested_width && job.requested_height ? `${job.requested_width}×${job.requested_height}` : 'auto'}</div><div className="mt-1">上游：{job.submitted_dimension_field ? `${job.submitted_dimension_field}=${job.submitted_dimension_value}` : job.resolved_provider_size ?? '—'}</div><div className={`mt-1 ${job.size_mismatch ? 'font-semibold text-amber-600' : ''}`}>实际：{job.actual_width && job.actual_height ? `${job.actual_width}×${job.actual_height}` : '—'}{job.size_mismatch ? ' · 尺寸不一致' : ''}</div></td><td className="max-w-[220px] py-3 pr-4 text-xs text-gray-500"><div className="truncate">{job.worker_name ?? '—'}</div><div className="mt-1 truncate" title={job.upstream_request_id ?? ''}>{job.upstream_request_id ?? '无 request id'}</div></td><td className="max-w-[260px] py-3 pr-4 text-xs text-red-600">{job.error_code ? `${job.error_code}: ${job.error_message ?? ''}` : '—'}</td><td className="py-3 text-xs text-gray-500">{time(job.created_at)}</td></tr>)}</tbody></table></div>}
  </Section></div>
}

function GenerationDiagnosticsTab() {
  const now = useCurrentTime()
  const diagnostics = useQuery({
    queryKey: ['admin', 'generation-resources'],
    queryFn: getGenerationResourceDiagnostics,
    refetchInterval: 5_000,
  })
  if (!diagnostics.data) return <LoadingOrError loading={diagnostics.isLoading} error={diagnostics.error} />
  const { system, resource_pools: pools, providers, keys } = diagnostics.data
  const rate = (value: number | null) => value === null ? '—' : `${value.toFixed(1)}%`
  const latency = (value: number | null) => value === null ? '—' : formatDuration(value)
  const systemCards = [
    ['真实上游请求', system.true_active_requests, `系统上限 ${system.configured_concurrency}`],
    ['数据库运行', system.database_running, `派发中 ${system.database_dispatching}`],
    ['Redis 槽位', system.redis_inflight, system.slot_mismatch ? '三方计数不一致' : '计数一致'],
    ['等待生成通道', system.waiting_for_resource, `普通排队 ${system.queued}`],
    ['技术重试', system.retry_waiting, `剩余 ${system.remaining_jobs}`],
    ['最近一小时成功', system.recent_hour_successes, system.eta_minutes === null ? '暂时无法估算 ETA' : `预计剩余 ${system.eta_minutes} 分钟`],
  ] as const
  return <div className="space-y-5">
    <Section
      title="系统并发总览"
      description="“真实上游请求”只统计已经发出且尚未结束的 HTTP 生图请求；等待资源不会计为失败或重试。"
      action={<StatusPill active={!system.slot_mismatch}>{system.slot_mismatch ? '槽位需要对账' : '槽位一致'}</StatusPill>}
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{systemCards.map(([label, value, detail]) => <div key={label} className="rounded-xl bg-gray-50 p-4 dark:bg-gray-950"><div className="text-xs text-gray-500">{label}</div><div className="mt-1 text-2xl font-black dark:text-white">{value}</div><div className={`mt-1 text-xs ${detail.includes('不一致') ? 'text-amber-600' : 'text-gray-500'}`}>{detail}</div></div>)}</div>
      <div className="mt-3 text-xs text-gray-500">在线 Worker：{system.worker_names.join('、') || '未检测到心跳'} · 数据每 5 秒刷新</div>
    </Section>
    <Section title="Provider 节点" description="统计窗口为最近 60 分钟；平台无法读取 New API 内部的 Codex 账号分配明细。">
      <div className="grid gap-3 xl:grid-cols-2">{providers.map((provider) => <div key={provider.id} className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]"><div className="flex items-start justify-between gap-3"><div><div className="font-bold dark:text-white">{provider.name}</div><div className="mt-1 text-xs text-gray-500">{provider.code} · {provider.base_url}</div></div><StatusPill active={provider.enabled}>{provider.enabled ? '启用' : '停用'}</StatusPill></div><div className="mt-4 grid grid-cols-3 gap-2 text-xs"><span>并发 {provider.active}/{provider.configured_capacity}</span><span>空闲 {provider.idle}</span><span>冷却 Key {provider.cooling_keys}</span><span>成功 {provider.successes}/{provider.requests}</span><span>成功率 {rate(provider.success_rate)}</span><span>每小时 {provider.hourly_successes}</span><span>平均 {latency(provider.average_latency_ms)}</span><span>P90 {latency(provider.p90_latency_ms)}</span><span>524 {provider.http_524}</span><span>429 {provider.http_429}</span><span>5xx {provider.http_5xx}</span><span>超时 {provider.timeouts}</span></div><div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10 dark:text-amber-200">{provider.account_visibility}</div></div>)}</div>
    </Section>
    <Section title="通道恢复状态" description="倒计时每秒更新；冷却结束后先放行一个探测任务，探测成功才恢复完整并发。">
      <div className="grid gap-3 xl:grid-cols-2">
        {providers.map((provider) => (
          <div key={provider.id} className="rounded-xl border border-gray-200 p-4 dark:border-white/[0.08]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-bold text-gray-950 dark:text-white">{provider.name}</div>
                <div className="mt-1 text-xs text-gray-500">{provider.code}</div>
              </div>
              <RecoveryBadge state={provider.recovery_state} />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-gray-600 dark:text-gray-300 sm:grid-cols-3">
              <span>配置并发 {provider.configured_capacity}</span>
              <span>当前有效 {provider.effective_capacity}</span>
              <span>正在请求 {provider.active}</span>
              <span>Redis 槽位 {provider.redis_active}</span>
              <span>恢复中 Key {provider.recovering_keys}</span>
              <span>探测任务 {provider.probe_active}</span>
              <span>最近 524 {provider.http_524}</span>
            </div>
            {provider.recovery_state === 'cooling' && (
              <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm font-bold text-amber-800 dark:bg-amber-500/10 dark:text-amber-100">
                距离下次探测：{countdown(provider.next_probe_at, now)}
                <span className="ml-2 text-xs font-normal">({time(provider.next_probe_at)})</span>
              </div>
            )}
            {provider.recovery_state === 'waiting_probe' && (
              <div className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-sm font-bold text-blue-800 dark:bg-blue-500/10 dark:text-blue-100">
                冷却结束，正在等待调度探测任务
              </div>
            )}
            {provider.recovery_state === 'probing' && (
              <div className="mt-3 rounded-lg bg-violet-50 px-3 py-2 text-sm font-bold text-violet-800 dark:bg-violet-500/10 dark:text-violet-100">
                探测请求正在生成；成功后自动恢复 {provider.configured_capacity} 并发
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {keys.map((key) => (
          <div key={key.id} className="rounded-xl bg-gray-50 p-3 text-xs dark:bg-gray-950">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-gray-900 dark:text-white">{key.label} · {key.masked_secret}</span>
              <RecoveryBadge state={key.recovery_state} />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-gray-600 dark:text-gray-300">
              <span>有效并发 {key.effective_capacity}/{key.configured_capacity}</span>
              <span>当前请求 {key.active}</span>
              <span>Redis 槽位 {key.redis_active}</span>
              <span>连续失败 {key.consecutive_failures}</span>
              <span>{key.probe_active ? '探测请求运行中' : '无探测请求'}</span>
            </div>
            {key.recovery_state === 'cooling' && (
              <div className="mt-2 font-bold text-amber-700 dark:text-amber-200">
                下次探测倒计时 {countdown(key.next_probe_at, now)}
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
    <Section title="Resource Pool 明细" description="Resource Pool 将业务 operation_code 绑定到模型与一个或多个 API Key。">
      <div className="overflow-x-auto"><table className="w-full min-w-[1050px] text-left text-xs"><thead className="text-gray-500"><tr><th className="pb-3">资源池</th><th className="pb-3">操作/模型</th><th className="pb-3">并发</th><th className="pb-3">等待</th><th className="pb-3">成功率</th><th className="pb-3">吞吐</th><th className="pb-3">耗时</th><th className="pb-3">错误</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-white/[0.06]">{pools.map((pool) => <tr key={pool.id}><td className="py-3 pr-4"><div className="font-semibold dark:text-white">{pool.name}</div><div className="text-gray-500">{pool.code}</div></td><td className="py-3 pr-4 text-gray-500">{pool.operation_codes.join('、') || '未绑定'}<br />{pool.model_code ?? '—'}</td><td className="py-3 pr-4">{pool.active}/{pool.configured_capacity}</td><td className="py-3 pr-4">{pool.waiting_jobs}</td><td className="py-3 pr-4">{rate(pool.success_rate)}</td><td className="py-3 pr-4">{pool.hourly_successes}/小时</td><td className="py-3 pr-4">平均 {latency(pool.average_latency_ms)}<br />P90 {latency(pool.p90_latency_ms)}</td><td className="py-3 pr-4 text-gray-500">429 {pool.http_429} · 524 {pool.http_524}<br />超时 {pool.timeouts}</td></tr>)}</tbody></table></div>
    </Section>
    <Section title="Key / 渠道明细" description="只显示掩码，不返回完整 API Key、Authorization 或上游认证文件。">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{keys.map((key) => <div key={key.id} className="rounded-xl border border-gray-200 p-3 text-xs dark:border-white/[0.08]"><div className="font-semibold dark:text-white">{key.label} · {key.masked_secret}</div><div className="mt-1 text-gray-500">{key.provider_name ?? key.provider_id}</div><div className="mt-3 grid grid-cols-2 gap-2"><span>并发 {key.active}/{key.configured_capacity}</span><span>状态 {key.status}</span><span>成功 {key.successes}</span><span>失败 {key.failures}</span><span>429 {key.http_429}</span><span>524 {key.http_524}</span></div><div className="mt-2 text-gray-500">冷却至 {time(key.cooldown_until)}</div></div>)}</div>
    </Section>
  </div>
}

function AuditsTab() {
  const audits = useQuery({ queryKey: ['admin', 'audits'], queryFn: getAdminAudits, refetchInterval: 10_000 })
  const logins = useQuery({ queryKey: ['admin', 'login-audits'], queryFn: getAdminLoginAudits, refetchInterval: 10_000 })
  return <div className="grid gap-5 xl:grid-cols-2"><Section title="操作审计" description="管理操作、额度变更和资源配置会记录操作者、资源、请求与来源 IP。">{!audits.data ? <LoadingOrError loading={audits.isLoading} error={audits.error} /> : <div className="max-h-[640px] space-y-2 overflow-auto">{audits.data.items.map((item) => <div key={item.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><div className="flex justify-between gap-3"><span className="text-sm font-semibold dark:text-white">{item.action}</span><span className="text-xs text-gray-500">{time(item.created_at)}</span></div><div className="mt-1 text-xs text-gray-500">{item.resource_type} · {item.resource_id ?? '—'} · IP {item.ip_address ?? '—'}</div></div>)}{!audits.data.items.length && <div className="py-10 text-center text-sm text-gray-500">暂无操作审计</div>}</div>}</Section><Section title="登录安全日志" description="用于追踪登录成功、失败、刷新、退出和团队切换。">{!logins.data ? <LoadingOrError loading={logins.isLoading} error={logins.error} /> : <div className="max-h-[640px] space-y-2 overflow-auto">{logins.data.items.map((item) => <div key={item.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><div className="flex justify-between gap-3"><span className="text-sm font-semibold dark:text-white">{item.account ?? '未知账号'} · {item.event}</span><StatusPill active={item.outcome === 'success'}>{item.outcome}</StatusPill></div><div className="mt-1 text-xs text-gray-500">{time(item.created_at)} · IP {item.ip_address ?? '—'}</div>{item.detail && <div className="mt-1 text-xs text-red-600">{item.detail}</div>}</div>)}{!logins.data.items.length && <div className="py-10 text-center text-sm text-gray-500">暂无登录日志</div>}</div>}</Section></div>
}

export default function AdminPage() {
  const auth = useAuth()
  const platformAdmin = auth.hasPermission('platform.admin')
  const canManageUsers = auth.hasPermission('organization.members.write')
  const [tab, setTab] = useState<Tab>(() => platformAdmin ? 'overview' : 'users')
  const [message, setMessage] = useState('')
  const content = useMemo(() => {
    if (tab === 'users') return <UsersTab notify={setMessage} />
    if (tab === 'organizations') return <OrganizationsTab notify={setMessage} />
    if (tab === 'categories') return <CategoryListingManagementPanel notify={setMessage} />
    if (tab === 'creative') return <CreativePresetManagementPanel notify={setMessage} />
    if (tab === 'reference-library') return <AttachmentReferenceLibraryManagementPanel notify={setMessage} />
    if (tab === 'resources') return <ResourcesTab notify={setMessage} />
    if (tab === 'diagnostics') return <GenerationDiagnosticsTab />
    if (tab === 'tasks') return <TasksTab />
    if (tab === 'audits') return <AuditsTab />
    return <OverviewTab />
  }, [tab])
  if (!platformAdmin && !canManageUsers) return <div className={`${panelClass} mt-6 p-8 text-center`}><h1 className="text-xl font-bold text-gray-950 dark:text-white">无权访问管理后台</h1><p className="mt-2 text-sm text-gray-500">此页面仅对平台管理员和团队管理员开放，服务端也会重新校验权限。</p></div>
  const visibleTabs = platformAdmin ? tabs : tabs.filter((item) => item.id === 'users')
  return <div className="mt-6 space-y-5"><section className={`${panelClass} p-5`}><div className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-xl font-bold text-gray-950 dark:text-white">管理后台</h1><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">统一管理账号、团队、额度、API Key、资源池、任务队列与审计日志。</p></div><StatusPill active>{auth.identity?.user.account ?? '管理员'}</StatusPill></div><div className="mt-5 flex gap-2 overflow-x-auto pb-1">{visibleTabs.map((item) => <button key={item.id} onClick={() => { setTab(item.id); setMessage('') }} className={`shrink-0 rounded-xl px-4 py-2 text-sm font-semibold transition ${tab === item.id ? 'bg-gray-950 text-white dark:bg-white dark:text-gray-950' : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-white/[0.06] dark:text-gray-300 dark:hover:bg-white/[0.1]'}`}>{item.label}</button>)}</div></section>{message && <div role="status" className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700 dark:border-blue-400/20 dark:bg-blue-500/10 dark:text-blue-300">{message}</div>}{content}</div>
}
