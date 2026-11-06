import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/AuthContext'
import { runtimeConfig } from '../../app/runtimeConfig'
import AuthenticatedImage from '../AuthenticatedImage'
import { SharedQueueView } from '../BatchTryOnSharedQueue'
import type { SharedQueueBoard } from '../../lib/batchTryOnSharedQueueApi'
import { uploadAsset } from '../../lib/contentApi'
import { useImagePaste } from '../../hooks/useImagePaste'
import { AgentPlanCard, AgentResultGallery, chatButton } from './AgentChatCards'
import AgentCapabilityPanel from './AgentCapabilityPanel'
import AgentAmazonCard, { AmazonResearchStatus } from './AgentAmazonCard'
import type { AmazonPlanRecord, AmazonReceipt } from '../../lib/amazonAgentApi'
import {amazonCardRunId,isSavedAmazonDraft} from '../../lib/agentAmazonTimeline'
import AgentProductionCard, { productionCardRunId } from './AgentProductionCard'
import {AgentClarificationCard,AgentSuggestionsCard} from './AgentClarificationCard'
import AgentPromptPanel from './AgentPromptPanel'
import AgentBatchInputCard from './AgentBatchInputCard'
import AgentBusinessCards from './AgentBusinessCards'
import AgentMaterialImport from './AgentMaterialImport'
import {hasBatchPreparation,importWasSubmitted} from '../../lib/agentBatchPreparation'
import {activeImageStatuses} from '../../lib/agentImageProgress'
import {AuthApiError} from '../../lib/authApi'
import {prepareImportFiles,collectDroppedFiles,type ImportSource} from '../../lib/agentImportFiles'
import {creativeModules,automaticContext,type CreativeModule} from '../../lib/agentCreativeModules'
import {
  resumeAgentRun, setAgentController, agentRequestId, attachAgentImage, detachAgentImage, createAgentChat, confirmAgentRun,setAgentCreativeContext,
  getAgentContexts, getAgentConversation, getAgentLibrary, getAgentRun, getAgentStatus, listAgentConversations,
  sendAgentChatMessage, stopAgentRun, saveAgentPrompt, type AgentPrompt, type AgentRun, type AgentStatus, type AgentConversation, type AgentAttachment,
  type AgentChatMessage, type AgentContextOption, type AgentOutput, type AttachmentRole, type AgentProductionPlan,type MaterialImportInfo,type BatchInputManifest,
} from '../../lib/agentControlApi'
import { ChatIcon, ArrowUpIcon, PaperclipIcon, SearchIcon, SparklesIcon } from './AgentControlIcons'
import { ChevronDownIcon, CloseIcon, CopyIcon, ExternalLinkIcon, HistoryIcon, PhotoIcon, PlusIcon, SidebarLeftIcon, SidebarRightIcon } from '../icons'
export { AgentPlanCard } from './AgentChatCards'

const roles: Array<[AttachmentRole, string]> = [['reference', '创作参考'], ['template', '模板图'], ['garment', '服装原图'], ['front', '正面参考'], ['back', '背面参考'], ['detail', '细节参考'], ['font', '字体图 C']]
type UploadState = { id: string; file: File; info:MaterialImportInfo;assetId?:string;status: 'uploading' | 'failed'; error?: string }
const categories = [
  { label: '电商', prompt: '为这款产品制作一张高转化的电商主图，突出产品主体、材质和核心卖点。' },
  { label: '社媒营销', prompt: '为这款产品创作一张适合社交媒体发布的营销图片，画面简洁、有吸引力。' },
  { label: '品牌视觉', prompt: '围绕这款产品创建一组统一、专业的品牌视觉图片，保持配色和光影一致。' },
  { label: '创意图片', prompt: '以这款产品为主体创作一张有创意、有视觉冲击力的图片，保留产品辨识度。' },
]
const quickTools = [
  { title: '商品主图', description: '突出产品与核心卖点', image: 'product-main.png', contain: true, prompt: '为上传的产品生成一张简约高级的电商主图，产品主体清晰，光影自然，背景干净。' },
  { title: '场景创作', description: '让产品融入真实场景', image: 'scene-creative.png', contain: false, prompt: '保留产品外观和细节，为产品设计一个真实、有质感的商业使用场景。' },
  { title: '细节优化', description: '优化光影、材质与质感', image: 'image-editing.png', contain: false, prompt: '在保持产品主体和构图不变的前提下，优化图片的光影、材质和产品细节。' },
  { title: '批量套图', description: '模板与服装智能组合', image: 'batch-tryon.png', contain: true, prompt: '帮我把这些衣服全部套到这几个模板上。' },
]
const professionalTools = [
  { name: '批量套图', description: '服装与模板批量生产', href: '/workspaces/batch-tryon', image: 'batch-tryon.png' },
  { name: 'A+ 内容', description: 'Amazon A+ 模块设计', href: '/workspaces/aplus', image: 'aplus-visual.png' },
  { name: '自由裂变', description: '基于一张图延展创意', href: '/workspaces/listing/variations', image: 'variation-portrait.png' },
  { name: '素材提取', description: '提取产品与设计元素', href: '/material-extract', image: 'image-editing.png' },
  { name: '印花编辑', description: '印花图案与区域编辑', href: '/workspaces/print-design', image: 'abstract-creative.png' },
]
const stylePresets = [
  { name: '简约科技', image: 'clean-tech.png', prompt: '以简约科技风创作产品图片，使用冷色光、清晰层级和精准的产品细节。' },
  { name: '自然暖调', image: 'natural-warm.png', prompt: '以自然暖调创作产品图片，使用柔和日光、自然材质和舒适的产品氛围。' },
  { name: '明亮零售', image: 'bright-retail.png', prompt: '以明亮零售风创作产品图片，画面清爽、卖点明确，具有电商营销感。' },
  { name: '高级对比', image: 'premium-contrast.png', prompt: '以高级对比风创作产品图片，使用深色背景、精致金属质感和杂志式光影。' },
]

