import { useEffect } from 'react'
import PasswordChangeForm from '../components/account/PasswordChangeForm'

export default function ChangePasswordPage() {
  useEffect(() => { document.title = '修改初始密码 · Amazon Image Studio' }, [])
  return <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-10 dark:bg-gray-950">
    <section className="w-full max-w-lg rounded-3xl border border-gray-200 bg-white p-7 shadow-xl shadow-gray-200/40 dark:border-white/[0.08] dark:bg-gray-900 dark:shadow-none">
      <div className="inline-flex rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">首次登录安全验证</div>
      <h1 className="mt-5 text-2xl font-bold tracking-tight text-gray-950 dark:text-white">请先修改初始密码</h1>
      <p className="mt-2 text-sm leading-6 text-gray-500 dark:text-gray-400">为了保护账号安全，完成修改前不能进入工作台。修改成功后会自动进入系统。</p>
      <div className="mt-7"><PasswordChangeForm forced /></div>
    </section>
  </main>
}
