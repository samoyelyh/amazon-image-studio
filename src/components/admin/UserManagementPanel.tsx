import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useAuth } from '../../app/AuthContext'
import { AuthApiError, type AuthMembership } from '../../lib/authApi'
import { getAdminUsers, updateAdminUser } from '../../lib/adminApi'
import { generateSecurePassword, isStrongPassword, passwordRules } from '../../lib/passwordPolicy'
import { randomUuid } from '../../lib/randomUuid'
import {
  createOrganizationMember,
  getCurrentOrganizationMembers,
  removeOrganizationMember,
  resetOrganizationMemberPassword,
  updateOrganizationMemberAccount,
  updateOrganizationMemberRole,
  updateOrganizationMemberStatus,
  type OrganizationRole,
} from '../../lib/userManagementApi'

const panelClass = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const inputClass = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const primaryButton = 'rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50'
const secondaryButton = 'rounded-xl border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.05]'

const roles: Array<{ code: OrganizationRole; label: string; description: string }> = [
  { code: 'organization_admin', label: '团队管理员', description: '管理当前团队成员及团队配置' },
  { code: 'manager', label: '业务经理', description: '管理业务项目和团队任务' },
  { code: 'member', label: '普通成员', description: '可以创建项目和生成图片' },
  { code: 'viewer', label: '只读用户', description: '只能查看允许的数据，不能生成或修改' },
]

function formatTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}

function errorMessage(error: unknown) {
  if (error instanceof TypeError) return '网络连接异常，请稍后重试。'
  if (!(error instanceof AuthApiError)) return error instanceof Error ? error.message : '操作失败，请稍后重试。'
  const mapping: Record<string, string> = {
    'organization.user_account_exists': '该账号已存在，请更换账号或重置该用户密码。',
    'organization.last_admin': '团队至少需要保留一名启用状态的管理员。',
    'auth.weak_password': error.message,
    'auth.permission_denied': '你没有执行此操作的权限。',
    'organization.member_limit_reached': '当前套餐的成员数量已达到上限。',
  }
  return mapping[error.code] || error.message
}

function Section({ title, description, action, children }: { title: string; description: string; action?: ReactNode; children: ReactNode }) {
  return <section className={panelClass}>
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-white/[0.06]">
      <div><h2 className="font-bold text-gray-950 dark:text-white">{title}</h2><p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p></div>
      {action}
    </div>
    <div className="p-5">{children}</div>
  </section>
}

function Modal({ title, children, onClose, disableClose = false }: { title: string; children: ReactNode; onClose: () => void; disableClose?: boolean }) {
  return <div className="fixed inset-0 z-[80] flex items-center justify-center bg-gray-950/55 p-4" role="dialog" aria-modal="true" aria-label={title}>
    <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-gray-200 bg-white p-6 shadow-2xl dark:border-white/[0.1] dark:bg-gray-900">
      <div className="flex items-center justify-between gap-4"><h2 className="text-lg font-bold text-gray-950 dark:text-white">{title}</h2><button type="button" disabled={disableClose} onClick={onClose} className={secondaryButton}>关闭</button></div>
      <div className="mt-5">{children}</div>
    </div>
  </div>
}

function PasswordInput({ password, setPassword, account, displayName }: { password: string; setPassword: (value: string) => void; account: string; displayName: string }) {
  const [visible, setVisible] = useState(true)
  const rules = passwordRules(password, account, displayName)
  return <div>
    <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">初始密码</label>
    <div className="mt-2 flex flex-wrap gap-2"><input required type={visible ? 'text' : 'password'} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} className="min-w-[220px] flex-1 rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-900 outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" /><button type="button" className={secondaryButton} onClick={() => setVisible((value) => !value)}>{visible ? '隐藏' : '显示'}</button><button type="button" className={secondaryButton} onClick={() => navigator.clipboard.writeText(password)}>复制</button><button type="button" className={secondaryButton} onClick={() => setPassword(generateSecurePassword())}>重新生成</button></div>
    <div className={`mt-2 text-xs font-semibold ${rules.every((rule) => rule.passed) ? 'text-emerald-600' : 'text-amber-600'}`}>密码强度：{rules.every((rule) => rule.passed) ? '强' : '未达到要求'}</div>
    <div className="mt-3 grid gap-1.5 sm:grid-cols-2">{rules.map((rule) => <div key={rule.label} className={`text-xs ${rule.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'}`}>{rule.passed ? '✓' : '○'} {rule.label}</div>)}</div>
  </div>
}