function ChatPanel() {
  const auth=useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [creative,setCreative]=useState(automaticContext)
  const [startNewTask,setStartNewTask]=useState(false)
  const [history, setHistory] = useState<AgentConversation[]>([])
  const [projects, setProjects] = useState<AgentContextOption[]>([])
  const [conversation, setConversation] = useState<AgentConversation | null>(null)
  const [messages, setMessages] = useState<AgentChatMessage[]>([])
  const [runs, setRuns] = useState<AgentRun[]>([])
  const [attachments, setAttachments] = useState<AgentAttachment[]>([])
  const [productionPlans, setProductionPlans] = useState<AgentProductionPlan[]>([])
  const [amazonPlans, setAmazonPlans] = useState<AmazonPlanRecord[]>([])
  const [amazonResearch, setAmazonResearch] = useState<AmazonReceipt[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [text, setText] = useState('')
  const [parent, setParent] = useState<AgentOutput | null>(null)
  const [uploads, setUploads] = useState<UploadState[]>([])
  const [preparingImport,setPreparingImport]=useState(false),[importNotice,setImportNotice]=useState('')
  const importing=useRef(false),continuedImports=useRef(new Set<string>())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [drawer, setDrawer] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historySearch, setHistorySearch] = useState('')
  const [library, setLibrary] = useState(false)
  const [librarySearch, setLibrarySearch] = useState('')
  const [libraryItems, setLibraryItems] = useState<Awaited<ReturnType<typeof getAgentLibrary>>>([])
  const mounted = useRef(true)
  const activeConversation = useRef<AgentConversation | null>(null)
  const epoch = useRef(0)
  const refreshSequence = useRef(0)
  const createPromise = useRef<Promise<AgentConversation> | null>(null)
  const sendKey = useRef<{ fingerprint: string; id: string } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const followingLatest=useRef(true)
  const [showLatest,setShowLatest]=useState(false)

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    const presetPrompt = new URLSearchParams(window.location.search).get('prompt')
    if (presetPrompt?.trim()) setText(presetPrompt.trim())
    void getAgentStatus(controller.signal).then(async (value) => {
      if (controller.signal.aborted) return
      setStatus(value)
      if (value.enabled) {
        const [conversations, contextOptions] = await Promise.all([listAgentConversations(controller.signal), getAgentContexts(controller.signal)])
        if (!controller.signal.aborted) {
          setHistory(conversations)
          setProjects(contextOptions)
          const id = new URLSearchParams(window.location.search).get('conversation_id')
          if (id) await refresh(id, epoch.current, true)
        }
      }
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message) })
    return () => { mounted.current = false; epoch.current++; controller.abort() }
  }, [])
  const outputCount=runs.reduce((n,r)=>n+(r.outputs?.length||0),0)
  const latestReply=messages[messages.length-1]?.content
  useEffect(() => { if(followingLatest.current)end.current?.scrollIntoView({ behavior: 'auto', block: 'end' }) }, [conversation?.id,messages.length,latestReply,outputCount])
  const waiting = runs.filter((run) => ['waiting_jobs','ready_to_submit','submitted','planning'].includes(run.status)
    ||run.jobs.some(j=>j.capability!=='text_generation'&&activeImageStatuses.has(j.status))).map((run) => run.id).join(',')
  useEffect(() => {
    if (!waiting) return
    const controller = new AbortController()
    const current = epoch.current
    let fetching = false
    const timer = setInterval(() => {
      if (fetching) return
      fetching = true
      void Promise.all(waiting.split(',').map((id) => getAgentRun(id, controller.signal))).then(async (values) => {
        if (controller.signal.aborted) return
        setRuns((old) => old.map((run) => values.find((value) => value.id === run.id) || run))
        if (activeConversation.current) await refresh(activeConversation.current.id, current)
      }).catch((reason) => { if (!controller.signal.aborted) setError(reason.message) }).finally(() => { fetching = false })
    }, 3000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [waiting])
  useEffect(() => {
    if (!library) return
    let active = true
    void getAgentLibrary(librarySearch).then((items) => { if (active) setLibraryItems(items) }).catch((reason) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [library, librarySearch])
  useEffect(() => {
    const closeOverlay = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setLibrary(false)
      setDrawer(false)
      setHistoryOpen(false)
    }
    window.addEventListener('keydown', closeOverlay)
    return () => window.removeEventListener('keydown', closeOverlay)
  }, [])

  function fail(reason: unknown) { if (mounted.current) setError(reason instanceof Error ? reason.message : String(reason)) }
  async function ensureConversation() {
    if (activeConversation.current) return activeConversation.current
    if (createPromise.current) return createPromise.current
    const currentEpoch = epoch.current
    createPromise.current = createAgentChat(undefined,creative.module==='auto'?undefined:creative.module).then((value) => {
      if (!mounted.current || currentEpoch !== epoch.current) throw new Error('已切换会话')
      activeConversation.current = value
      setConversation(value)
      setCreative(value.creative_context||automaticContext)
      setHistory((old) => [value, ...old])
      navigate(`/workspaces/agent-control?conversation_id=${encodeURIComponent(value.id)}`, { replace: true })
      return value
    }).finally(() => { createPromise.current = null })
    return createPromise.current
  }
  async function refresh(id: string, currentEpoch = epoch.current, restoreSelection = false) {
    const sequence = ++refreshSequence.current
    const detail = await getAgentConversation(id)
    if (!mounted.current || currentEpoch !== epoch.current || sequence !== refreshSequence.current) return
    activeConversation.current = detail
    setConversation(detail)
    setCreative(detail.creative_context||automaticContext)
    setHistory((old) => old.map((value) => value.id === detail.id ? detail : value))
    setMessages(detail.messages)
    setRuns(detail.runs)
    setProductionPlans(detail.production_plans || [])
    setAmazonPlans(detail.amazon_plans || [])
    setAmazonResearch(detail.amazon_research || [])
    setAttachments(detail.attachments || [])
    if (restoreSelection) setSelected((detail.attachments || []).filter((attachment) => !attachment.submitted).map((attachment) => attachment.id))
    navigate(`/workspaces/agent-control?conversation_id=${encodeURIComponent(id)}`, { replace: true })
  }
  async function openConversation(id: string) {
    if (busy || uploads.length) return
    epoch.current++
    const current = epoch.current
    setBusy(true)
    setError('')
    setSelected([])
    setParent(null)
    setText('')
    setStartNewTask(false)
    setHistoryOpen(false)
    followingLatest.current=true;setShowLatest(false)
    sendKey.current = null
    try { await refresh(id, current, true) } catch (reason) { fail(reason) } finally { if (mounted.current) setBusy(false) }
  }
  function newConversation() {
    if (busy || uploads.length) return
    epoch.current++
    activeConversation.current = null
    followingLatest.current=true;setShowLatest(false)
    setConversation(null)
    setCreative(automaticContext)
    setMessages([])
    setRuns([])
    setProductionPlans([])
    setAmazonPlans([])
    setAmazonResearch([])
    setAttachments([])
    setSelected([])
    setText('')
    setStartNewTask(false)
    setParent(null)
    setError('')
    setHistoryOpen(false)
    sendKey.current = null
    navigate('/workspaces/agent-control', { replace: true })
  }
  async function openProject(id: string) {
    setBusy(true)
    epoch.current++
    try {
      const value = await createAgentChat(id)
      setHistory((old) => [value, ...old])
      await refresh(value.id)
      setSelected([])
      setParent(null)
      setText('')
      setHistoryOpen(false)
    } catch (reason) { fail(reason) } finally { if (mounted.current) setBusy(false) }
  }
  async function startBatch(){
    if(busy)return
    setBusy(true);setError('')
    try{const value=await ensureConversation();await sendAgentChatMessage(value.id,{content:'开始批量换衣，请引导我上传模板图和服装主图。',client_request_id:agentRequestId(),attachment_ids:[],creative_module:'batch_tryon'});await refresh(value.id)}catch(reason){fail(reason)}finally{setBusy(false)}
  }
  async function chooseModule(module:CreativeModule){
    if(busy||uploads.length)return
    sendKey.current=null
    if(!conversation){setCreative({...automaticContext,module,label:creativeModules.find(m=>m.id===module)!.label});composer.current?.focus();return}
    setBusy(true);setError('');refreshSequence.current++
    try{setCreative(await setAgentCreativeContext(conversation.id,module,creative.revision))}catch(reason){fail(reason)}finally{setBusy(false)}
  }
  async function addAsset(assetId: string, role: AttachmentRole = 'reference',info?:MaterialImportInfo) {
    const current = epoch.current
    const value = await ensureConversation()
    const attachment = await attachAgentImage(value.id, assetId, role,info)
    if (!mounted.current || current !== epoch.current) return
    setAttachments((old) => [...old.filter((item) => item.id !== attachment.id), attachment])
    setSelected((old) => old.includes(attachment.id) ? old : [...old, attachment.id])
  }
  async function transferImports(pending:UploadState[],current:number){
    let index=0
    await Promise.all(Array.from({length:Math.min(3,pending.length)},async()=>{
      while(index<pending.length){const item=pending[index++]
        try{
          const assetId=item.assetId||(await uploadAsset(item.file,'product_reference','agent_chat')).id
          item.assetId=assetId
          if(!mounted.current||current!==epoch.current)return
          await addAsset(assetId,'reference',item.info)
          setUploads(old=>old.filter(v=>v.id!==item.id))
        }catch(reason){if(mounted.current&&current===epoch.current)setUploads(old=>old.map(v=>v.id===item.id?{...item,status:'failed',error:reason instanceof Error?reason.message:'上传失败'}:v))}
      }
    }))
  }
  async function uploadFiles(files:File[],source:ImportSource='auto'){
    if(!status?.enabled||importing.current||!files.length)return
    importing.current=true;setPreparingImport(true);setError('');setImportNotice('')
    const current=epoch.current
    try{
      const result=await prepareImportFiles(files,500-attachments.length-uploads.length)
      if(!mounted.current||current!==epoch.current)return
      if(result.skipped.length)setImportNotice(`已跳过 ${result.skipped.length} 个非图片文件：${result.skipped.slice(0,8).join('、')}${result.skipped.length>8?'…':''}`)
      if(!result.files.length){if(!result.skipped.length)setError('没有可导入的图片');return}
      const batchId=agentRequestId()
      const pending:UploadState[]=result.files.map(v=>({id:agentRequestId(),file:v.file,status:'uploading',info:{batch_id:batchId,total_files:result.files.length,source,relative_path:v.relativePath}}))
      setUploads(old=>[...old,...pending]);setPreparingImport(false)
      await transferImports(pending,current)
    }catch(reason){fail(reason)}finally{importing.current=false;if(mounted.current)setPreparingImport(false)}
  }
  async function continueImport(manifest:BatchInputManifest){
    const key=manifest.continuation_key
    if(key&&importWasSubmitted(runs,key)){continuedImports.current.add(key);return}
    if(!conversation||!key||busy||preparingImport||importing.current||uploads.length||hasBatchPreparation(runs)||creative.module!=='batch_tryon'||continuedImports.current.has(key))return
    continuedImports.current.add(key);setBusy(true)
    try{await sendAgentChatMessage(conversation.id,{content:'素材导入或关联已更新，请沿用本会话当前批量换衣要求，基于最新素材继续准备；每个模板先生成一张样图，生成后等我审核。',attachment_ids:[],use_batch_inputs:true,creative_module:'batch_tryon',client_request_id:'imports:'+key});setSelected([]);await refresh(conversation.id)}
    catch(reason){
      if(reason instanceof AuthApiError&&reason.code==='agent.import_preparation_pending'){
        continuedImports.current.delete(key)
        await refresh(conversation.id)
      }else fail(reason)
    }finally{setBusy(false)}
  }
  const paste = useImagePaste({ disabled: !status?.enabled || busy, maxFiles: 500, onPasteFiles: uploadFiles })
  async function changeRole(attachment: AgentAttachment, role: AttachmentRole) {
    if (!conversation || attachment.submitted) return
    try {
      const updated = await attachAgentImage(conversation.id, attachment.asset_id, role)
      setAttachments((old) => old.map((value) => value.id === updated.id ? updated : value))
    } catch (reason) { fail(reason) }
  }
  async function removeAttachment(attachment: AgentAttachment) {
    if (!conversation) return
    try {
      if (!attachment.submitted) {
        await detachAgentImage(conversation.id, attachment.id)
        setAttachments((old) => old.filter((value) => value.id !== attachment.id))
      }
      setSelected((old) => old.filter((id) => id !== attachment.id))
    } catch (reason) { fail(reason) }
  }
  async function send(mode:'create'|'suggest'='create',followup?:{run:AgentRun;content:string}) {
    const content=(followup?.content??text).trim()
    if (busy || preparingImport||!content || uploads.some((upload) => upload.status === 'uploading')) return
    followingLatest.current=true;setShowLatest(false)
    setBusy(true)
    setError('')
    const current = epoch.current
    const input = { content, attachment_ids: followup?[]:selected.slice(0,50), use_batch_inputs:!followup&&selected.length>50, parent_output_id: followup?null:parent?.id || null,
      ...(!followup&&startNewTask&&status?.auto_execution?.mode==='autonomous'?{start_new_task:true}:{}),
      ...(mode==='suggest'?{request_mode:mode}:{}),...(followup?{reply_to_run_id:followup.run.id,reply_to_revision:followup.run.revision}:{}) }
    const fingerprint = JSON.stringify(input)
    if (sendKey.current?.fingerprint !== fingerprint) sendKey.current = { fingerprint, id: agentRequestId() }
    try {
      const value = await ensureConversation()
      await sendAgentChatMessage(value.id, { ...input, client_request_id: sendKey.current.id })
      if (!mounted.current || current !== epoch.current) return
      if(!followup){setText('');setSelected([]);setParent(null);setStartNewTask(false)}
      sendKey.current = null
      await refresh(value.id, current)
    } catch (reason) { fail(reason) } finally { if (mounted.current) setBusy(false) }
  }
  async function runAction(run: AgentRun, stop = false, resume = false) {
    setBusy(true)
    setError('')
    const current = epoch.current
    try {
      const value = await (resume ? resumeAgentRun(run.id) : stop ? stopAgentRun(run.id) : confirmAgentRun(run))
      if (!mounted.current || current !== epoch.current) return
      setRuns((old) => old.map((item) => item.id === value.id ? value : item))
      if (conversation) await refresh(conversation.id, current)
    } catch (reason) { fail(reason) } finally { if (mounted.current) setBusy(false) }
  }
  async function retryImage(jobId:string){
    if(busy||!conversation)return
    setBusy(true);setError('');const current=epoch.current
    try{
      await sendAgentChatMessage(conversation.id,{content:'仅重新生成这张失败图片，其他图片保持不变。',attachment_ids:[],
        client_request_id:agentRequestId(),retry_image_job_id:jobId})
      if(current===epoch.current)await refresh(conversation.id,current)
    }catch(reason){fail(reason)}finally{if(mounted.current)setBusy(false)}
  }
  function edit(image: AgentOutput) { setParent(image); setText(''); composer.current?.focus() }

  async function savePrompt(run:AgentRun,source:AgentPrompt,content:string){
    const current=epoch.current
    const next=await saveAgentPrompt(run,source.id,content)
    if(mounted.current&&current===epoch.current)setRuns(old=>old.map(r=>r.id===next.id?next:r))
    return next
  }
  async function generateSavedPrompt(run:AgentRun,version:AgentPrompt){
    if(busy)return
    setBusy(true);setError('')
    const current=epoch.current
    const input={content:`使用提示词 V${version.version}生成图片`,attachment_ids:[],prompt_source_run_id:run.id,prompt_version_id:version.id,review_before_generation:false}
    const fingerprint=JSON.stringify(input)
    if(sendKey.current?.fingerprint!==fingerprint)sendKey.current={fingerprint,id:agentRequestId()}
    try{
      const value=await ensureConversation()
      await sendAgentChatMessage(value.id,{...input,client_request_id:sendKey.current.id})
      if(!mounted.current||current!==epoch.current)return
      sendKey.current=null
      await refresh(value.id,current)
    }catch(reason){fail(reason)}finally{if(mounted.current)setBusy(false)}
  }

  function renderConversationSidebar() {
    const filteredHistory = history.filter((item) => item.title.toLowerCase().includes(historySearch.trim().toLowerCase()))
    return <>
      <div className="p-4 pb-3">
        <button className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#282825] px-4 text-sm font-medium text-white shadow-sm transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-gray-900" onClick={newConversation} disabled={busy || uploads.length > 0}><PlusIcon className="h-4 w-4" />新建创作</button>
        <label className="mt-4 flex h-10 items-center gap-2 rounded-xl bg-[#f3f3f0] px-3 text-gray-400 dark:bg-white/[0.05]">
          <SearchIcon className="h-4 w-4 shrink-0" />
          <input aria-label="搜索历史对话" value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} placeholder="搜索对话" className="min-w-0 flex-1 bg-transparent text-xs text-gray-700 outline-none placeholder:text-gray-400 dark:text-gray-200" />
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <div className="mb-2 flex items-center gap-2 px-2 text-[11px] font-medium text-gray-400"><HistoryIcon className="h-3.5 w-3.5" />最近对话</div>
        <div className="space-y-1">
          {filteredHistory.map((item) => <button key={item.id} disabled={busy || uploads.length > 0} className={`group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-xs transition ${conversation?.id === item.id ? 'bg-[#e9e9e4] font-medium text-gray-900 dark:bg-white/10 dark:text-white' : 'text-gray-500 hover:bg-black/[0.035] hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white'}`} onClick={() => void openConversation(item.id)}>
            <ChatIcon className="h-4 w-4 shrink-0 opacity-50" /><span className="truncate">{item.title}{item.context_kind !== 'chat' ? ' · 旧版' : ''}</span>
          </button>)}
          {!filteredHistory.length && <p className="px-3 py-6 text-center text-xs text-gray-400">{history.length ? '没有匹配的对话' : '你的创作对话会显示在这里'}</p>}
        </div>
      </div>
      <div className="border-t border-black/[0.06] p-3 dark:border-white/[0.07]">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg px-2 py-2 text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white"><span>历史项目</span><ChevronDownIcon className="h-3.5 w-3.5 transition group-open:rotate-180" /></summary>
          <div className="mt-1 max-h-40 overflow-y-auto">{projects.map((project) => <button key={project.id} disabled={busy} className="w-full truncate rounded-lg px-2 py-2 text-left text-xs text-gray-500 hover:bg-black/[0.04] dark:text-gray-400 dark:hover:bg-white/5" onClick={() => void openProject(project.id)}>{project.name}</button>)}</div>
        </details>
        <Link className="mt-1 flex items-center justify-between rounded-lg px-2 py-2 text-xs text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white" to="/workspaces/batch-tryon">专业工作台<ExternalLinkIcon className="h-3.5 w-3.5" /></Link>
      </div>
    </>
  }

  function renderComposer(empty = false) {
    return <div {...paste} onDragOver={(event) => { event.preventDefault() }} onDrop={(event) => { event.preventDefault(); void collectDroppedFiles(event.dataTransfer).then(files=>uploadFiles(files)).catch(fail) }} className="rounded-[22px] border border-black/[0.09] bg-white p-3 shadow-[0_12px_40px_rgba(39,39,35,0.08)] transition focus-within:border-black/20 focus-within:shadow-[0_14px_44px_rgba(39,39,35,0.11)] dark:border-white/10 dark:bg-gray-900 dark:focus-within:border-white/25">
      {!startNewTask&&!parent&&!selected.length&&['awaiting_clarification','awaiting_review'].includes(runs[0]?.status||'')&&<div className="mb-2 flex items-center justify-between rounded-xl bg-stone-100 px-3 py-2 text-sm"><span>继续补充上一个任务，沿用原图片与方案</span><button type="button" className={chatButton} onClick={()=>setStartNewTask(true)}>改为新任务</button></div>}
      {parent && <div className="mb-3 flex items-center gap-3 rounded-xl bg-[#f4f2ed] p-2.5 text-xs text-gray-600 dark:bg-white/[0.05] dark:text-gray-300">
        <AuthenticatedImage src={parent.content_url} alt="编辑底图" className="h-11 w-11 shrink-0 rounded-lg bg-white object-contain" />
        <div className="min-w-0"><p className="font-medium">以此图为基础继续创作</p><p className="mt-0.5 text-[11px] text-gray-400">图片 {parent.number} · v{parent.version}</p></div>
        <button aria-label="取消引用图片" className="ml-auto rounded-full p-1.5 hover:bg-black/5 dark:hover:bg-white/10" onClick={() => setParent(null)}><CloseIcon className="h-4 w-4" /></button>
      </div>}
      {(attachments.some((attachment) => selected.includes(attachment.id)) || uploads.length > 0) && <div className="mb-2 flex gap-2 overflow-x-auto pb-2">
        {attachments.filter((attachment) => selected.includes(attachment.id)).map((attachment) => <div key={attachment.id} className="relative w-[104px] shrink-0 overflow-hidden rounded-xl border border-black/[0.07] bg-[#fafaf8] dark:border-white/10 dark:bg-white/[0.03]">
          <AuthenticatedImage src={attachment.content_url} alt={attachment.filename} className="h-[72px] w-full object-contain" />
          <div className="px-2 pb-1.5 pt-1"><p className="truncate text-[10px] text-gray-500">{attachment.filename}</p><select aria-label={`${attachment.filename} 图片角色`} disabled={attachment.submitted || busy} className="mt-0.5 w-full cursor-pointer bg-transparent text-[10px] text-gray-400 outline-none" value={attachment.role} onChange={(event) => void changeRole(attachment, event.target.value as AttachmentRole)}>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          <button aria-label={`移除附件 ${attachment.filename}`} className="absolute right-1.5 top-1.5 rounded-full bg-white/90 p-1 text-gray-500 shadow-sm dark:bg-gray-800/90" onClick={() => void removeAttachment(attachment)}><CloseIcon className="h-3 w-3" /></button>
        </div>)}
        {uploads.map((upload) => <div key={upload.id} className="flex w-[140px] shrink-0 flex-col justify-center rounded-xl border border-black/[0.07] bg-[#fafaf8] p-2.5 text-xs dark:border-white/10 dark:bg-white/[0.03]"><p className="truncate">{upload.file.name}</p><p className={`mt-1 text-[10px] ${upload.status === 'failed' ? 'text-red-500' : 'text-gray-400'}`}>{upload.status === 'uploading' ? '正在上传…' : upload.error}</p>{upload.status === 'failed' && <button className="mt-1 self-start text-[11px] font-medium text-red-500" onClick={() => { setUploads(old=>old.map(v=>v.id===upload.id?{...v,status:'uploading'}:v)); void transferImports([upload],epoch.current) }}>重试</button>}</div>)}
      </div>}
      {preparingImport&&<p role="status" className="px-2 py-1 text-sm">正在检查并展开素材…</p>}
      {importNotice&&<p role="status" className="px-2 py-1 text-sm text-amber-700">{importNotice}</p>}
      <textarea ref={composer} aria-label="发送创作需求" rows={empty ? 3 : 2} value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} className="max-h-40 min-h-[68px] w-full resize-none bg-transparent px-2 py-1.5 text-[15px] leading-7 text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-100" placeholder={parent ? '告诉我这张图需要怎么修改…' : '描述你想创作的图片，也可以粘贴或上传参考图…'} />
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <input ref={fileInput} className="hidden" type="file" multiple accept="image/jpeg,image/png,image/webp,.zip,application/zip" onChange={(event) => { void uploadFiles(Array.from(event.target.files || [])); event.target.value = '' }} />
          {creative.module!=='batch_tryon'&&<button aria-label="上传图片" title="上传图片" className="inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-black/[0.04] hover:text-gray-900 disabled:opacity-40 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white" disabled={!status?.enabled || busy||preparingImport} onClick={() => fileInput.current?.click()}><PaperclipIcon className="h-[18px] w-[18px]" /><span className="hidden sm:inline">上传图片</span></button>}
          {creative.module==='batch_tryon'&&<AgentMaterialImport disabled={!status?.enabled||busy||preparingImport||uploads.length>0} onImport={(files,source)=>void uploadFiles(files,source)}/>}
          <button className="inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-black/[0.04] hover:text-gray-900 disabled:opacity-40 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white" onClick={() => setLibrary(true)} disabled={!status?.enabled || busy}><PhotoIcon className="h-[18px] w-[18px]" />素材库</button>
          <button type="button" className={chatButton} title={status?.creative_assistance_enabled?'仅生成文字建议':'服务端尚未启用 AI 建议'} disabled={busy||!text.trim()||!status?.creative_assistance_enabled||!status.checkpoint_configured||uploads.some(u=>u.status==='uploading')} onClick={()=>void send('suggest')}>AI 帮我完善</button>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-[10px] text-gray-400 md:inline">Enter 发送 · Shift + Enter 换行</span>
          <button aria-label="发送" className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#282825] text-white shadow-sm transition hover:scale-[1.03] hover:bg-black disabled:cursor-not-allowed disabled:opacity-25 disabled:hover:scale-100 dark:bg-white dark:text-gray-900" disabled={busy || preparingImport||!text.trim() || !status?.enabled || !status.checkpoint_configured || uploads.some((upload) => upload.status === 'uploading')} onClick={() => void send()}>{busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <ArrowUpIcon className="h-5 w-5" />}</button>
        </div>
      </div>
    </div>
  }

  const runById = new Map(runs.map((run) => [run.id, run]))
  const answeredRuns=new Set<string>()
  for(const message of messages){
    if(message.role!=='user'||message.metadata?.request_mode==='suggest')continue
    let id=message.metadata?.reply_to_run_id
    for(let i=0;id&&i<12&&!answeredRuns.has(id);i++){
      answeredRuns.add(id);id=runById.get(id)?.result.reply_context?.source_run_id
    }
  }
  const lastMessage = new Map(messages.filter((message) => message.metadata?.run_id).map((message) => [message.metadata!.run_id, message.id]))
  const replyRuns=new Set(messages.filter(m=>m.role!=='user'&&m.metadata?.run_id).map(m=>m.metadata!.run_id!))
  const amazonOwners=new Map(amazonPlans.map(p=>[p.id,amazonCardRunId(runs,p)]))
  const orphanPlans=amazonPlans.filter(p=>!replyRuns.has(amazonOwners.get(p.id)||''))
  if (status && !status.enabled) return <div className="mx-auto max-w-3xl p-8"><h1 className="text-2xl font-semibold">AI 总控</h1><p className="my-4 text-gray-500">当前服务尚未启用总控。原批量套图和附图工作台不受影响。</p><Link className={chatButton} to="/workspaces/batch-tryon">进入批量套图</Link></div>

  return <main className="relative flex h-full min-h-0 overflow-hidden bg-[#f8f8f6] text-[#292927] dark:bg-gray-950 dark:text-gray-100">
    <nav aria-label="创作导航" className="hidden w-16 shrink-0 flex-col items-center border-r border-black/[0.06] bg-[#f1f1ee] px-2 py-4 lg:flex dark:border-white/[0.07] dark:bg-gray-900/60">
      <div className="mb-5 flex h-9 w-9 items-center justify-center rounded-xl bg-[#292927] text-white dark:bg-white dark:text-gray-900"><SparklesIcon className="h-5 w-5" /></div>
      <span title={status?.controller==='dsh'?'DSH SuperAgent · K2.8':'LangGraph'} className="mb-2 text-[10px] font-semibold">{status?.controller==='dsh'?'DSH':'LG'}</span>
      <button aria-label="新建创作" title="新建创作" className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-white text-gray-700 shadow-sm transition hover:scale-105 disabled:opacity-40 dark:bg-white/10 dark:text-gray-200" onClick={newConversation} disabled={busy || uploads.length > 0}><PlusIcon className="h-5 w-5" /></button>
      <button aria-label="创作首页" title="创作首页" className={`flex h-10 w-10 items-center justify-center rounded-xl transition ${messages.length === 0 ? 'bg-black/[0.07] text-gray-900 dark:bg-white/10 dark:text-white' : 'text-gray-400 hover:bg-black/[0.04] hover:text-gray-800 dark:hover:bg-white/5 dark:hover:text-white'}`} onClick={newConversation} disabled={busy || uploads.length > 0}><SparklesIcon className="h-5 w-5" /></button>
      <button aria-label="历史对话" title="历史对话" className="mt-1 flex h-10 w-10 items-center justify-center rounded-xl text-gray-400 transition hover:bg-black/[0.04] hover:text-gray-800 dark:hover:bg-white/5 dark:hover:text-white" onClick={() => setHistoryOpen(true)}><HistoryIcon className="h-5 w-5" /></button>
      <button aria-label="打开素材库" title="素材库" className="mt-1 flex h-10 w-10 items-center justify-center rounded-xl text-gray-400 transition hover:bg-black/[0.04] hover:text-gray-800 disabled:opacity-40 dark:hover:bg-white/5 dark:hover:text-white" onClick={() => setLibrary(true)} disabled={!status?.enabled || busy}><PhotoIcon className="h-5 w-5" /></button>
      <Link aria-label="素材中心" title="素材中心" className="mt-1 flex h-10 w-10 items-center justify-center rounded-xl text-gray-400 transition hover:bg-black/[0.04] hover:text-gray-800 dark:hover:bg-white/5 dark:hover:text-white" to="/assets"><CopyIcon className="h-5 w-5" /></Link>
      <div className="mt-auto flex flex-col items-center gap-1">
        <button aria-label="素材与执行详情" title="素材与执行详情" className="flex h-10 w-10 items-center justify-center rounded-xl text-gray-400 transition hover:bg-black/[0.04] hover:text-gray-800 dark:hover:bg-white/5 dark:hover:text-white" onClick={() => setDrawer(true)}><SidebarRightIcon className="h-5 w-5" /></button>
        <Link aria-label="专业工作台" title="专业工作台" className="flex h-10 w-10 items-center justify-center rounded-xl text-gray-400 transition hover:bg-black/[0.04] hover:text-gray-800 dark:hover:bg-white/5 dark:hover:text-white" to="/workspaces/batch-tryon"><ExternalLinkIcon className="h-5 w-5" /></Link>
      </div>
    </nav>
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-black/[0.055] bg-[#f8f8f6]/90 px-3 sm:px-5 dark:border-white/[0.07] dark:bg-gray-950/90">
        <div className="flex min-w-0 items-center gap-2.5">
          <button aria-label="打开历史对话" className="rounded-full p-2 hover:bg-black/[0.04] lg:hidden dark:hover:bg-white/5" onClick={() => setHistoryOpen(true)}><SidebarLeftIcon className="h-5 w-5" /></button>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-[#e9e5dc] text-[#796749] dark:bg-white/10 dark:text-gray-300"><SparklesIcon className="h-[18px] w-[18px]" /></div>
          <div className="min-w-0"><h1 className="text-sm font-semibold">AI 总控</h1><p className="truncate text-[11px] text-gray-400">{conversation?.title || '你的对话式图片创作助手'}</p></div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <select aria-label="当前专业模块" className="max-w-32 rounded-full border bg-white px-3 py-2 text-xs" disabled={busy||uploads.length>0} value={creative.module} onChange={e=>void chooseModule(e.target.value as CreativeModule)}>{creativeModules.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}</select>
          <button className="inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-black/[0.04] hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white" onClick={() => setDrawer(true)}><SidebarRightIcon className="h-[18px] w-[18px]" /><span className="hidden sm:inline">素材与详情</span></button>
          <Link aria-label="专业工作台" className="inline-flex h-9 items-center gap-1.5 rounded-full px-2.5 text-xs text-gray-500 transition hover:bg-black/[0.04] hover:text-gray-900 dark:text-gray-400 dark:hover:bg-white/5 dark:hover:text-white" to="/workspaces/batch-tryon"><span className="hidden md:inline">专业工作台</span><ExternalLinkIcon className="h-4 w-4" /></Link>
        </div>
      </header>
      {(error || uploads.some((upload) => upload.status === 'failed')) && <div role="alert" className="relative z-10 mx-3 mt-3 flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-xs leading-5 text-red-700 sm:mx-5 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300"><span className="flex-1">{error || '部分附件上传失败，可重试或移除失败项后继续。'}</span><button aria-label="关闭错误并移除失败上传" className="shrink-0 rounded-full p-0.5 hover:bg-red-100 dark:hover:bg-red-900/40" onClick={() => { setError(''); setUploads((old) => old.filter((upload) => upload.status === 'uploading')) }}><CloseIcon className="h-4 w-4" /></button></div>}
      {messages.length === 0 ? <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-10 pt-8 sm:px-8 sm:pt-10 lg:pt-12">
        <div className="mx-auto w-full max-w-[1220px]">
          <div className="mx-auto max-w-[780px] text-center">
            <h2 className="text-xl font-medium tracking-[-0.025em] text-[#292927] sm:text-2xl dark:text-gray-100">欢迎来到 AI 创作</h2>
            <p className="mt-2 text-xs text-gray-400 sm:text-sm">告诉我你想做什么，或从一个创作工具开始</p>
            <div aria-label="选择专业创作模块" className="mt-4 flex flex-wrap justify-center gap-2">{creativeModules.filter(m=>m.id!=='auto').map(m=><button key={m.id} aria-pressed={creative.module===m.id} disabled={busy||uploads.length>0} className={`rounded-full border px-4 py-2 text-sm ${creative.module===m.id?'border-gray-900 bg-gray-900 text-white':'bg-white text-gray-800'}`} onClick={()=>m.id==='batch_tryon'?void startBatch():void chooseModule(m.id)}>{m.label}</button>)}</div>
            <div className="mt-6 text-left">{renderComposer(true)}</div>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {categories.map((category) => <button key={category.label} disabled={busy} className="rounded-full border border-black/[0.08] bg-white/50 px-4 py-2 text-xs text-gray-500 transition hover:border-black/20 hover:bg-white hover:text-gray-900 dark:border-white/10 dark:bg-white/[0.03] dark:text-gray-400 dark:hover:bg-white/[0.08] dark:hover:text-white" onClick={() => { void chooseModule(category.label==='电商'?'listing_images':'free_creation');setText(category.prompt); composer.current?.focus() }}>{category.label}</button>)}
            </div>
          </div>
          <section aria-label="快捷创作工具" className="mt-10 sm:mt-12">
            <div className="mb-3 flex items-end justify-between"><div><h3 className="text-sm font-semibold">快捷创作</h3><p className="mt-1 text-[11px] text-gray-400">选择场景，继续描述你的想法</p></div><SparklesIcon className="h-4 w-4 text-gray-300" /></div>
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              {quickTools.map((tool) => <button key={tool.title} className="lovart-image-card group text-left" disabled={busy} onClick={() => { if(tool.title==='批量套图'){void startBatch();return}void chooseModule(tool.title==='细节优化'?'image_edit':'listing_images');setText(tool.prompt); composer.current?.focus() }}>
                <div className={`relative aspect-[1.45] overflow-hidden ${tool.contain ? 'bg-[#eeeeeb] p-6' : 'bg-[#242424]'}`}>
                  <img src={`${import.meta.env.BASE_URL}creative-assets/${tool.image}`} alt={`${tool.title}示例`} className={`h-full w-full ${tool.contain ? 'object-contain' : 'object-cover'}`} />
                  <span className="absolute left-3 top-3 rounded-full border border-white/15 bg-black/35 px-2.5 py-1 text-[10px] text-white/80 backdrop-blur-sm">AI 创作</span>
                </div>
                <div className="p-3"><p className="text-xs font-medium sm:text-sm">{tool.title}</p><p className="mt-0.5 truncate text-[10px] text-gray-500 sm:text-[11px]">{tool.description}</p></div>
              </button>)}
            </div>
          </section>
          <section aria-label="专业创作工具" className="mt-10 sm:mt-12">
            <div className="mb-3 flex items-end justify-between"><div><h3 className="text-sm font-semibold">专业创作工具</h3><p className="mt-1 text-[11px] text-gray-400">进入完整工作台，处理复杂的电商图片生产</p></div><span className="hidden text-[11px] text-gray-400 sm:inline">也可直接在对话中交给 Agent 调度</span></div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
              {professionalTools.map((tool) => <Link key={tool.href} to={tool.href} className="group flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.035] p-3 transition hover:border-white/[0.16] hover:bg-white/[0.06]">
                <div className="h-11 w-11 shrink-0 overflow-hidden rounded-xl bg-[#eeeeeb]"><img src={`${import.meta.env.BASE_URL}creative-assets/${tool.image}`} alt="" className="h-full w-full object-cover" /></div>
                <div className="min-w-0"><div className="flex items-center gap-1"><span className="truncate text-xs font-semibold sm:text-sm">{tool.name}</span><ExternalLinkIcon className="h-3 w-3 shrink-0 text-gray-600 transition group-hover:text-gray-300" /></div><p className="mt-1 truncate text-[10px] text-gray-500">{tool.description}</p></div>
              </Link>)}
            </div>
          </section>
          <section aria-label="从风格开始" className="mt-10 sm:mt-12">
            <div className="mb-3"><h3 className="text-sm font-semibold">从风格开始</h3><p className="mt-1 text-[11px] text-gray-400">选中风格后，仍可自由修改创作需求</p></div>
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              {stylePresets.map((preset) => <button key={preset.name} className="group overflow-hidden rounded-2xl border border-black/[0.06] bg-white text-left shadow-sm transition hover:-translate-y-0.5 hover:border-black/15 hover:shadow-md dark:border-white/10 dark:bg-gray-900" onClick={() => { setText(preset.prompt); composer.current?.focus() }}>
                <div className="aspect-[1.45] overflow-hidden bg-[#f0f0ed]"><img src={`${import.meta.env.BASE_URL}style-presets/${preset.image}`} alt="" className="h-full w-full object-cover object-top transition duration-500 group-hover:scale-[1.025]" /></div>
                <div className="flex items-center justify-between px-3 py-2.5"><span className="text-xs font-medium">{preset.name}</span><ArrowUpIcon className="h-3.5 w-3.5 rotate-45 text-gray-300 transition group-hover:text-gray-700 dark:group-hover:text-gray-200" /></div>
              </button>)}
            </div>
          </section>
        </div>
      </div> : <>
        <div role="region" aria-label="对话记录" tabIndex={0} className="min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6 sm:py-8" onScroll={event=>{const el=event.currentTarget;const near=el.scrollHeight-el.scrollTop-el.clientHeight<80;followingLatest.current=near;setShowLatest(!near)}}>
          <div className="mx-auto w-full max-w-[880px] space-y-7">
            {conversation && attachments.length>0 && (creative.module==='batch_tryon'||productionPlans.length>0||runs.some(r=>r.plan?.actions.some(a=>['analyze_chat_assets','guide_batch_inputs','generate_chat_tryon'].includes(a.tool)))||attachments.some(a=>a.role==='template')) && <AgentBatchInputCard conversationId={conversation.id} refreshKey={attachments.map(a=>a.asset_id+':'+a.role).join(',')+':'+runs.map(r=>r.id+':'+r.revision+':'+r.status).join(',')} runs={runs} paused={busy||preparingImport||uploads.length>0} onPartialAccepted={()=>setUploads(old=>old.filter(u=>u.status!=='failed'))} onContinue={creative.module==='batch_tryon'?continueImport:undefined} onRefresh={()=>refresh(conversation.id)} onError={setError}/>}
            {messages.map((message) => {
              const run = message.metadata?.run_id ? runById.get(message.metadata.run_id) : null
              const latest = !run || lastMessage.get(run.id) === message.id
              const savedDraft = !!run && isSavedAmazonDraft(run,amazonPlans)
              const showText = message.role === 'user' || !run || !latest || run.planner_mode==='dsh-native'
              if (message.role === 'user') return <article key={message.id} className="flex justify-end pl-8 sm:pl-20">
                <div className="max-w-[760px] rounded-[20px_20px_6px_20px] bg-[#e9e9e4] px-4 py-3 text-sm leading-7 dark:bg-white/10">
                  <p className="whitespace-pre-wrap">{message.content}</p>
                  {message.metadata?.attachments && <div className="mt-3 flex flex-wrap gap-2">{message.metadata.attachments.map((attachment, index) => <AuthenticatedImage key={attachment.id || attachment.asset_id || index} src={attachment.content_url} alt={attachment.filename} className="h-20 w-20 rounded-xl border border-black/[0.06] bg-white object-contain dark:border-white/10" />)}</div>}
                </div>
              </article>
              return <article key={message.id} data-agent-run={run?.id} className="flex gap-3">
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px] bg-[#eae5da] text-[#806c47] dark:bg-white/10 dark:text-gray-300"><SparklesIcon className="h-4 w-4" /></div>
                <div className="min-w-0 flex-1">
                  {showText && <div className="py-1 text-sm leading-7 text-gray-700 dark:text-gray-200"><p className="whitespace-pre-wrap">{message.content}</p></div>}
                  {run && latest && status && <div className={showText ? 'mt-3' : ''}><AgentPlanCard run={run} statusLabel={savedDraft?'方案已保存':undefined} status={status} busy={busy} onConfirm={() => void runAction(run)} onStop={() => void runAction(run, true)} onResume={() => void runAction(run,false,true)} onRetry={id=>void retryImage(id)} retriedIds={runs.flatMap(r=>r.result.retry_of_job_id?[r.result.retry_of_job_id]:[])}/><AgentPromptPanel run={run} busy={busy} onSave={(source,content)=>savePrompt(run,source,content)} onGenerate={version=>void generateSavedPrompt(run,version)} onError={setError}/>{run.result.actions?.filter((action) => action.tool === 'read_shared_queue').map((action, index) => <SharedQueueView key={index} board={action.result as unknown as SharedQueueBoard} onOpen={(entry) => { if (entry.can_open && entry.navigation?.project_id) navigate(`/workspaces/batch-tryon?project_id=${entry.navigation.project_id}`) }} />)}</div>}
                  {run&&latest&&<>{!savedDraft&&<AgentClarificationCard run={run} busy={busy} enabled={status?.creative_assistance_enabled===true} answered={answeredRuns.has(run.id)} onReply={content=>void send('create',{run,content})} onSuggest={()=>void send('suggest',{run,content:'请结合原始需求、追问和参考图，给我几个可编辑的创作建议。'})}/>}<AgentSuggestionsCard run={run} busy={busy} onAdopt={content=>void send('create',{run,content})}/></>}
                  {run&&latest&&<AgentBusinessCards run={run} disabled={!status?.enabled||busy||preparingImport||uploads.length>0} onImport={(files,source)=>void uploadFiles(files,source)}/>}
                  {run&&latest&&conversation&&amazonPlans.filter(plan=>amazonOwners.get(plan.id)===run.id).map(plan=><AgentAmazonCard key={`${conversation.id}:${plan.id}`} record={plan} conversationId={conversation.id} outputs={runs.flatMap(item=>item.outputs||[])} pendingRun={runs.find(r=>r.status==='awaiting_review'&&r.plan?.actions.some(a=>a.tool==='generate_aplus'&&a.arguments.plan_id===plan.id))} onRefresh={()=>refresh(conversation.id)} onError={setError}/>)}
                  {run&&latest&&status&&<AgentResultGallery outputs={run.outputs || []} onEdit={edit} onError={setError} />}
                  {run && latest && conversation && productionPlans.filter((plan) => productionCardRunId(runs, plan.id) === run.id).map((plan) => <AgentProductionCard key={plan.id} plan={plan} conversationId={conversation.id} attachments={attachments} outputs={runs.flatMap((item) => item.outputs || [])} onRefresh={() => refresh(conversation.id)} onError={setError} />)}
                </div>
              </article>
            })}
            <div ref={end} />
          </div>
        </div>
        <div className="relative shrink-0 bg-gradient-to-t from-[#f8f8f6] via-[#f8f8f6] to-transparent px-3 pb-4 pt-3 sm:px-6 dark:from-gray-950 dark:via-gray-950">{showLatest&&<button className={`${chatButton} absolute -top-9 left-1/2 z-10 -translate-x-1/2 bg-white shadow-sm dark:bg-gray-900`} onClick={()=>{followingLatest.current=true;setShowLatest(false);end.current?.scrollIntoView({behavior:'smooth',block:'end'})}}>回到最新对话 ↓</button>}<div className="mx-auto w-full max-w-[880px]">{renderComposer()}</div></div>
      </>}
    </section>

    {historyOpen && <div className="absolute inset-0 z-40"><button aria-label="关闭历史对话" className="absolute inset-0 bg-black/25 backdrop-blur-[2px]" onClick={() => setHistoryOpen(false)} /><aside className="absolute inset-y-0 left-0 flex w-[86%] max-w-[300px] flex-col bg-[#f3f3f0] shadow-2xl lg:left-16 dark:bg-gray-900"><div className="flex h-14 shrink-0 items-center justify-between border-b border-black/[0.06] px-4 dark:border-white/10"><span className="text-sm font-semibold">创作对话</span><button aria-label="关闭历史对话" className="rounded-full p-2 hover:bg-black/5 dark:hover:bg-white/5" onClick={() => setHistoryOpen(false)}><CloseIcon className="h-4 w-4" /></button></div><div className="flex min-h-0 flex-1 flex-col">{renderConversationSidebar()}</div></aside></div>}
    {drawer && <div className="absolute inset-0 z-40"><button aria-label="关闭素材与执行详情" className="absolute inset-0 bg-black/20 backdrop-blur-[2px]" onClick={() => setDrawer(false)} /><aside aria-label="素材与执行详情" className="absolute inset-y-0 right-0 w-full max-w-[380px] overflow-y-auto border-l border-black/[0.07] bg-white p-5 shadow-2xl dark:border-white/10 dark:bg-gray-900">
      <div className="mb-5 flex items-center justify-between"><div><h2 className="text-sm font-semibold">素材与执行详情</h2><p className="mt-1 text-xs text-gray-400">当前会话的图片和任务信息</p></div><button aria-label="关闭素材与执行详情" className="rounded-full p-2 hover:bg-black/5 dark:hover:bg-white/5" onClick={() => setDrawer(false)}><CloseIcon className="h-4 w-4" /></button></div>
      <section><h3 className="mb-3 text-xs font-medium text-gray-400">会话素材 · {attachments.length}</h3>{attachments.map((attachment) => <button key={attachment.id} className={`mb-2 flex w-full items-center gap-3 rounded-xl border p-2.5 text-left text-sm transition dark:border-white/10 ${selected.includes(attachment.id) ? 'border-[#a89574] bg-[#f7f4ee] dark:bg-white/[0.07]' : 'hover:bg-black/[0.025] dark:hover:bg-white/5'}`} onClick={() => setSelected((old) => old.includes(attachment.id) ? old : [...old, attachment.id])}><AuthenticatedImage src={attachment.content_url} alt={attachment.filename} className="h-12 w-12 shrink-0 rounded-lg bg-[#f4f4f1] object-contain" /><span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium">{attachment.filename}</span><span className="mt-1 block text-[11px] text-gray-400">{roles.find((role) => role[0] === attachment.role)?.[1]}</span></span><span className="text-[11px] text-gray-400">{selected.includes(attachment.id) ? '已引用' : '引用'}</span></button>)}{!attachments.length && <div className="rounded-2xl bg-[#f7f7f4] px-4 py-8 text-center text-xs text-gray-400 dark:bg-white/[0.03]">上传或从素材库选择的图片会显示在这里</div>}</section>
      {auth.hasPermission('platform.admin')&&<section aria-label="主控切换" className="my-4 rounded-xl border p-3 text-sm"><label>默认主控 <select aria-label="默认主控" value={status?.controller||'langgraph'} onChange={event=>{const controller=event.target.value as 'dsh'|'langgraph';void setAgentController(controller).then(()=>getAgentStatus()).then(setStatus).catch(fail)}}><option value="dsh">DSH SuperAgent · K2.8</option><option value="langgraph">LangGraph 紧急回退</option></select></label><p className="mt-2 text-xs text-gray-500">新消息使用所选主控；已有任务、图片和历史记录保留。</p></section>}
      {status?.auto_execution?.mode==='autonomous'&&<p className="my-6 text-sm font-medium">自主执行 · {status.auto_execution.enabled?'已开启':'当前环境未启用'}</p>}
      {status?.auto_execution && status.auto_execution.mode!=='autonomous' && <section aria-label="自动生成阈值" className="my-6 rounded-2xl bg-[#f7f7f4] p-4 text-sm dark:bg-white/[0.04]"><h3 className="mb-3 text-xs font-semibold">自动生成阈值{!status.auto_execution.enabled && ' · 未开启'}</h3><dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs text-gray-500 dark:text-gray-400"><div><dt>图片数量</dt><dd className="mt-1 font-medium text-gray-800 dark:text-gray-200">最多 {status.auto_execution.max_images} 张</dd></div><div><dt>预计耗时</dt><dd className="mt-1 font-medium text-gray-800 dark:text-gray-200">{Math.ceil(status.auto_execution.max_seconds / 60)} 分钟内</dd></div><div><dt>单次累计额度</dt><dd className="mt-1 font-medium text-gray-800 dark:text-gray-200">{status.auto_execution.max_credits}</dd></div><div><dt>并行流程</dt><dd className="mt-1 font-medium text-gray-800 dark:text-gray-200">{status.auto_execution.max_active_runs} 个</dd></div><div><dt>自动提交</dt><dd className="mt-1 font-medium text-gray-800 dark:text-gray-200">每分钟 {status.auto_execution.submissions_per_minute} 次</dd></div></dl></section>}
      <AgentCapabilityPanel />
      {!!amazonPlans.length&&conversation&&<section aria-label="对话方案" className="my-5"><h3 className="text-sm font-medium">对话方案 · {amazonPlans.length}</h3>{amazonPlans.filter(p=>!orphanPlans.includes(p)).map(p=><button key={p.id} className="mt-2 block w-full rounded-xl border p-3 text-left text-sm dark:border-white/10" onClick={()=>{setDrawer(false);followingLatest.current=false;setShowLatest(true);requestAnimationFrame(()=>document.getElementById('amazon-plan-'+p.id)?.scrollIntoView({block:'center',behavior:'smooth'}))}}>{p.plan.deliverable==='listing'?'Listing 图片方案':'A+ 图片方案'} · {p.plan.modules.length} 个模块 · v{p.revision}<span className="mt-1 block text-xs text-gray-500">跳转到方案所在对话</span></button>)}{orphanPlans.map(p=><AgentAmazonCard key={p.id} record={p} conversationId={conversation.id} outputs={runs.flatMap(r=>r.outputs||[])} onRefresh={()=>refresh(conversation.id)} onError={setError}/>)}</section>}
      <AmazonResearchStatus receipts={amazonResearch}/>
      <details className="group mt-5 rounded-xl border border-black/[0.06] p-3 text-xs dark:border-white/10"><summary className="flex cursor-pointer list-none items-center justify-between text-gray-500">模型配置状态<ChevronDownIcon className="h-3.5 w-3.5 transition group-open:rotate-180" /></summary><pre className="mt-3 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[#f7f7f4] p-3 text-[10px] leading-5 text-gray-500 dark:bg-white/[0.04] dark:text-gray-400">{JSON.stringify(status, null, 2)}</pre></details>
      <details className="group mt-3 rounded-xl border border-black/[0.06] p-3 text-xs dark:border-white/10"><summary className="flex cursor-pointer list-none items-center justify-between text-gray-500">任务日志 / 参数快照<ChevronDownIcon className="h-3.5 w-3.5 transition group-open:rotate-180" /></summary>{runs.map((run) => <div key={run.id} className="mt-3"><p className="break-all text-[10px] text-gray-400">{run.id}</p><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[#f7f7f4] p-3 text-[10px] leading-5 text-gray-500 dark:bg-white/[0.04] dark:text-gray-400">{JSON.stringify({ plan: run.plan, jobs: run.jobs, events: run.events, execution: run.execution_notice, verification: run.verification }, null, 2)}</pre></div>)}</details>
    </aside></div>}
    {library && <div role="dialog" aria-label="选择已有图片" className="absolute inset-0 z-50 flex items-end justify-center bg-black/30 backdrop-blur-[2px] sm:items-center sm:p-6" onClick={() => setLibrary(false)}><section className="flex max-h-[88%] w-full max-w-4xl flex-col rounded-t-[24px] bg-white p-4 shadow-2xl sm:max-h-full sm:rounded-[24px] sm:p-6 dark:bg-gray-900" onClick={(event) => event.stopPropagation()}>
      <div className="mb-5 flex items-center justify-between gap-3"><div><h2 className="text-base font-semibold">选择创作素材</h2><p className="mt-1 text-xs text-gray-400">从我的素材、模板或历史结果中选择</p></div><button aria-label="关闭素材库" className="rounded-full p-2 hover:bg-black/5 dark:hover:bg-white/5" onClick={() => setLibrary(false)}><CloseIcon className="h-5 w-5" /></button></div>
      <label className="mb-5 flex h-11 items-center gap-2 rounded-xl bg-[#f4f4f1] px-3 dark:bg-white/[0.05]"><SearchIcon className="h-4 w-4 text-gray-400" /><input aria-label="搜索素材" value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="搜索文件名" className="min-w-0 flex-1 bg-transparent text-sm outline-none" /></label>
      <div className="min-h-0 overflow-y-auto"><div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-5">{libraryItems.map((asset) => <button key={asset.id} className="group overflow-hidden rounded-xl border border-black/[0.07] bg-[#fafaf8] p-1.5 text-left transition hover:border-black/20 dark:border-white/10 dark:bg-white/[0.03]" onClick={() => { void addAsset(asset.id, asset.category === 'model_template' ? 'template' : asset.category === 'garment' ? 'garment' : 'reference').then(() => setLibrary(false)).catch(fail) }}><AuthenticatedImage src={asset.content_url} alt={asset.filename} className="aspect-square w-full rounded-lg bg-[#f0f0ed] object-contain" /><p className="truncate px-1 py-2 text-[11px] text-gray-500 dark:text-gray-400">{asset.filename}</p></button>)}</div>{!libraryItems.length && <p className="p-10 text-center text-sm text-gray-400">没有符合条件的图片</p>}</div>
    </section></div>}
  </main>
}

export default function AgentControlWorkspace() {
  const auth = useAuth()
  if (runtimeConfig.isStandalone) return <div className="p-8 text-sm">AI 总控仅用于已登录的多人服务模式，原工作台可继续使用。</div>
  return <ChatPanel key={`${auth.identity?.user.id || 'none'}:${auth.identity?.organization?.id || 'none'}`} />
}
