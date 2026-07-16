export const appRoutes = {
  root: '/',
  dashboard: '/dashboard',
  listing: '/workspaces/listing',
  batchTryOn: '/workspaces/batch-tryon',
  aplus: '/workspaces/aplus',
  tasks: '/tasks',
  assets: '/assets',
  history: '/history',
  quota: '/quota',
  profile: '/profile',
  admin: '/admin',
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
      { label: 'Listing 图', path: appRoutes.listing },
      { label: '批量套图', path: appRoutes.batchTryOn },
      { label: 'A+ 图', path: appRoutes.aplus },
    ],
  },
  {
    label: '公共中心',
    items: [
      { label: '任务中心', path: appRoutes.tasks },
      { label: '素材中心', path: appRoutes.assets },
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
