import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listAdminCategorySkills, listProductCategories, type AdminCategorySkill, type ProductCategory } from '../../lib/listingWorkflowApi'

const panel = 'rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-white/[0.08] dark:bg-gray-900'

export default function CategoryListingManagementPanel({ notify }: { notify: (value: string) => void }) {
  const [categories, setCategories] = useState<ProductCategory[]>([])
  const [skills, setSkills] = useState<AdminCategorySkill[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    void Promise.all([listProductCategories(true), listAdminCategorySkills()]).then(([categoryRows, skillRows]) => {
      setCategories(categoryRows); setSkills(skillRows)
    }).catch((error) => notify(error instanceof Error ? error.message : '品类配置加载失败')).finally(() => setLoading(false))
  }, [notify])
  return <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-white/[0.06]"><div><h2 className="font-bold dark:text-white">品类与 Skill</h2><p className="mt-1 text-xs text-gray-500">品类、分析 Schema、Listing/翻译/图片/A+ 规则和不可变版本已统一迁移到专用配置台。</p></div><Link to="/admin/category-skills" className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white">打开品类 Skill 配置台</Link></div>
    <div className="grid gap-4 p-5 sm:grid-cols-3"><div className="rounded-xl bg-gray-50 p-4 dark:bg-white/[0.04]"><span className="text-xs text-gray-500">品类</span><strong className="mt-1 block text-2xl dark:text-white">{loading ? '…' : categories.length}</strong></div><div className="rounded-xl bg-gray-50 p-4 dark:bg-white/[0.04]"><span className="text-xs text-gray-500">Skills</span><strong className="mt-1 block text-2xl dark:text-white">{loading ? '…' : skills.length}</strong></div><div className="rounded-xl bg-gray-50 p-4 dark:bg-white/[0.04]"><span className="text-xs text-gray-500">已发布默认版本</span><strong className="mt-1 block text-2xl dark:text-white">{loading ? '…' : skills.filter((item) => item.default_published_version_id).length}</strong></div></div>
  </section>
}
