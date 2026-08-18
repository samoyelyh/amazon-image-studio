import { Link } from 'react-router-dom'

const steps = ['商品分析', 'Listing生成', '选择制作内容', '图片制作']

export default function WorkflowSteps({ current, sessionId, outputLabel }: { current: 1 | 2 | 3 | 4; sessionId?: string; outputLabel?: string }) {
  return <div className="mb-5 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-white/[0.08] dark:bg-gray-900">
    <div className="grid gap-2 sm:grid-cols-4">{steps.map((label, index) => {
      const number = index + 1
      const text = number === 4 && outputLabel ? outputLabel : label
      const active = number === current
      const complete = number < current
      const content = <div className={`rounded-xl px-3 py-2 text-sm font-semibold ${active ? 'bg-blue-600 text-white' : complete ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300' : 'bg-gray-50 text-gray-500 dark:bg-gray-950'}`}>
        <span className="mr-2">{number}.</span>{text}
      </div>
      if (!sessionId || (!complete && number !== 3)) return <div key={label}>{content}</div>
      const to = number <= 2 ? `/listing-workbench/${sessionId}` : number === 3 ? `/listing-workbench/${sessionId}/select-output` : ''
      return to ? <Link key={label} to={to}>{content}</Link> : <div key={label}>{content}</div>
    })}</div>
  </div>
}
