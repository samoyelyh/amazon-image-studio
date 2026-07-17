import { useState, type FormEvent } from 'react'
import { useAuth } from '../app/AuthContext'
import { authenticatedFetch, type CurrentIdentity } from '../lib/authApi'

export default function ProfilePage() {
  const auth = useAuth()
  const identity = auth.identity!
  const [displayName, setDisplayName] = useState(identity.user.display_name)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setMessage('')
    try {
      const nextIdentity = await authenticatedFetch<CurrentIdentity>('/users/me', {
        method: 'PATCH',
        body: JSON.stringify({ display_name: displayName }),
      })
      auth.setIdentity(nextIdentity)
      setMessage('资料已保存')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">个人中心</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">账号身份由服务端统一管理。</p>
        <form onSubmit={save} className="mt-6 max-w-lg space-y-4">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">邮箱<input readOnly value={identity.user.email} className="mt-2 w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-gray-500 dark:border-white/[0.08] dark:bg-gray-950 dark:text-gray-400" /></label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">显示名称<input required maxLength={100} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-gray-950 outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" /></label>
          <div className="flex items-center gap-3"><button disabled={saving} className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60">{saving ? '保存中…' : '保存资料'}</button>{message && <span className="text-sm text-gray-500 dark:text-gray-400">{message}</span>}</div>
        </form>
      </section>
      <aside className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h2 className="font-bold text-gray-950 dark:text-white">当前团队</h2>
        <select value={identity.organization?.id || ''} onChange={(event) => auth.switchOrganization(event.target.value)} className="mt-3 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white">
          {identity.memberships.map((membership) => <option key={membership.id} value={membership.organization.id}>{membership.organization.name}</option>)}
        </select>
        <div className="mt-4 flex flex-wrap gap-2">{identity.role_codes.map((role) => <span key={role} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">{role}</span>)}</div>
        <button onClick={() => auth.logout()} className="mt-6 w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50 dark:border-white/[0.1] dark:text-gray-200 dark:hover:bg-white/[0.04]">退出登录</button>
      </aside>
    </div>
  )
}
