import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { changePassword as changePasswordRequest, clearAccessToken, login as loginRequest, logout as logoutRequest, refreshSession, subscribeAuthSessionChanges, switchOrganization, type CurrentIdentity } from '../lib/authApi'
import { queryClient } from './queryClient'
import { runtimeConfig } from './runtimeConfig'
import { useStore } from '../store'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: AuthStatus
  identity: CurrentIdentity | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  switchOrganization: (organizationId: string) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  setIdentity: (identity: CurrentIdentity) => void
  hasPermission: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)
const ACCOUNT_SCOPE_KEY = 'amazon-image-studio:account-scope:v1'

function clearAccountScopedClientState() {
  useStore.setState({
    batchTryOnBatch: null,
    tasks: [],
    selectedTaskIds: [],
    toast: null,
    confirmDialog: null,
  })
  if (typeof window !== 'undefined' && window.location.pathname.includes('/batch-tryon')) {
    const url = new URL(window.location.href)
    if (url.searchParams.has('project_id')) {
      url.searchParams.delete('project_id')
      window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
    }
  }
}

function synchronizeAccountScope(nextIdentity: CurrentIdentity | null) {
  if (typeof window === 'undefined') return
  const nextScope = nextIdentity
    ? `${nextIdentity.user.id}:${nextIdentity.organization?.id ?? 'no-organization'}`
    : null
  const previousScope = window.localStorage.getItem(ACCOUNT_SCOPE_KEY)
  if (!nextScope || previousScope !== nextScope) clearAccountScopedClientState()
  if (nextScope) window.localStorage.setItem(ACCOUNT_SCOPE_KEY, nextScope)
  else window.localStorage.removeItem(ACCOUNT_SCOPE_KEY)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(runtimeConfig.isStandalone ? 'anonymous' : 'loading')
  const [identity, setIdentity] = useState<CurrentIdentity | null>(null)
  const authRevision = useRef(0)

  useEffect(() => {
    if (runtimeConfig.isStandalone) return
    let active = true
    const startupRevision = authRevision.current
    const unsubscribe = subscribeAuthSessionChanges((change) => {
      if (!active) return
      authRevision.current += 1
      queryClient.clear()
      if (change.type === 'session') {
        synchronizeAccountScope(change.session.identity)
        setIdentity(change.session.identity)
        setStatus('authenticated')
      } else {
        clearAccessToken()
        synchronizeAccountScope(null)
        setIdentity(null)
        setStatus('anonymous')
      }
    })
    refreshSession().then((session) => {
      if (!active || authRevision.current !== startupRevision) return
      synchronizeAccountScope(session.identity)
      setIdentity(session.identity)
      setStatus('authenticated')
    }).catch(() => {
      if (!active || authRevision.current !== startupRevision) return
      clearAccessToken()
      synchronizeAccountScope(null)
      setIdentity(null)
      setStatus('anonymous')
    })
    return () => {
      active = false
      unsubscribe()
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const revision = ++authRevision.current
    try {
      const session = await loginRequest(email, password)
      if (authRevision.current !== revision) return
      queryClient.clear()
      synchronizeAccountScope(session.identity)
      setIdentity(session.identity)
      setStatus('authenticated')
    } catch (error) {
      if (authRevision.current === revision) {
        clearAccessToken()
        synchronizeAccountScope(null)
        setIdentity(null)
        setStatus('anonymous')
      }
      throw error
    }
  }, [])

  const logout = useCallback(async () => {
    const revision = ++authRevision.current
    try {
      await logoutRequest()
    } finally {
      if (authRevision.current !== revision) return
      queryClient.clear()
      synchronizeAccountScope(null)
      setIdentity(null)
      setStatus('anonymous')
    }
  }, [])

  const changeOrganization = useCallback(async (organizationId: string) => {
    const revision = ++authRevision.current
    const session = await switchOrganization(organizationId)
    if (authRevision.current !== revision) return
    queryClient.clear()
    synchronizeAccountScope(session.identity)
    setIdentity(session.identity)
    setStatus('authenticated')
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const revision = ++authRevision.current
    const session = await changePasswordRequest(currentPassword, newPassword)
    if (authRevision.current !== revision) return
    queryClient.clear()
    synchronizeAccountScope(session.identity)
    setIdentity(session.identity)
    setStatus('authenticated')
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    status,
    identity,
    login,
    logout,
    switchOrganization: changeOrganization,
    changePassword,
    setIdentity: (nextIdentity) => {
      synchronizeAccountScope(nextIdentity)
      setIdentity(nextIdentity)
    },
    hasPermission: (permission) => identity?.permissions.includes(permission) ?? false,
  }), [changeOrganization, changePassword, identity, login, logout, status])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