interface OneTimeCredential { action: 'created' | 'reset'; name: string; account: string; role: string; password: string }

function OneTimeCredentialModal({ value, onClose }: { value: OneTimeCredential; onClose: () => void }) {
  const loginUrl = new URL('login', `${window.location.origin}${import.meta.env.BASE_URL}`).toString()
  const copy = (text: string) => navigator.clipboard.writeText(text)
  const loginInfo = `登录地址：${loginUrl}\n登录账号：${value.account}\n初始密码：${value.password}\n请妥善保管初始密码。`
  return <Modal title={value.action === 'created' ? '用户创建成功' : '密码重置成功'} onClose={onClose}>
    <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">密码只在本窗口显示一次。关闭后系统不会再提供明文，请先复制并通过安全渠道交给用户。</div>
    <dl className="mt-4 space-y-3 text-sm"><div><dt className="text-gray-500">用户姓名 / 角色</dt><dd className="mt-1 font-medium text-gray-950 dark:text-white">{value.name} · {value.role}</dd></div><div><dt className="text-gray-500">登录地址</dt><dd className="mt-1 break-all font-medium text-gray-950 dark:text-white">{loginUrl}</dd></div><div><dt className="text-gray-500">登录账号</dt><dd className="mt-1 font-medium text-gray-950 dark:text-white">{value.account}</dd></div><div><dt className="text-gray-500">初始密码</dt><dd className="mt-1 break-all rounded-xl bg-gray-100 px-3 py-2 font-mono font-bold text-gray-950 dark:bg-gray-950 dark:text-white">{value.password}</dd></div></dl>
    <div className="mt-5 flex flex-wrap gap-2"><button className={primaryButton} onClick={() => copy(loginInfo)}>复制完整登录信息</button><button className={secondaryButton} onClick={() => copy(value.password)}>仅复制密码</button></div>
  </Modal>
}

