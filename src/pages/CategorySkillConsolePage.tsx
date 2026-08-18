import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createAdminCategorySkill, createAdminCategorySkillVersion, createProductCategory,
  listAdminCategorySkills, listAdminCategorySkillVersions, listProductCategories,
  publishAdminCategorySkillVersion, setDefaultAdminCategorySkillVersion,
  testAdminCategorySkillVersion, updateAdminCategorySkill, updateAdminCategorySkillVersion,
  updateProductCategory, validateAdminCategorySkillVersion,
  type AdminCategorySkill, type CategorySkillValidation, type CategorySkillVersionConfig, type ProductCategory,
} from '../lib/listingWorkflowApi'
import { useStore } from '../store'
import CategorySkillStructuredEditor from '../components/admin/CategorySkillStructuredEditor'

const panel = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'
const field = 'w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-white/[0.1] dark:bg-gray-950 dark:text-white'
const button = 'rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50 dark:border-white/[0.1] dark:bg-gray-950 dark:text-gray-200'
const primary = 'rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50'
type SectionKey = 'analysis_config' | 'listing_config' | 'translation_config' | 'image_prompt_config' | 'a_plus_config'
const sectionLabels: Record<SectionKey, string> = {
  analysis_config: '商品分析 Schema', listing_config: 'Listing 规则', translation_config: '中英文规则',
  image_prompt_config: '图片提示词', a_plus_config: 'A+ 规则',
}
function message(error: unknown) { return error instanceof Error ? error.message : '请求失败，请稍后重试' }
function pretty(value: unknown) { return JSON.stringify(value ?? {}, null, 2) }

