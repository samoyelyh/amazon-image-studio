import { useEffect, useState } from 'react'
import type { BatchGarmentStyleProfile, BatchTryOnGarment, BatchTryOnTemplate } from '../types'
import { batchStyleProfileDisplay, batchStyleProfileSummary } from '../lib/batchTryOnStyleProfile'
import { ChevronDownIcon } from './icons'

interface BatchTryOnStyleAnalysisPanelProps {
  profiles: BatchGarmentStyleProfile[]
  garments: BatchTryOnGarment[]
  templates: BatchTryOnTemplate[]
  templateProfiles: Record<string, Record<string, unknown>>
  status?: string | null
}

export default function BatchTryOnStyleAnalysisPanel({
  profiles,
  garments,
  templates,
  templateProfiles,
  status,
}: BatchTryOnStyleAnalysisPanelProps) {
  const [expandedProfileKey, setExpandedProfileKey] = useState<string | null>(null)
  const isAnalyzing = Boolean(status?.startsWith('正在'))
  const hasProfiles = profiles.length > 0
  const templateEntries = Object.entries(templateProfiles)

  useEffect(() => {
    if (!profiles.length) {
      setExpandedProfileKey(null)
      return
    }
    if (!profiles.some((profile) => profile.profileKey === expandedProfileKey)) {
      setExpandedProfileKey(profiles[0].profileKey)
    }
  }, [expandedProfileKey, profiles])

  return (
    <section data-testid="batch-style-analysis" className="mt-4 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-950">
      <div className="flex flex-col gap-3 border-b border-gray-100 px-4 py-4 dark:border-white/[0.06] sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-300">
            <StyleAnalysisIcon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">AI 款式识别</h3>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${isAnalyzing ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-200' : hasProfiles ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-200' : 'bg-gray-100 text-gray-500 dark:bg-white/[0.06] dark:text-gray-400'}`}>
                {isAnalyzing ? '分析中' : hasProfiles ? `已识别 ${profiles.length} 个结构组` : '等待分析'}
              </span>
            </div>
            <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
              首件服装用于提取共用结构；颜色、文字、号码、姓名和具体图案始终以每件当前服装原图为准。
            </p>
          </div>
        </div>
        {status && <div className="shrink-0 rounded-lg bg-gray-50 px-2.5 py-1.5 text-xs text-gray-600 dark:bg-white/[0.04] dark:text-gray-300">{status}</div>}
      </div>

      {!hasProfiles ? (
        <div className="flex items-center gap-3 px-4 py-4 text-sm text-gray-500 dark:text-gray-400">
          {isAnalyzing
            ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-violet-200 border-t-violet-600" />
            : <span className="grid h-7 w-7 place-items-center rounded-lg bg-gray-100 text-xs font-bold text-gray-400 dark:bg-white/[0.05]">1</span>}
          <div>
            <div className="font-medium text-gray-600 dark:text-gray-300">{isAnalyzing ? '正在读取首件服装并建立批次结构规则…' : '生成组合时自动识别首件服装'}</div>
            {!isAnalyzing && <div className="mt-0.5 text-xs text-gray-400">识别完成后将在这里展示结构、正反面规则和保真规则。</div>}
          </div>
        </div>
      ) : (
        <div className="divide-y divide-gray-100 dark:divide-white/[0.06]">
          {profiles.map((profile, index) => {
            const display = batchStyleProfileDisplay(profile)
            const expanded = expandedProfileKey === profile.profileKey
            const sourceGarment = garments.find((garment) => garment.id === profile.sourceGarmentId)
              || garments.find((garment) => garment.serverAssetId === profile.sourceSampleAssetId)
            const coveredGarments = garments.filter((garment) => profile.coveredGarmentIds.includes(garment.id))
            const observation = profile.firstSampleObservation && Object.keys(profile.firstSampleObservation).length
              ? profile.firstSampleObservation
              : null
            return (
              <article key={profile.profileKey}>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setExpandedProfileKey(expanded ? null : profile.profileKey)}
                  className="flex w-full items-center gap-3 px-4 py-3.5 text-left transition hover:bg-gray-50/80 dark:hover:bg-white/[0.025]"
                >
                  <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-gray-100 text-xs font-bold text-gray-600 dark:bg-white/[0.06] dark:text-gray-300">{index + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">{display.category}</span>
                      <span className="rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-500/10 dark:text-blue-200">覆盖 {profile.coveredGarmentIds.length} 件服装</span>
                    </span>
                    <span className="mt-1 block truncate text-xs text-gray-500 dark:text-gray-400">{batchStyleProfileSummary(profile)}</span>
                  </span>
                  <ChevronDownIcon className={`h-4 w-4 shrink-0 text-gray-400 transition ${expanded ? 'rotate-180' : ''}`} />
                </button>

                {expanded && (
                  <div className="bg-gray-50/70 px-4 pb-4 pt-1 dark:bg-white/[0.018]">
                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
                      <div className="rounded-xl border border-gray-200 bg-white p-3 dark:border-white/[0.08] dark:bg-gray-950">
                        <div className="text-xs font-bold text-gray-700 dark:text-gray-200">识别出的结构</div>
                        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                          {display.structure.map((item) => <ResultField key={item.label} label={item.label} value={item.value} />)}
                          {!display.structure.length && <span className="col-span-full text-xs text-gray-400">AI 未返回具体结构字段</span>}
                        </div>
                        <div className="mt-3 border-t border-gray-100 pt-3 dark:border-white/[0.06]">
                          <div className="text-[11px] font-semibold text-gray-500">正反面规则</div>
                          <div className="mt-1.5 flex flex-wrap gap-1.5">{display.viewRules.map((rule) => <RuleTag key={rule}>{rule}</RuleTag>)}</div>
                        </div>
                      </div>

                      <div className="rounded-xl border border-gray-200 bg-white p-3 dark:border-white/[0.08] dark:bg-gray-950">
                        <div className="text-xs font-bold text-gray-700 dark:text-gray-200">生成时必须保持</div>
                        <div className="mt-2 flex flex-wrap gap-1.5">{display.preservationRules.map((rule) => <RuleTag key={rule}>{rule}</RuleTag>)}</div>
                        <div className="mt-3 rounded-lg bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-800 dark:bg-amber-500/10 dark:text-amber-100">
                          这些是“如何保护”的规则，不包含首件样本的具体颜色、号码、文字或图案。
                        </div>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-2 text-xs text-gray-500 dark:text-gray-400 sm:grid-cols-3">
                      <InfoItem label="结构样本" value={sourceGarment?.garmentFileName || '首件服装'} />
                      <InfoItem label="适用服装" value={coveredGarments.length ? summarizeGarments(coveredGarments) : `${profile.coveredGarmentIds.length} 件服装`} />
                      <InfoItem label="分析模型" value={`${profile.analysisModel || '平台文本模型'} · ${profile.analysisVersion}`} />
                    </div>

                    {observation && (
                      <details className="mt-3 rounded-xl border border-dashed border-gray-200 bg-white/70 p-3 dark:border-white/[0.08] dark:bg-gray-950/70">
                        <summary className="cursor-pointer text-xs font-semibold text-gray-500 dark:text-gray-400">首件样本观察（仅调试，不参与后续生成约束）</summary>
                        <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-950 p-3 text-[11px] leading-5 text-gray-200">{JSON.stringify(observation, null, 2)}</pre>
                      </details>
                    )}
                  </div>
                )}
              </article>
            )
          })}
        </div>
      )}

      {templateEntries.length > 0 && (
        <div className="border-t border-gray-100 px-4 py-4 dark:border-white/[0.06]">
          <div className="mb-3">
            <div className="text-xs font-bold text-gray-700 dark:text-gray-200">模板构图识别</div>
            <div className="mt-1 text-[11px] text-gray-400">用于锁定模板的视角、裁切、姿势、镜头距离、背景、光线与遮挡关系。</div>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {templateEntries.map(([templateId, profile]) => {
              const template = templates.find((item) => item.id === templateId || item.serverAssetId === profile.template_asset_id)
              const fields = templateProfileFields(profile)
              const occlusion = Array.isArray(profile.occlusion)
                ? profile.occlusion.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
                : []
              return (
                <article key={templateId} className="rounded-xl border border-gray-200 bg-gray-50/70 p-3 dark:border-white/[0.08] dark:bg-white/[0.025]">
                  <div className="flex items-center justify-between gap-3">
                    <div className="truncate text-xs font-bold text-gray-700 dark:text-gray-200">
                      {String(profile.template_name || template?.displayName || template?.fileName || templateId)}
                    </div>
                    <span className="shrink-0 rounded-md bg-white px-1.5 py-0.5 text-[10px] font-semibold text-gray-500 dark:bg-white/[0.06] dark:text-gray-300">
                      {String(profile.quality || 'unknown')}
                    </span>
                  </div>
                  {fields.length ? (
                    <>
                      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                        {fields.map((item) => <ResultField key={item.label} label={item.label} value={item.value} />)}
                      </div>
                      {occlusion.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {occlusion.map((item) => <RuleTag key={item}>{`遮挡：${item}`}</RuleTag>)}
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="mt-2 rounded-lg bg-amber-50 px-2.5 py-2 text-[11px] leading-5 text-amber-800 dark:bg-amber-500/10 dark:text-amber-100">
                      历史分析未返回有效模板结构。重新生成组合后，系统会按修复后的格式重新识别。
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}

function templateProfileFields(profile: Record<string, unknown>) {
  const candidates: Array<[string, unknown]> = [
    ['人物视角', profile.body_view],
    ['裁切范围', profile.crop_type],
    ['镜头角度', profile.camera_angle],
    ['镜头距离', profile.camera_distance],
    ['姿势', profile.pose],
    ['背景', profile.background],
    ['光线', profile.lighting],
    ['构图', profile.composition],
    ['聚焦区域', profile.focus_area],
    ['细节优先', profile.detail_priority],
  ]
  const concrete = candidates.filter(([label, value]) => (
    label !== '聚焦区域'
    && typeof value === 'string'
    && Boolean(value.trim())
    && value.trim().toLowerCase() !== 'unknown'
  ))
  if (!concrete.length) return []
  return candidates
    .filter(([, value]) => typeof value === 'string' && Boolean(value.trim()) && value.trim().toLowerCase() !== 'unknown')
    .map(([label, value]) => ({ label, value: String(value) }))
}

function ResultField({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-gray-50 px-2.5 py-2 dark:bg-white/[0.035]"><div className="text-[10px] text-gray-400">{label}</div><div className="mt-0.5 text-xs font-semibold text-gray-700 dark:text-gray-200">{value}</div></div>
}

function RuleTag({ children }: { children: string }) {
  return <span className="rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-[11px] font-medium text-gray-600 dark:border-white/[0.08] dark:bg-white/[0.035] dark:text-gray-300">{children}</span>
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg px-1 py-1"><span className="text-gray-400">{label}：</span><span className="font-medium text-gray-600 dark:text-gray-300">{value}</span></div>
}

function summarizeGarments(garments: BatchTryOnGarment[]) {
  const names = garments.slice(0, 3).map((garment) => garment.garmentFileName)
  return garments.length > 3 ? `${names.join('、')} 等 ${garments.length} 件` : names.join('、')
}

function StyleAnalysisIcon({ className }: { className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 9.7 8.2 4.5 10.5l5.2 2.3L12 18l2.3-5.2 5.2-2.3-5.2-2.3L12 3Z"/><path d="m5 3 .8 1.8L7.5 5.5l-1.7.7L5 8l-.8-1.8-1.7-.7 1.7-.7L5 3Z"/><path d="m18.5 16 .9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9.9-2.1Z"/></svg>
}
