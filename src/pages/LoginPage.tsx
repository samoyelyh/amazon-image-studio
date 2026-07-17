import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/AuthContext'
import { appRoutes } from '../app/routes'
import { AuthApiError } from '../lib/authApi'

export default function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => { document.title = '登录 · Amazon Image Studio' }, [])

  if (auth.status === 'authenticated') return <Navigate to={appRoutes.dashboard} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await auth.login(email, password)
      const target = (location.state as { from?: string } | null)?.from || appRoutes.dashboard
      navigate(target, { replace: true })
    } catch (requestError) {
      setError(requestError instanceof AuthApiError ? requestError.message : '无法连接到登录服务')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10 dark:bg-gray-950">
      <section className="w-full max-w-md rounded-3xl border border-gray-200 bg-white p-7 shadow-xl shadow-gray-200/40 dark:border-white/[0.08] dark:bg-gray-900 dark:shadow-none">
        <div className="inline-flex rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">多人协作平台</div>
        <h1 className="mt-5 text-2xl font-bold tracking-tight text-gray-950 dark:text-white">登录 Amazon Image Studio</h1>
        <p className="mt-2 text-sm leading-6 text-gray-500 dark:text-gray-400">使用平台账号进入团队工作区。登录状态通过安全的刷新令牌恢复。</p>
        <form className="mt-7 space-y-4" onSubmit={submit}>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            邮箱
            <input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-gray-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" />
          </label>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">
            密码
            <input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-gray-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" />
          </label>
          {error && <div role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">{error}</div>}
          <button type="submit" disabled={submitting} className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60">
            {submitting ? '正在登录…' : '登录'}
          </button>
        </form>
      </section>
    </main>
  )
}