export default function CategorySkillConsolePage() {
  const showToast = useStore((state) => state.showToast)
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [skills, setSkills] = useState<AdminCategorySkill[]>([])
  const [versions, setVersions] = useState<CategorySkillVersionConfig[]>([])
  const [categoryId, setCategoryId] = useState('')
  const [skillId, setSkillId] = useState('')
  const [versionId, setVersionId] = useState('')
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<SectionKey | 'advanced' | 'test'>('analysis_config')
  const [sectionTexts, setSectionTexts] = useState<Record<SectionKey, string>>({
    analysis_config: '{}', listing_config: '{}', translation_config: '{}', image_prompt_config: '{}', a_plus_config: '{}',
  })
  const [advancedText, setAdvancedText] = useState('{}')
  const [changeSummary, setChangeSummary] = useState('')
  const [validation, setValidation] = useState<CategorySkillValidation | null>(null)
  const [testInput, setTestInput] = useState('')
  const [testOutput, setTestOutput] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState('')
  const [newCategory, setNewCategory] = useState({ category_code: '', category_name: '', description: '' })
  const [newSkill, setNewSkill] = useState({ skill_name: '', skill_code: '', description: '', marketplace: 'amazon_us', language: 'en-US_zh-CN' })

  const selectedCategory = categories.find((item) => item.id === categoryId)
  const selectedSkill = skills.find((item) => item.id === skillId)
  const selectedVersion = versions.find((item) => item.id === versionId)
  const readOnly = selectedVersion?.status === 'published' || selectedVersion?.status === 'disabled' || selectedVersion?.status === 'archived'
  const visibleCategories = useMemo(() => categories.filter((item) => !search.trim() || `${item.category_name} ${item.category_code}`.toLowerCase().includes(search.trim().toLowerCase())), [categories, search])

  const loadCategories = async () => {
    const rows = await listProductCategories(true); setCategories(rows)
    if (!categoryId && rows.length) setCategoryId(rows[0].id)
  }
  const loadSkills = async (nextCategoryId: string) => {
    const rows = await listAdminCategorySkills(nextCategoryId); setSkills(rows)
    const next = rows.some((item) => item.id === skillId) ? skillId : rows[0]?.id || ''
    setSkillId(next); if (!next) { setVersions([]); setVersionId('') }
  }
  const loadVersions = async (nextSkillId: string, preferred?: string) => {
    const rows = await listAdminCategorySkillVersions(nextSkillId); setVersions(rows)
    setVersionId(preferred && rows.some((item) => item.id === preferred) ? preferred : rows[0]?.id || '')
  }

  useEffect(() => { void loadCategories().catch((error) => showToast(message(error), 'error')) }, [])
  useEffect(() => { if (categoryId) void loadSkills(categoryId).catch((error) => showToast(message(error), 'error')) }, [categoryId])
  useEffect(() => { if (skillId) void loadVersions(skillId).catch((error) => showToast(message(error), 'error')) }, [skillId])
  useEffect(() => {
    if (!selectedVersion) return
    const nextSections = {
      analysis_config: pretty(selectedVersion.analysis_config), listing_config: pretty(selectedVersion.listing_config),
      translation_config: pretty(selectedVersion.translation_config), image_prompt_config: pretty(selectedVersion.image_prompt_config),
      a_plus_config: pretty(selectedVersion.a_plus_config),
    }
    setSectionTexts(nextSections)
    setAdvancedText(pretty(Object.fromEntries(Object.entries(nextSections).map(([key, text]) => [key, JSON.parse(text)]))))
    setChangeSummary(selectedVersion.change_summary || ''); setValidation(null); setTestOutput(null)
  }, [versionId])

  const parsedConfig = () => {
    try {
      return Object.fromEntries(Object.entries(sectionTexts).map(([key, value]) => [key, JSON.parse(value)])) as Record<SectionKey, Record<string, unknown>>
    } catch (error) { throw new Error(`JSON 格式无效：${message(error)}`) }
  }
  const sectionValue = (key: SectionKey) => {
    try { return JSON.parse(sectionTexts[key]) as Record<string, unknown> } catch { return {} }
  }
  const setSectionValue = (key: SectionKey, next: Record<string, unknown>) => {
    const nextTexts = { ...sectionTexts, [key]: pretty(next) }
    setSectionTexts(nextTexts)
    try { setAdvancedText(pretty(Object.fromEntries(Object.entries(nextTexts).map(([name, text]) => [name, JSON.parse(text)])))) } catch { /* Structured editors emit valid objects. */ }
  }
  const applyAdvanced = () => {
    try {
      const parsed = JSON.parse(advancedText) as Record<SectionKey, Record<string, unknown>>
      const next = Object.fromEntries((Object.keys(sectionLabels) as SectionKey[]).map((key) => {
        if (!parsed[key] || typeof parsed[key] !== 'object' || Array.isArray(parsed[key])) throw new Error(`缺少 ${key} 对象`)
        return [key, pretty(parsed[key])]
      })) as Record<SectionKey, string>
      setSectionTexts(next)
      setAdvancedText(pretty(parsed))
      showToast('高级 JSON 已同步到表单。', 'success')
    } catch (error) { showToast(`高级 JSON 无效：${message(error)}`, 'error') }
  }
  const saveVersion = async () => {
    if (!selectedSkill || !selectedVersion || readOnly) return
    setBusy('save')
    try {
      const config = parsedConfig()
      const value = await updateAdminCategorySkillVersion(selectedSkill.id, selectedVersion.id, { ...config, change_summary: changeSummary })
      await loadVersions(selectedSkill.id, value.id); showToast('Skill 草稿已保存。', 'success')
    } catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const validateVersion = async () => {
    if (!selectedSkill || !selectedVersion) return
    setBusy('validate')
    try { if (!readOnly) await saveVersion(); const value = await validateAdminCategorySkillVersion(selectedSkill.id, selectedVersion.id); setValidation(value); showToast(value.valid ? 'Skill 校验通过。' : 'Skill 校验未通过。', value.valid ? 'success' : 'error') }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const runTest = async () => {
    if (!selectedSkill || !selectedVersion) return
    setBusy('test')
    try {
      if (!readOnly) await saveVersion()
      const value = await testAdminCategorySkillVersion(selectedSkill.id, selectedVersion.id, { product_information: testInput })
      setValidation(value.validation); setTestOutput(value as unknown as Record<string, unknown>); await loadVersions(selectedSkill.id, selectedVersion.id)
    } catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const publishVersion = async () => {
    if (!selectedSkill || !selectedVersion) return
    setBusy('publish')
    try { if (!readOnly) await saveVersion(); await publishAdminCategorySkillVersion(selectedSkill.id, selectedVersion.id); await loadVersions(selectedSkill.id, selectedVersion.id); await loadSkills(categoryId); showToast(`V${selectedVersion.version_number} 已发布。`, 'success') }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const setDefault = async () => {
    if (!selectedSkill || !selectedVersion) return
    setBusy('default')
    try { await setDefaultAdminCategorySkillVersion(selectedSkill.id, selectedVersion.id); await loadCategories(); await loadSkills(categoryId); showToast(`V${selectedVersion.version_number} 已设为该品类默认版本。`, 'success') }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const createVersion = async () => {
    if (!selectedSkill) return
    setBusy('new-version')
    try { const value = await createAdminCategorySkillVersion(selectedSkill.id, selectedVersion?.id, `Copied from V${selectedVersion?.version_number || 1}`); await loadVersions(selectedSkill.id, value.id); showToast(`V${value.version_number} 草稿已创建。`, 'success') }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const addCategory = async () => {
    setBusy('new-category')
    try { const value = await createProductCategory({ ...newCategory, is_active: true, sort_order: 100 }); setNewCategory({ category_code: '', category_name: '', description: '' }); await loadCategories(); setCategoryId(value.id) }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }
  const addSkill = async () => {
    if (!categoryId) return
    setBusy('new-skill')
    try { const value = await createAdminCategorySkill({ category_id: categoryId, ...newSkill }); setNewSkill({ skill_name: '', skill_code: '', description: '', marketplace: 'amazon_us', language: 'en-US_zh-CN' }); await loadSkills(categoryId); setSkillId(value.id) }
    catch (error) { showToast(message(error), 'error') } finally { setBusy('') }
  }

  return <div className="pb-12">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-2xl font-bold dark:text-white">品类 Skill 配置台</h1><p className="mt-1 text-sm text-gray-500">管理品类、不可变 Skill 版本、分析 Schema、Listing、翻译、图片和 A+ 规则。</p></div><Link className={button} to="/admin">返回管理后台</Link></div>
    <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className={`${panel} p-4`}><input className={field} value={search} placeholder="搜索品类" onChange={(event) => setSearch(event.target.value)} />
        <div className="mt-3 max-h-64 space-y-2 overflow-auto">{visibleCategories.map((item) => <button key={item.id} className={`w-full rounded-xl border px-3 py-2 text-left text-sm ${item.id === categoryId ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 dark:border-white/[0.08]'}`} onClick={() => setCategoryId(item.id)}><strong>{item.category_name}</strong><span className="block text-xs opacity-70">{item.category_code}{!item.is_active ? ' · 已停用' : ''}</span></button>)}</div>
        <details className="mt-4 rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-sm font-semibold">新增品类</summary><div className="mt-3 space-y-2"><input className={field} placeholder="品类名称" value={newCategory.category_name} onChange={(event) => setNewCategory((value) => ({ ...value, category_name: event.target.value }))} /><input className={field} placeholder="category_code" value={newCategory.category_code} onChange={(event) => setNewCategory((value) => ({ ...value, category_code: event.target.value }))} /><textarea className={field} placeholder="说明" value={newCategory.description} onChange={(event) => setNewCategory((value) => ({ ...value, description: event.target.value }))} /><button className={primary} disabled={!newCategory.category_name || !newCategory.category_code || Boolean(busy)} onClick={() => void addCategory()}>创建品类</button></div></details>
        {selectedCategory && <div className="mt-4 rounded-xl bg-gray-50 p-3 text-xs dark:bg-white/[0.04]"><div className="flex items-center justify-between"><span>品类状态</span><button className={button} onClick={async () => { await updateProductCategory(selectedCategory.id, { is_active: !selectedCategory.is_active }); await loadCategories() }}>{selectedCategory.is_active ? '停用品类' : '启用品类'}</button></div></div>}
      </aside>

      <main className="space-y-5"><section className={`${panel} p-5`}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold dark:text-white">{selectedCategory?.category_name || '请选择品类'} · Skills</h2><p className="text-xs text-gray-500">一个品类可维护多个 Skill，发布版本不会被直接编辑。</p></div></div>
        <div className="mt-4 flex flex-wrap gap-2">{skills.map((item) => <button key={item.id} className={`rounded-xl border px-3 py-2 text-left text-sm ${item.id === skillId ? 'border-blue-500 bg-blue-50 text-blue-700' : 'border-gray-200 dark:border-white/[0.08]'}`} onClick={() => setSkillId(item.id)}><strong>{item.skill_name}</strong><span className="ml-2 text-xs">{item.default_version_number ? `V${item.default_version_number}` : '未发布'}{item.is_category_default ? ' · 默认' : ''}</span></button>)}</div>
        <details className="mt-4 rounded-xl border border-gray-200 p-3 dark:border-white/[0.08]"><summary className="cursor-pointer text-sm font-semibold">新增 Skill</summary><div className="mt-3 grid gap-2 md:grid-cols-2"><input className={field} placeholder="Skill 名称" value={newSkill.skill_name} onChange={(event) => setNewSkill((value) => ({ ...value, skill_name: event.target.value }))} /><input className={field} placeholder="skill_code" value={newSkill.skill_code} onChange={(event) => setNewSkill((value) => ({ ...value, skill_code: event.target.value }))} /><input className={field} placeholder="站点，例如 amazon_us" value={newSkill.marketplace} onChange={(event) => setNewSkill((value) => ({ ...value, marketplace: event.target.value }))} /><input className={field} placeholder="语言" value={newSkill.language} onChange={(event) => setNewSkill((value) => ({ ...value, language: event.target.value }))} /><textarea className={`${field} md:col-span-2`} placeholder="说明" value={newSkill.description} onChange={(event) => setNewSkill((value) => ({ ...value, description: event.target.value }))} /><button className={primary} disabled={!newSkill.skill_name || !newSkill.skill_code || Boolean(busy)} onClick={() => void addSkill()}>创建 Skill 与 V1 草稿</button></div></details>
      </section>

      {selectedSkill && <section className={`${panel} p-5`}><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-bold dark:text-white">{selectedSkill.skill_name}</h2><p className="text-xs text-gray-500">{selectedSkill.skill_code} · {selectedSkill.marketplace} · {selectedSkill.language}</p></div><button className={button} onClick={() => void createVersion()} disabled={Boolean(busy)}>从当前版本创建新草稿</button></div>
        <div className="mt-4 flex flex-wrap gap-2">{versions.map((item) => <button key={item.id} className={`rounded-xl border px-3 py-2 text-sm ${item.id === versionId ? 'border-violet-500 bg-violet-50 text-violet-700' : 'border-gray-200 dark:border-white/[0.08]'}`} onClick={() => setVersionId(item.id)}>V{item.version_number} · {item.status}{selectedSkill.default_published_version_id === item.id ? ' · 默认' : ''}</button>)}</div>
      </section>}

      {selectedVersion && <section className={panel}><div className="border-b border-gray-100 px-5 py-4 dark:border-white/[0.06]"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold dark:text-white">V{selectedVersion.version_number} 配置</h2><p className="text-xs text-gray-500">状态：{selectedVersion.status}{readOnly ? ' · 已发布版本只读，请创建新草稿后修改' : ''}</p></div><div className="flex flex-wrap gap-2"><button className={button} disabled={readOnly || Boolean(busy)} onClick={() => void saveVersion()}>{busy === 'save' ? '保存中…' : '保存草稿'}</button><button className={button} disabled={Boolean(busy)} onClick={() => void validateVersion()}>校验</button><button className={primary} disabled={readOnly || Boolean(busy)} onClick={() => void publishVersion()}>发布版本</button><button className={button} disabled={selectedVersion.status !== 'published' || Boolean(busy)} onClick={() => void setDefault()}>设为默认版本</button></div></div></div>
        <div className="flex flex-wrap gap-1 border-b border-gray-100 px-5 pt-3 dark:border-white/[0.06]">{(Object.keys(sectionLabels) as SectionKey[]).map((key) => <button key={key} className={`rounded-t-xl px-3 py-2 text-sm ${tab === key ? 'bg-blue-50 font-semibold text-blue-700' : 'text-gray-500'}`} onClick={() => setTab(key)}>{sectionLabels[key]}</button>)}<button className={`rounded-t-xl px-3 py-2 text-sm ${tab === 'advanced' ? 'bg-blue-50 font-semibold text-blue-700' : 'text-gray-500'}`} onClick={() => setTab('advanced')}>高级 JSON</button><button className={`rounded-t-xl px-3 py-2 text-sm ${tab === 'test' ? 'bg-blue-50 font-semibold text-blue-700' : 'text-gray-500'}`} onClick={() => setTab('test')}>测试与发布</button></div>
        <div className="p-5">{tab in sectionLabels && <div><div className="mb-4 flex items-center justify-between"><div><h3 className="font-semibold dark:text-white">{sectionLabels[tab as SectionKey]}</h3><p className="text-xs text-gray-500">结构化表单和高级 JSON 使用同一份版本数据；已发布版本只读。</p></div></div><CategorySkillStructuredEditor section={tab as SectionKey} value={sectionValue(tab as SectionKey)} disabled={readOnly} onChange={(next) => setSectionValue(tab as SectionKey, next)} /></div>}
          {tab === 'advanced' && <div><p className="mb-3 text-sm text-gray-500">高级模式可编辑完整配置。修改后点击“应用到表单”，系统会校验五个配置区并保持同步。</p><textarea className={`${field} min-h-[600px] font-mono text-xs`} disabled={readOnly} value={advancedText} onChange={(event) => setAdvancedText(event.target.value)} /><button className={`${button} mt-3`} disabled={readOnly} onClick={applyAdvanced}>应用到表单</button></div>}
          {tab === 'test' && <div className="grid gap-4 lg:grid-cols-2"><div><label className="text-sm font-semibold">变更摘要<textarea className={`${field} mt-2 min-h-24`} disabled={readOnly} value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)} /></label><label className="mt-4 block text-sm font-semibold">测试商品信息<textarea className={`${field} mt-2 min-h-36`} value={testInput} onChange={(event) => setTestInput(event.target.value)} placeholder="填写测试商品的可见信息；测试不会写入正式 Session。" /></label><button className={`${primary} mt-3`} disabled={Boolean(busy)} onClick={() => void runTest()}>{busy === 'test' ? '测试中…' : '运行 Skill 测试'}</button>{validation && <div className={`mt-4 rounded-xl p-3 text-sm ${validation.valid ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}><strong>{validation.valid ? '校验通过' : '校验失败'}</strong>{validation.errors.map((item) => <p key={item}>· {item}</p>)}{validation.warnings.map((item) => <p key={item}>· 警告：{item}</p>)}</div>}</div><pre className="max-h-[600px] overflow-auto rounded-xl bg-gray-950 p-4 text-xs text-sky-200">{testOutput ? pretty(testOutput) : '测试结果将在这里显示系统提示词、用户提示词、结构化预览、图片提示词和耗时；不会显示 API Key。'}</pre></div>}
        </div>
      </section>}
      </main>
    </div>
  </div>
}
