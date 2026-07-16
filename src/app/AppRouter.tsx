import { BrowserRouter, HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './AppShell'
import { appRoutes } from './routes'
import { normalizeBrowserBasename, runtimeConfig } from './runtimeConfig'
import { APlusWorkspacePage, BatchTryOnWorkspacePage, ListingWorkspacePage } from '../pages/WorkspacePages'
import { DashboardPage, NotFoundPage, PlatformPage } from '../pages/PlatformPage'

function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to={appRoutes.listing} replace />} />
        <Route path={appRoutes.dashboard} element={<DashboardPage />} />
        <Route path={appRoutes.listing} element={<ListingWorkspacePage />} />
        <Route path={appRoutes.batchTryOn} element={<BatchTryOnWorkspacePage />} />
        <Route path={appRoutes.aplus} element={<APlusWorkspacePage />} />
        <Route path={appRoutes.tasks} element={<PlatformPage page="tasks" />} />
        <Route path={appRoutes.assets} element={<PlatformPage page="assets" />} />
        <Route path={appRoutes.history} element={<PlatformPage page="history" />} />
        <Route path={appRoutes.quota} element={<PlatformPage page="quota" />} />
        <Route path={appRoutes.profile} element={<PlatformPage page="profile" />} />
        <Route path={appRoutes.admin} element={<PlatformPage page="admin" />} />
        <Route path="*" element={<NotFoundPage />} />
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
