import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { changePassword as changePasswordRequest, clearAccessToken, login as loginRequest, logout as logoutRequest, refreshSession, switchOrganization, type CurrentIdentity } from '../lib/authApi'
import { queryClient } from './queryClient'
import { runtimeConfig } from './runtimeConfig'

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

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(runtimeConfig.isStandalone ? 'anonymous' : 'loading')
  const [identity, setIdentity] = useState<CurrentIdentity | null>(null)

  useEffect(() => {
    if (runtimeConfig.isStandalone) return
    let active = true
    refreshSession().then((session) => {
      if (!active) return
      setIdentity(session.identity)
      setStatus('authenticated')
    }).catch(() => {
      if (!active) return
      clearAccessToken()
      setIdentity(null)
      setStatus('anonymous')
    })
    return () => { active = false }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const session = await loginRequest(email, password)
    queryClient.clear()
    setIdentity(session.identity)
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try {
      await logoutRequest()
    } finally {
      queryClient.clear()
      setIdentity(null)
      setStatus('anonymous')
    }
  }, [])

  const changeOrganization = useCallback(async (organizationId: string) => {
    const session = await switchOrganization(organizationId)
    queryClient.clear()
    setIdentity(session.identity)
    setStatus('authenticated')
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const session = await changePasswordRequest(currentPassword, newPassword)
    queryClient.clear()
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
    setIdentity,
    hasPermission: (permission) => identity?.permissions.includes(permission) ?? false,
  }), [changeOrganization, changePassword, identity, login, logout, status])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