export default function UserManagementPanel({ notify, platformAdmin }: { notify: (message: string) => void; platformAdmin: boolean }) {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const members = useQuery({ queryKey: ['organization', 'members'], queryFn: getCurrentOrganizationMembers })
  const platformUsers = useQuery({ queryKey: ['admin', 'users'], queryFn: getAdminUsers, enabled: platformAdmin })
  const [createOpen, setCreateOpen] = useState(false)
  const [createKey, setCreateKey] = useState('')
  const [createForm, setCreateForm] = useState({ account: '', displayName: '', role: 'member' as OrganizationRole, password: generateSecurePassword() })
  const [createPasswordConfirm, setCreatePasswordConfirm] = useState('')
  const [resetTarget, setResetTarget] = useState<{ id: string; account: string; displayName: string } | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetPasswordConfirm, setResetPasswordConfirm] = useState('')
  const [accountTarget, setAccountTarget] = useState<{ id: string; account: string; displayName: string } | null>(null)
  const [oneTime, setOneTime] = useState<OneTimeCredential | null>(null)
  const [detailMember, setDetailMember] = useState<AuthMembership | null>(null)
  const canCreate = auth.hasPermission('organization.members.write') && auth.hasPermission('roles.assign')
  const creators = useMemo(() => new Map((members.data || []).map((item) => [item.user.id, item.user.display_name])), [members.data])
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ['organization', 'members'] }); queryClient.invalidateQueries({ queryKey: ['admin'] }) }
  const fail = (error: unknown) => notify(errorMessage(error))

  const createMutation = useMutation({
    mutationFn: () => createOrganizationMember({ account: createForm.account.trim().toLowerCase(), display_name: createForm.displayName.trim(), temporary_password: createForm.password, role_code: createForm.role }, createKey),
    onSuccess: () => { const credential: OneTimeCredential = { action: 'created', name: createForm.displayName.trim(), account: createForm.account.trim().toLowerCase(), role: roles.find((role) => role.code === createForm.role)?.label || createForm.role, password: createForm.password }; setCreateOpen(false); setCreateForm({ account: '', displayName: '', role: 'member', password: '' }); setCreatePasswordConfirm(''); setOneTime(credential); notify('用户创建成功'); refresh() },
    onError: fail,
  })
  const resetMutation = useMutation({
    mutationFn: () => resetOrganizationMemberPassword(resetTarget!.id, resetPassword),
    onSuccess: () => { const credential: OneTimeCredential = { action: 'reset', name: resetTarget!.displayName, account: resetTarget!.account, role: '当前团队成员', password: resetPassword }; setResetTarget(null); setResetPassword(''); setResetPasswordConfirm(''); setOneTime(credential); notify('密码已重置'); refresh() },
    onError: fail,
  })
  const roleMutation = useMutation({ mutationFn: ({ id, role }: { id: string; role: OrganizationRole }) => updateOrganizationMemberRole(id, role), onSuccess: () => { notify('角色已更新'); refresh() }, onError: fail })
  const statusMutation = useMutation({ mutationFn: ({ id, status }: { id: string; status: 'active' | 'disabled' }) => updateOrganizationMemberStatus(id, status), onSuccess: () => { notify('成员状态已更新'); refresh() }, onError: fail })
  const accountMutation = useMutation({ mutationFn: () => updateOrganizationMemberAccount(accountTarget!.id, accountTarget!.account.trim().toLowerCase()), onSuccess: () => { notify('登录账号已更新，旧会话已失效'); setAccountTarget(null); refresh() }, onError: fail })
  const removeMutation = useMutation({ mutationFn: removeOrganizationMember, onSuccess: () => { notify('成员已从当前团队移除'); refresh() }, onError: fail })
  const platformMutation = useMutation({ mutationFn: ({ id, status, admin }: { id: string; status?: 'active' | 'disabled'; admin?: boolean }) => updateAdminUser(id, { status, platform_admin: admin }), onSuccess: () => { notify('平台账号已更新'); refresh() }, onError: fail })

  const openCreate = () => { setCreateKey(`user-create:${randomUuid()}`); setCreateForm({ account: '', displayName: '', role: 'member', password: generateSecurePassword() }); setCreatePasswordConfirm(''); setCreateOpen(true) }
  const openReset = (id: string, account: string, displayName: string) => { setResetTarget({ id, account, displayName }); setResetPassword(generateSecurePassword()); setResetPasswordConfirm('') }
  const submitCreate = (event: FormEvent) => { event.preventDefault(); if (createForm.password === createPasswordConfirm && isStrongPassword(createForm.password, createForm.account, createForm.displayName)) createMutation.mutate() }
  const submitReset = (event: FormEvent) => { event.preventDefault(); if (resetTarget && resetPassword === resetPasswordConfirm && isStrongPassword(resetPassword, resetTarget.account, resetTarget.displayName)) resetMutation.mutate() }

  return <div className="space-y-5">
    <Section title="当前团队用户" description="创建、分配角色、重置密码和控制当前团队访问权限。密码重置后，用户的全部旧会话会立即失效。" action={canCreate ? <button className={primaryButton} onClick={openCreate}>创建用户</button> : undefined}>
      {members.isLoading && <div className="py-10 text-center text-sm text-gray-500">正在加载…</div>}
      {members.error && <div className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{errorMessage(members.error)}</div>}
      {members.data && <div className="overflow-x-auto"><table className="w-full min-w-[1040px] text-left text-sm"><thead className="text-xs text-gray-500"><tr><th className="pb-3">用户</th><th className="pb-3">团队角色</th><th className="pb-3">密码状态</th><th className="pb-3">创建 / 登录</th><th className="pb-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-white/[0.06]">
        {members.data.map((member) => { const self = member.user.id === auth.identity?.user.id; return <tr key={member.id}><td className="py-4 pr-4"><div className="font-semibold text-gray-950 dark:text-white">{member.user.display_name}</div><div className="mt-1 text-xs text-gray-500">{member.user.account}</div><span className={`mt-2 inline-flex rounded-full px-2 py-1 text-xs font-semibold ${member.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'}`}>{member.status === 'active' ? '正常' : '已停用'}</span></td><td className="py-4 pr-4"><select className={inputClass} value={member.role.code} disabled={roleMutation.isPending || self} onChange={(event) => roleMutation.mutate({ id: member.id, role: event.target.value as OrganizationRole })}>{roles.map((role) => <option key={role.code} value={role.code}>{role.label}</option>)}</select></td><td className="py-4 pr-4 text-xs"><div className={member.user.must_change_password ? 'font-semibold text-amber-600' : 'text-emerald-600'}>{member.user.must_change_password ? (member.user.last_login_at ? '必须修改密码' : '待首次登录 · 必须修改密码') : '已设置正式密码'}</div><div className="mt-1 text-gray-500">修改于 {formatTime(member.user.password_changed_at)}</div></td><td className="py-4 pr-4 text-xs text-gray-500"><div>创建：{formatTime(member.user.created_at)}</div><div className="mt-1">创建人：{member.user.created_by ? creators.get(member.user.created_by) || member.user.created_by : '系统'}</div><div className="mt-1">登录：{formatTime(member.user.last_login_at)}</div></td><td className="py-4"><div className="flex justify-end gap-2"><button className={secondaryButton} onClick={() => setDetailMember(member)}>详情</button><button className={secondaryButton} disabled={self} onClick={() => setAccountTarget({ id: member.id, account: member.user.account, displayName: member.user.display_name })}>修改账号</button><button className={secondaryButton} disabled={self} onClick={() => openReset(member.id, member.user.account, member.user.display_name)}>重置密码</button><button className={secondaryButton} disabled={self || statusMutation.isPending} onClick={() => { const next = member.status === 'active' ? 'disabled' : 'active'; if (next === 'active' || window.confirm(`确认停用 ${member.user.display_name}？该用户将无法访问当前团队。`)) statusMutation.mutate({ id: member.id, status: next }) }}>{member.status === 'active' ? '停用' : '启用'}</button><button className={secondaryButton} disabled={self || removeMutation.isPending} onClick={() => { if (window.confirm(`确认将 ${member.user.display_name} 从当前团队移除？`)) removeMutation.mutate(member.id) }}>移除</button></div></td></tr> })}
        {!members.data.length && <tr><td colSpan={5} className="py-12 text-center text-gray-500">当前团队暂无用户</td></tr>}
      </tbody></table></div>}
    </Section>

    {platformAdmin && <Section title="全平台账号" description="平台级停用和平台管理员授权会影响该账号在所有团队中的访问。">
      {!platformUsers.data ? <div className="py-8 text-center text-sm text-gray-500">正在加载…</div> : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead className="text-xs text-gray-500"><tr><th className="pb-3">账号</th><th className="pb-3">团队数</th><th className="pb-3">平台角色</th><th className="pb-3 text-right">操作</th></tr></thead><tbody className="divide-y divide-gray-100 dark:divide-white/[0.06]">{platformUsers.data.items.map((user) => { const self = user.id === auth.identity?.user.id; const admin = user.platform_role === 'platform_admin'; return <tr key={user.id}><td className="py-4"><div className="font-semibold dark:text-white">{user.display_name}</div><div className="text-xs text-gray-500">{user.account} · {user.status === 'active' ? '启用' : '停用'}</div></td><td>{user.memberships.length}</td><td>{admin ? '平台管理员' : '普通账号'}</td><td><div className="flex justify-end gap-2"><button className={secondaryButton} disabled={self} onClick={() => platformMutation.mutate({ id: user.id, admin: !admin })}>{admin ? '取消平台管理员' : '设为平台管理员'}</button><button className={secondaryButton} disabled={self} onClick={() => platformMutation.mutate({ id: user.id, status: user.status === 'active' ? 'disabled' : 'active' })}>{user.status === 'active' ? '全局停用' : '全局启用'}</button></div></td></tr> })}</tbody></table></div>}
    </Section>}

    {createOpen && <Modal title="创建用户" disableClose={createMutation.isPending} onClose={() => { setCreateOpen(false); setCreateForm((value) => ({ ...value, password: '' })) }}><form className="space-y-4" onSubmit={submitCreate}><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">登录账号<input required type="text" autoComplete="off" className={`mt-2 ${inputClass}`} value={createForm.account} onChange={(event) => setCreateForm((value) => ({ ...value, account: event.target.value }))} /></label><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">用户姓名<input required minLength={2} maxLength={50} autoComplete="off" className={`mt-2 ${inputClass}`} value={createForm.displayName} onChange={(event) => setCreateForm((value) => ({ ...value, displayName: event.target.value }))} /></label><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">用户角色<select className={`mt-2 ${inputClass}`} value={createForm.role} onChange={(event) => setCreateForm((value) => ({ ...value, role: event.target.value as OrganizationRole }))}>{roles.map((role) => <option key={role.code} value={role.code}>{role.label} — {role.description}</option>)}</select></label><PasswordInput password={createForm.password} setPassword={(password) => setCreateForm((value) => ({ ...value, password }))} account={createForm.account} displayName={createForm.displayName} /><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">确认初始密码<input required type="password" autoComplete="new-password" className={`mt-2 ${inputClass}`} value={createPasswordConfirm} onChange={(event) => setCreatePasswordConfirm(event.target.value)} /></label><button className={`w-full ${primaryButton}`} disabled={createMutation.isPending || !createForm.account || createForm.displayName.trim().length < 2 || createForm.password !== createPasswordConfirm || !isStrongPassword(createForm.password, createForm.account, createForm.displayName)}>{createMutation.isPending ? '正在创建…' : '确认创建'}</button></form></Modal>}
    {resetTarget && <Modal title={`重置 ${resetTarget.displayName} 的密码`} disableClose={resetMutation.isPending} onClose={() => { setResetTarget(null); setResetPassword('') }}><form className="space-y-4" onSubmit={submitReset}><div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">提交后该用户所有旧会话立即失效，旧密码立即失效，新密码可直接登录。</div><PasswordInput password={resetPassword} setPassword={setResetPassword} account={resetTarget.account} displayName={resetTarget.displayName} /><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">确认新密码<input required type="password" autoComplete="new-password" className={`mt-2 ${inputClass}`} value={resetPasswordConfirm} onChange={(event) => setResetPasswordConfirm(event.target.value)} /></label><button className={`w-full ${primaryButton}`} disabled={resetMutation.isPending || resetPassword !== resetPasswordConfirm || !isStrongPassword(resetPassword, resetTarget.account, resetTarget.displayName)}>{resetMutation.isPending ? '正在重置…' : '确认重置密码'}</button></form></Modal>}
    {accountTarget && <Modal title={`修改 ${accountTarget.displayName} 的账号`} disableClose={accountMutation.isPending} onClose={() => setAccountTarget(null)}><form className="space-y-4" onSubmit={(event) => { event.preventDefault(); accountMutation.mutate() }}><label className="block text-sm font-medium text-gray-700 dark:text-gray-200">登录账号<input required minLength={3} maxLength={32} pattern="[A-Za-z0-9_-]+" autoComplete="off" className={`mt-2 ${inputClass}`} value={accountTarget.account} onChange={(event) => setAccountTarget((value) => value ? { ...value, account: event.target.value } : value)} /></label><p className="text-xs text-gray-500">修改后该用户的旧登录会话会立即失效，需要使用新账号重新登录。</p><button className={`w-full ${primaryButton}`} disabled={accountMutation.isPending}>确认修改账号</button></form></Modal>}
    {detailMember && <Modal title="用户详情" onClose={() => setDetailMember(null)}><dl className="space-y-3 text-sm"><div><dt className="text-gray-500">用户</dt><dd className="mt-1 font-semibold dark:text-white">{detailMember.user.display_name} · {detailMember.user.account}</dd></div><div><dt className="text-gray-500">团队角色 / 状态</dt><dd className="mt-1 dark:text-white">{roles.find((role) => role.code === detailMember.role.code)?.label || detailMember.role.code} · {detailMember.status === 'active' ? '正常' : '已停用'}</dd></div><div><dt className="text-gray-500">密码状态</dt><dd className="mt-1 dark:text-white">{detailMember.user.must_change_password ? '必须修改密码' : '已设置正式密码'}</dd></div><div><dt className="text-gray-500">创建 / 最后登录</dt><dd className="mt-1 dark:text-white">{formatTime(detailMember.user.created_at)} / {formatTime(detailMember.user.last_login_at)}</dd></div></dl></Modal>}
    {oneTime && <OneTimeCredentialModal value={oneTime} onClose={() => setOneTime(null)} />}
  </div>
}
