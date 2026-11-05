import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/AuthContext'
import { appRoutes } from '../app/routes'
import { AuthApiError } from '../lib/authApi'
import { SparklesIcon } from '../components/agent-control/AgentControlIcons'

export default function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [account, setAccount] = useState('')
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
      await auth.login(account, password)
      const target = (location.state as { from?: string } | null)?.from || appRoutes.dashboard
      navigate(target, { replace: true })
    } catch (requestError) {
      setError(requestError instanceof AuthApiError ? requestError.message : '无法连接到登录服务')
    } finally { setSubmitting(false) }
  }

  return <main className="lovart-shell flex min-h-screen bg-[#f7f7f5] text-gray-900 lg:grid lg:grid-cols-[1.1fr_1fr]">
    <section className="login-visual relative hidden overflow-hidden text-white lg:block">
      <img src={`${import.meta.env.BASE_URL}creative-assets/scene-creative.png`} alt="AI 创意视觉" className="absolute inset-0 h-full w-full object-cover opacity-70" />
      <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/15 to-black/20" />
      <div className="absolute inset-x-0 bottom-0 p-12 xl:p-16"><div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white text-gray-950"><SparklesIcon className="h-6 w-6" /></div><h2 className="mt-6 max-w-lg text-4xl font-semibold tracking-[-0.04em]">让团队的每个创意，<br />都成为专业图片。</h2><p className="mt-4 max-w-md text-sm leading-6 text-white/65">电商图片策划、生成、编辑与团队协作，在一个创作空间完成。</p></div>
    </section>
    <section className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
      <div className="w-full max-w-md">
        <div className="mb-10 flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white text-gray-950"><SparklesIcon className="h-5 w-5" /></span><div><p className="text-sm font-semibold">Amazon Image Studio</p><p className="mt-0.5 text-[11px] text-gray-500">AI 图片创作平台</p></div></div>
        <div className="inline-flex rounded-full border border-white/10 px-3 py-1 text-xs text-gray-400">团队协作空间</div>
        <h1 className="mt-5 text-3xl font-semibold tracking-[-0.035em]">欢迎回来</h1>
        <p className="mt-2 text-sm leading-6 text-gray-500">登录后继续你的图片创作与团队项目。</p>
        <form className="mt-8 space-y-5" onSubmit={submit}>
          <label className="block text-xs font-medium text-gray-400">账号<input type="text" autoComplete="username" minLength={3} maxLength={32} pattern="[A-Za-z0-9_-]+" required value={account} onChange={(event) => setAccount(event.target.value)} placeholder="请输入账号" className="mt-2 h-12 w-full rounded-xl border border-white/10 bg-[#1b1b1b] px-4 text-sm text-white outline-none transition focus:border-white/25" /></label>
          <label className="block text-xs font-medium text-gray-400">密码<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入密码" className="mt-2 h-12 w-full rounded-xl border border-white/10 bg-[#1b1b1b] px-4 text-sm text-white outline-none transition focus:border-white/25" /></label>
          {error && <div role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}
          <button type="submit" disabled={submitting} className="h-12 w-full rounded-full bg-white text-sm font-semibold text-gray-950 transition hover:bg-gray-200 disabled:cursor-wait disabled:opacity-50">{submitting ? '正在登录…' : '登录'}</button>
        </form>
        <p className="mt-8 text-center text-[11px] leading-5 text-gray-600">登录状态通过安全刷新令牌恢复，团队数据按权限隔离。</p>
      </div>
    </section>
  </main>
}
