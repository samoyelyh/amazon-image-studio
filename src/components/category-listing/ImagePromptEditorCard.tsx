import { useEffect, useRef, useState } from 'react'
import {
  getImagePromptItem, listImagePromptVersions, optimizeImagePrompt,
  restoreDefaultImagePrompt, restorePreviousImagePrompt, saveImagePromptItem,
  type ImagePromptItem, type ImagePromptVersion,
} from '../../lib/listingWorkflowApi'
import { randomUuid } from '../../lib/randomUuid'
import { useStore } from '../../store'
import AutoSaveIndicator, { type AutoSaveState } from './AutoSaveIndicator'

const field = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 px-3 py-2 text-sm font-semibold disabled:opacity-50 dark:border-white/[0.1] dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50'
const statusLabel: Record<string, string> = {
  draft: '初始版本', needs_optimization: '中文要求待优化', optimizing: '正在优化', optimized: '已 AI 优化', manually_edited: '英文已手动编辑',
}
function errorText(error: unknown) { return error instanceof Error ? error.message : '请求失败' }
function wait(ms: number) { return new Promise((resolve) => window.setTimeout(resolve, ms)) }

export default function ImagePromptEditorCard({
  projectType, projectId, sessionId, categoryId, itemCode, imageType, label, basePrompt, initialItem, onUpdate, onStatusChange,
}: {
  projectType: 'listing_image' | 'a_plus'; projectId: string; sessionId: string; categoryId: string
  itemCode: string; imageType: string; label: string; basePrompt: string; initialItem?: ImagePromptItem
  onUpdate?: (item: ImagePromptItem) => void; onStatusChange?: (itemCode: string, status: string) => void
}) {
  const showToast = useStore((state) => state.showToast)
  const mounted = useRef(true)
  const hydrated = useRef(false)
  const itemRef = useRef<ImagePromptItem | undefined>(initialItem)
  const latestRef = useRef({ chinese: initialItem?.chinese_editing_instruction || '', english: initialItem?.optimized_english_prompt || basePrompt, manual: false })
  const lastSavedSignature = useRef('')
  const timer = useRef<number | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const [item, setItem] = useState<ImagePromptItem | undefined>(initialItem)
  const [chinese, setChinese] = useState(initialItem?.chinese_editing_instruction || '')
  const [english, setEnglish] = useState(initialItem?.optimized_english_prompt || basePrompt)
  const [status, setStatus] = useState(initialItem?.status || 'draft')
  const [saveState, setSaveState] = useState<AutoSaveState>('idle')
  const [busy, setBusy] = useState(false)
  const [versions, setVersions] = useState<ImagePromptVersion[]>([])
  const [showHistory, setShowHistory] = useState(false)
  const promptReady = basePrompt.trim().length >= 20

  const apply = (value: ImagePromptItem, replaceDraft = true) => {
    itemRef.current = value; setItem(value); setStatus(value.status)
    if (replaceDraft) {
      setChinese(value.chinese_editing_instruction); setEnglish(value.optimized_english_prompt)
      latestRef.current = { chinese: value.chinese_editing_instruction, english: value.optimized_english_prompt, manual: value.status === 'manually_edited' }
      lastSavedSignature.current = JSON.stringify(latestRef.current)
    }
    onStatusChange?.(itemCode, value.status); onUpdate?.(value)
  }

  const queueSave = () => {
    queue.current = queue.current.then(async () => {
      if (!promptReady) return
      const draft = latestRef.current
      const signature = JSON.stringify(draft)
      if (signature === lastSavedSignature.current) return
      if (mounted.current) setSaveState('saving')
      try {
        const value = await saveImagePromptItem({
          project_type: projectType, project_id: projectId, session_id: sessionId, prompt_item_id: itemCode,
          category_id: categoryId, image_type: imageType, original_english_prompt: basePrompt,
          chinese_editing_instruction: draft.chinese, optimized_english_prompt: draft.english,
          manual_edit: draft.manual, expected_state_version: itemRef.current?.state_version,
        })
        itemRef.current = value
        lastSavedSignature.current = signature
        if (mounted.current) {
          setItem(value); onUpdate?.(value); onStatusChange?.(itemCode, value.status)
          setSaveState(JSON.stringify(latestRef.current) === signature ? 'saved' : 'dirty')
        }
      } catch (error) {
        if (mounted.current) { setSaveState('failed'); showToast(errorText(error), 'error') }
      }
    })
    return queue.current
  }

  useEffect(() => {
    mounted.current = true; hydrated.current = false
    const nextChinese = initialItem?.chinese_editing_instruction || ''
    const nextEnglish = initialItem?.optimized_english_prompt || basePrompt
    itemRef.current = initialItem; setItem(initialItem); setChinese(nextChinese); setEnglish(nextEnglish)
    setStatus(initialItem?.status || 'draft')
    latestRef.current = { chinese: nextChinese, english: nextEnglish, manual: initialItem?.status === 'manually_edited' }
    lastSavedSignature.current = JSON.stringify(latestRef.current)
    setSaveState(initialItem?.last_saved_at ? 'saved' : 'idle')
    hydrated.current = true
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
      if (lastSavedSignature.current !== JSON.stringify(latestRef.current)) void queueSave()
      mounted.current = false
    }
  }, [basePrompt, initialItem?.id])

  useEffect(() => {
    latestRef.current = { chinese, english, manual: status === 'manually_edited' }
    if (!hydrated.current || !promptReady) return
    if (JSON.stringify(latestRef.current) === lastSavedSignature.current) return
    setSaveState('dirty')
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void queueSave() }, 1000)
    return () => { if (timer.current) window.clearTimeout(timer.current) }
  }, [chinese, english, status, promptReady])

  const optimize = async () => {
    setBusy(true)
    try {
      await queueSave()
      const draft = latestRef.current
      let value = await optimizeImagePrompt({
        project_type: projectType, project_id: projectId, session_id: sessionId, prompt_item_id: itemCode,
        category_id: categoryId, image_type: imageType, original_english_prompt: basePrompt,
        chinese_editing_instruction: draft.chinese, optimized_english_prompt: draft.english,
        expected_state_version: itemRef.current?.state_version,
        idempotency_key: `prompt-optimize:${projectId}:${itemCode}:${randomUuid()}`,
      })
      apply(value)
      while (value.status === 'optimizing') { await wait(1200); value = await getImagePromptItem(value.id); apply(value) }
      if (value.status !== 'optimized') throw new Error(value.error_message || 'AI 优化失败，请重试')
      setSaveState('saved'); showToast('英文提示词已根据中文要求重新优化。', 'success')
    } catch (error) { showToast(errorText(error), 'error') } finally { setBusy(false) }
  }

  const restore = async (kind: 'previous' | 'default') => {
    if (!itemRef.current) return
    try { apply(await (kind === 'previous' ? restorePreviousImagePrompt(itemRef.current.id) : restoreDefaultImagePrompt(itemRef.current.id))); setSaveState('saved') }
    catch (error) { showToast(errorText(error), 'error') }
  }
  const toggleHistory = async () => {
    if (!itemRef.current) return
    if (!showHistory) setVersions(await listImagePromptVersions(itemRef.current.id))
    setShowHistory((value) => !value)
  }

  return <article className={`rounded-xl border p-4 ${status === 'needs_optimization' ? 'border-amber-400 bg-amber-50/40 dark:bg-amber-500/5' : 'border-gray-200 dark:border-white/[0.08]'}`}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold dark:text-white">{label}</h3><div className="flex flex-wrap items-center gap-2"><AutoSaveIndicator state={saveState} savedAt={item?.last_saved_at} onRetry={() => void queueSave()} /><span className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600 dark:bg-white/[0.08] dark:text-gray-300">{statusLabel[status] || status}{item?.current_version_number ? ` · V${item.current_version_number}` : ''}</span></div></div>
    {!promptReady && <p className="mt-3 rounded-lg bg-blue-50 p-2 text-xs text-blue-700">请先构建基础提示词，再填写中文创作要求。</p>}
    <label className="mt-4 block text-xs font-semibold text-gray-600">中文创作要求<textarea disabled={!promptReady} className={`${field} mt-1 min-h-28 disabled:bg-gray-100`} value={chinese} placeholder="使用中文描述希望增加、删除或调整的内容。修改后可点击 AI 优化。" onChange={(event) => { setChinese(event.target.value); setStatus('needs_optimization'); onStatusChange?.(itemCode, 'needs_optimization') }} onBlur={() => void queueSave()} /></label>
    {status === 'needs_optimization' && <p className="mt-2 text-xs font-semibold text-amber-700">中文要求已修改，请重新执行 AI 优化。</p>}
    <button className={`${primary} mt-3`} disabled={!promptReady || busy || !chinese.trim()} onClick={() => void optimize()}>{busy ? '正在理解中文要求并重构英文提示词…' : 'AI 优化英文提示词'}</button>
    <label className="mt-4 block text-xs font-semibold text-gray-600">最终英文图片提示词 <span className="font-normal text-gray-400">（该内容将发送给图片模型）</span><textarea disabled={!promptReady} className={`${field} mt-1 min-h-52 font-mono text-xs disabled:bg-gray-100`} value={english} onChange={(event) => { setEnglish(event.target.value); setStatus('manually_edited'); onStatusChange?.(itemCode, 'manually_edited') }} onBlur={() => void queueSave()} /></label>
    <div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={!item} onClick={() => void restore('previous')}>恢复上一版</button><button className={button} disabled={!item} onClick={() => void restore('default')}>恢复 Skill 默认提示词</button><button className={button} disabled={!item} onClick={() => void toggleHistory()}>{showHistory ? '收起版本' : '查看版本历史'}</button></div>
    {showHistory && <div className="mt-3 space-y-2 rounded-xl bg-gray-50 p-3 text-xs dark:bg-white/[0.04]">{versions.length ? versions.map((version) => <div key={version.id} className="flex justify-between"><span>V{version.version_number} · {version.optimizer_model || 'AI 模型'}</span><span>{new Date(version.optimized_at).toLocaleString()}</span></div>) : <p>暂无 AI 优化历史版本。</p>}</div>}
  </article>
}
