export const appRoutes = {
  root: '/',
  login: '/login',
  changePassword: '/change-password',
  dashboard: '/dashboard',
  listing: '/workspaces/listing',
  attachmentImages: '/workspaces/attachment-images',
  attachmentImageWorkbench: '/attachment-image-workbench/:sessionId',
  listingQuick: '/workspaces/listing/quick',
  listingQuickProgress: '/workspaces/listing/quick/:quickSessionId',
  smartImageVariationHub: '/workspaces/listing/variations',
  legacyListing: '/workspaces/listing/legacy',
  listingWorkbench: '/listing-workbench/:sessionId',
  listingOutputSelect: '/listing-workbench/:sessionId/select-output',
  listingImageWorkbench: '/listing-image-workbench/:sessionId',
  smartImageVariation: '/listing-image-workbench/:sessionId/variations',
  categoryAPlusWorkbench: '/a-plus-workbench/:sessionId',
  batchTryOn: '/workspaces/batch-tryon',
  batchTryOnRegionReplace: '/workspaces/batch-tryon/region-replace/:itemId',
  aplus: '/workspaces/aplus',
  materialExtract: '/material-extract',
  printDesign: '/workspaces/print-design',
  tasks: '/tasks',
  assets: '/assets',
  projects: '/projects',
  history: '/history',
  quota: '/quota',
  profile: '/profile',
  admin: '/admin',
  categorySkillsAdmin: '/admin/category-skills',
} as const

export type AppRoutePath = (typeof appRoutes)[keyof typeof appRoutes]

export interface NavigationItem {
  label: string
  path: AppRoutePath
  shortLabel?: string
  multiuserOnly?: boolean
}

export interface NavigationSection {
  label: string
  items: NavigationItem[]
}

export const navigationSections: NavigationSection[] = [
  {
    label: '概览',
    items: [{ label: '工作台概览', shortLabel: '概览', path: appRoutes.dashboard }],
  },
  {
    label: '图片工作台',
    items: [
      { label: '品类 Listing', path: appRoutes.listing },
      { label: '附图生成工作台', shortLabel: '附图生成', path: appRoutes.attachmentImages },
      { label: '原版 Listing 图', path: appRoutes.legacyListing },
      { label: '自由图片裂变', path: appRoutes.smartImageVariationHub },
      { label: '批量套图', path: appRoutes.batchTryOn },
      { label: 'A+ 图', path: appRoutes.aplus },
      { label: '素材提取', path: appRoutes.materialExtract },
      { label: '印花编辑', path: appRoutes.printDesign },
    ],
  },
  {
    label: '公共中心',
    items: [
      { label: '任务中心', path: appRoutes.tasks },
      { label: '素材中心', path: appRoutes.assets },
      { label: '项目系统', path: appRoutes.projects, multiuserOnly: true },
      { label: '生成历史', path: appRoutes.history },
      { label: '额度中心', path: appRoutes.quota, multiuserOnly: true },
    ],
  },
  {
    label: '账户',
    items: [
      { label: '个人中心', path: appRoutes.profile },
      { label: '管理后台', path: appRoutes.admin, multiuserOnly: true },
    ],
  },
]
