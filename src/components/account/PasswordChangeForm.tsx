import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/AuthContext'
import { appRoutes } from '../../app/routes'
import { passwordRules } from '../../lib/passwordPolicy'

const inputClass = 'mt-2 w-full rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-gray-950 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'

export default function PasswordChangeForm({ forced = false }: { forced?: boolean }) {
  const auth = useAuth()
  const navigate = useNavigate()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [visible, setVisible] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState('')
  const rules = passwordRules(newPassword, auth.identity?.user.account, auth.identity?.user.display_name)
  const valid = rules.every((rule) => rule.passed) && confirmation === newPassword && currentPassword.length > 0

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!valid) return
    setSubmitting(true)
    setMessage('')
    try {
      await auth.changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      if (forced) navigate(appRoutes.dashboard, { replace: true })
      else setMessage('密码已修改，其他设备上的旧会话已失效。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '密码修改失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return <form className="space-y-4" onSubmit={submit}>
    <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">当前密码<input required type={visible ? 'text' : 'password'} autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className={inputClass} /></label>
    <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">新密码<input required minLength={12} type={visible ? 'text' : 'password'} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className={inputClass} /></label>
    <div className="grid gap-1.5 sm:grid-cols-2">{rules.map((rule) => <div key={rule.label} className={`text-xs ${rule.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-gray-400'}`}>{rule.passed ? '✓' : '○'} {rule.label}</div>)}</div>
    <label className="block text-sm font-medium text-gray-700 dark:text-gray-200">确认新密码<input required type={visible ? 'text' : 'password'} autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className={inputClass} /></label>
    {confirmation && confirmation !== newPassword && <div className="text-xs text-red-600">两次输入的新密码不一致</div>}
    <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300"><input type="checkbox" checked={visible} onChange={(event) => setVisible(event.target.checked)} />显示密码</label>
    {message && <div role="status" className={`rounded-xl px-3 py-2 text-sm ${message.startsWith('密码已修改') ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}>{message}</div>}
    <button className="w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={!valid || submitting}>{submitting ? '正在修改…' : '修改密码'}</button>
  </form>
}
