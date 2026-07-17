import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useAuth } from '../app/AuthContext'
import { adjustQuota, estimateQuota, getQuotaAccount, getQuotaPackages, getQuotaReservations, getQuotaRules, getQuotaTransactions, type CostEstimate } from '../lib/quotaApi'

const transactionNames: Record<string, string> = { grant: '赠送', recharge: '充值', reserve: '预占', consume: '消费', release: '释放', refund: '退款', adjust: '调整', expire: '过期' }
const statusNames: Record<string, string> = { reserved: '已冻结', consumed: '已消费', partially_consumed: '部分消费', released: '已释放', refunded: '已退款', partially_refunded: '部分退款', expired: '已过期' }

function number(value: number) { return new Intl.NumberFormat('zh-CN').format(value) }
function time(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }

export default function QuotaPage() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const account = useQuery({ queryKey: ['quota', 'account'], queryFn: getQuotaAccount })
  const rules = useQuery({ queryKey: ['quota', 'rules'], queryFn: getQuotaRules })
  const transactions = useQuery({ queryKey: ['quota', 'transactions'], queryFn: getQuotaTransactions })
  const reservations = useQuery({ queryKey: ['quota', 'reservations'], queryFn: getQuotaReservations })
  const packages = useQuery({ queryKey: ['quota', 'packages'], queryFn: getQuotaPackages })
  const [operationCode, setOperationCode] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [quality, setQuality] = useState('standard')
  const [resolution, setResolution] = useState('1024')
  const [estimate, setEstimate] = useState<CostEstimate | null>(null)
  const [message, setMessage] = useState('')
  const [adjustAmount, setAdjustAmount] = useState(1000)
  const [adjustReason, setAdjustReason] = useState('人工额度调整')
  useEffect(() => { if (!operationCode && rules.data?.[0]) setOperationCode(rules.data[0].operation_code) }, [operationCode, rules.data])
  const estimateMutation = useMutation({
    mutationFn: () => estimateQuota({ operation_code: operationCode, quantity, quality, resolution, resource_pool: 'platform' }),
    onSuccess: (result) => { setEstimate(result); setMessage('') },
    onError: (error) => setMessage(error instanceof Error ? error.message : '费用预估失败'),
  })
  const adjustMutation = useMutation({
    mutationFn: () => adjustQuota({ transaction_type: 'adjust', amount: adjustAmount, reason: adjustReason, idempotency_key: `manual:${crypto.randomUUID()}` }),
    onSuccess: () => { setMessage('额度调整成功'); queryClient.invalidateQueries({ queryKey: ['quota'] }) },
    onError: (error) => setMessage(error instanceof Error ? error.message : '额度调整失败'),
  })
  const submitEstimate = (event: FormEvent) => { event.preventDefault(); if (operationCode) estimateMutation.mutate() }

  return (
    <div className="mt-6 space-y-5">
      <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
        <h1 className="text-xl font-bold text-gray-950 dark:text-white">额度中心</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">额度由服务端统一预估、冻结、结算和退款，页面不模拟扣减。</p>
        {account.isError && <div className="mt-4 text-sm text-red-500">{account.error.message}</div>}
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {[['可用额度', account.data?.available_balance ?? 0, 'text-blue-600 dark:text-blue-300'], ['冻结额度', account.data?.reserved_balance ?? 0, 'text-amber-600 dark:text-amber-300'], ['总余额', account.data?.balance ?? 0, 'text-gray-950 dark:text-white']].map(([label, value, color]) => <div key={String(label)} className="rounded-2xl bg-gray-50 p-4 dark:bg-gray-950"><div className="text-xs text-gray-500">{label}</div><div className={`mt-2 text-2xl font-bold ${color}`}>{account.isLoading ? '—' : number(value as number)}</div></div>)}
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
          <h2 className="font-bold text-gray-950 dark:text-white">费用预估</h2>
          <form onSubmit={submitEstimate} className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <select value={operationCode} onChange={(event) => setOperationCode(event.target.value)} className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white">{rules.data?.map((rule) => <option key={rule.id} value={rule.operation_code}>{rule.name}</option>)}</select>
            <input type="number" min={1} max={10000} value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} aria-label="数量" className="rounded-xl border border-gray-200 px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white" />
            <select value={quality} onChange={(event) => setQuality(event.target.value)} aria-label="质量" className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"><option value="standard">标准质量</option><option value="high">高质量</option></select>
            <select value={resolution} onChange={(event) => setResolution(event.target.value)} aria-label="分辨率" className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white"><option value="1024">1024</option><option value="2048">2048</option></select>
            <button disabled={!operationCode || estimateMutation.isPending} className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">{estimateMutation.isPending ? '计算中…' : '计算费用'}</button>
          </form>
          {estimate && <div className={`mt-4 rounded-2xl border p-4 ${estimate.sufficient ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-400/20 dark:bg-emerald-500/10' : 'border-red-200 bg-red-50 dark:border-red-400/20 dark:bg-red-500/10'}`}><div className="grid gap-3 sm:grid-cols-3"><div><div className="text-xs text-gray-500">预计生成</div><div className="mt-1 font-bold">{estimate.quantity} 个计费单元</div></div><div><div className="text-xs text-gray-500">预计消耗</div><div className="mt-1 font-bold">{number(estimate.estimated_cost)} 额度</div></div><div><div className="text-xs text-gray-500">当前可用</div><div className="mt-1 font-bold">{number(estimate.available_balance)} 额度</div></div></div><div className="mt-3 text-xs text-gray-500">单价 {estimate.unit_cost} · {estimate.sufficient ? '额度充足' : '额度不足'}</div></div>}
        </section>
        <aside className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
          <h2 className="font-bold text-gray-950 dark:text-white">额度套餐</h2><div className="mt-3 space-y-2">{packages.data?.map((item) => <div key={item.id} className="rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><div className="flex justify-between gap-3"><span className="text-sm font-semibold dark:text-white">{item.name}</span><span className="text-sm text-blue-600">{number(item.quota_amount)}</span></div><div className="mt-1 text-xs text-gray-500">¥{item.price} · 购买支付将在管理阶段接入</div></div>)}</div>
        </aside>
      </div>

      {auth.hasPermission('quota.manage') && <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 dark:border-amber-400/20 dark:bg-amber-500/10"><h2 className="font-bold text-amber-900 dark:text-amber-100">平台额度调整</h2><div className="mt-3 grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)_auto]"><input type="number" value={adjustAmount} onChange={(event) => setAdjustAmount(Number(event.target.value))} aria-label="调整额度" className="rounded-xl border border-amber-200 px-3 py-2 text-sm dark:border-amber-400/20 dark:bg-gray-950" /><input value={adjustReason} onChange={(event) => setAdjustReason(event.target.value)} aria-label="调整原因" className="rounded-xl border border-amber-200 px-3 py-2 text-sm dark:border-amber-400/20 dark:bg-gray-950" /><button onClick={() => adjustMutation.mutate()} disabled={!adjustAmount || !adjustReason.trim() || adjustMutation.isPending} className="rounded-xl bg-amber-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">确认调整</button></div></section>}
      {message && <div className="text-sm text-gray-600 dark:text-gray-300">{message}</div>}

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="border-b border-gray-200 px-5 py-4 font-bold dark:border-white/[0.08] dark:text-white">额度流水</div><div className="divide-y divide-gray-100 dark:divide-white/[0.06]">{transactions.data?.items.map((item) => <div key={item.id} className="flex items-center justify-between gap-4 px-5 py-3"><div><div className="text-sm font-semibold text-gray-900 dark:text-white">{transactionNames[item.transaction_type] ?? item.transaction_type}{item.operation_code ? ` · ${item.operation_code}` : ''}</div><div className="mt-1 text-xs text-gray-500">{time(item.created_at)}</div></div><div className={`text-right text-sm font-bold ${item.balance_delta > 0 ? 'text-emerald-600' : item.balance_delta < 0 ? 'text-red-600' : 'text-amber-600'}`}>{item.balance_delta > 0 ? '+' : ''}{item.balance_delta || `冻结 ${item.reserved_delta > 0 ? '+' : ''}${item.reserved_delta}`}</div></div>)}{!transactions.isLoading && !transactions.data?.items.length && <div className="py-10 text-center text-sm text-gray-500">暂无额度流水</div>}</div></section>
        <section className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900"><div className="border-b border-gray-200 px-5 py-4 font-bold dark:border-white/[0.08] dark:text-white">预占记录</div><div className="divide-y divide-gray-100 dark:divide-white/[0.06]">{reservations.data?.items.map((item) => <div key={item.id} className="px-5 py-3"><div className="flex justify-between gap-3"><span className="text-sm font-semibold text-gray-900 dark:text-white">{item.operation_code}</span><span className="text-xs font-semibold text-amber-600">{statusNames[item.status] ?? item.status}</span></div><div className="mt-1 text-xs text-gray-500">预占 {number(item.reserved_amount)} · 消费 {number(item.consumed_amount)} · 释放 {number(item.released_amount)}</div></div>)}{!reservations.isLoading && !reservations.data?.items.length && <div className="py-10 text-center text-sm text-gray-500">暂无预占记录</div>}</div></section>
      </div>
    </div>
  )
}
