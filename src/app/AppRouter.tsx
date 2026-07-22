import { BrowserRouter, HashRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import AppShell from './AppShell'
import { appRoutes } from './routes'
import { normalizeBrowserBasename, runtimeConfig } from './runtimeConfig'
import { APlusWorkspacePage, BatchTryOnWorkspacePage, ListingWorkspacePage } from '../pages/WorkspacePages'
import { DashboardPage, NotFoundPage, PlatformPage } from '../pages/PlatformPage'
import LoginPage from '../pages/LoginPage'
import ProfilePage from '../pages/ProfilePage'
import AssetsPage from '../pages/AssetsPage'
import ProjectsPage from '../pages/ProjectsPage'
import QuotaPage from '../pages/QuotaPage'
import TasksPage from '../pages/TasksPage'
import HistoryPage from '../pages/HistoryPage'
import AdminPage from '../pages/AdminPage'
import ChangePasswordPage from '../pages/ChangePasswordPage'
import { useAuth } from './AuthContext'

function ProtectedRoutes() {
  const auth = useAuth()
  const location = useLocation()
  if (runtimeConfig.isStandalone) return <Outlet />
  if (auth.status === 'loading') {
    return <div className="flex min-h-screen items-center justify-center bg-gray-50 text-sm text-gray-500 dark:bg-gray-950 dark:text-gray-400">正在恢复登录状态…</div>
  }
  if (auth.status === 'anonymous') {
    return <Navigate to={appRoutes.login} replace state={{ from: location.pathname }} />
  }
  if (auth.identity?.user.must_change_password && location.pathname !== appRoutes.changePassword) {
    return <Navigate to={appRoutes.changePassword} replace />
  }
  return <Outlet />
}

function AppRoutes() {
  return (
    <Routes>
      <Route path={appRoutes.login} element={runtimeConfig.isStandalone ? <Navigate to={appRoutes.listing} replace /> : <LoginPage />} />
      <Route element={<ProtectedRoutes />}>
        <Route path={appRoutes.changePassword} element={<ChangePasswordPage />} />
        <Route element={<AppShell />}>
          <Route index element={<Navigate to={appRoutes.listing} replace />} />
          <Route path={appRoutes.dashboard} element={<DashboardPage />} />
          <Route path={appRoutes.listing} element={<ListingWorkspacePage />} />
          <Route path={appRoutes.batchTryOn} element={<BatchTryOnWorkspacePage />} />
          <Route path={appRoutes.aplus} element={<APlusWorkspacePage />} />
          <Route path={appRoutes.tasks} element={runtimeConfig.isStandalone ? <PlatformPage page="tasks" /> : <TasksPage />} />
          <Route path={appRoutes.assets} element={runtimeConfig.isStandalone ? <PlatformPage page="assets" /> : <AssetsPage />} />
          <Route path={appRoutes.projects} element={runtimeConfig.isStandalone ? <PlatformPage page="projects" /> : <ProjectsPage />} />
          <Route path={appRoutes.history} element={runtimeConfig.isStandalone ? <PlatformPage page="history" /> : <HistoryPage />} />
          <Route path={appRoutes.quota} element={runtimeConfig.isStandalone ? <PlatformPage page="quota" /> : <QuotaPage />} />
          <Route path={appRoutes.profile} element={runtimeConfig.isStandalone ? <PlatformPage page="profile" /> : <ProfilePage />} />
          <Route path={appRoutes.admin} element={runtimeConfig.isStandalone ? <PlatformPage page="admin" /> : <AdminPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  )
}

export default function AppRouter() {
  if (runtimeConfig.isStandalone) {
    return <HashRouter><AppRoutes /></HashRouter>
  }
  return <BrowserRouter basename={normalizeBrowserBasename(import.meta.env.BASE_URL)}><AppRoutes /></BrowserRouter>
}
