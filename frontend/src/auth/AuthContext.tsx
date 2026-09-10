import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi, type AuthUser, type UserCreatePayload } from '../services/auth'
import { useQueryClient } from '@tanstack/react-query'
import { createSessionBoundary } from './sessionBoundary'

type AuthPhase = 'loading' | 'authenticated' | 'anonymous' | 'bootstrap'

interface AuthContextValue {
  phase: AuthPhase
  user: AuthUser | null
  sessionEpoch: number
  bootstrapAvailable: boolean
  localBootstrapAvailable: boolean
  login: (username: string, password: string) => Promise<void>
  bootstrap: (payload: UserCreatePayload, bootstrapToken: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient()
  const boundary = useMemo(() => createSessionBoundary(queryClient), [queryClient])
  const [sessionEpoch, setSessionEpoch] = useState(0)
  const [phase, setPhase] = useState<AuthPhase>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [bootstrapAvailable, setBootstrapAvailable] = useState(false)
  const [localBootstrapAvailable, setLocalBootstrapAvailable] = useState(false)

  const resetSession = useCallback((nextPhase: AuthPhase = 'anonymous') => {
    const revision = boundary.reset()
    setSessionEpoch(revision)
    setUser(null)
    setPhase(nextPhase)
    return revision
  }, [boundary])

  const refresh = useCallback(async () => {
    const revision = resetSession('loading')
    try {
      const currentUser = await authApi.me()
      if (!boundary.isCurrent(revision)) return
      setUser(currentUser)
      setPhase('authenticated')
      return
    } catch {
      if (!boundary.isCurrent(revision)) return
    }

    try {
      const status = await authApi.bootstrapStatus()
      if (!boundary.isCurrent(revision)) return
      setBootstrapAvailable(status.bootstrap_available)
      setLocalBootstrapAvailable(status.local_bootstrap_available)
      setPhase(status.initialized ? 'anonymous' : 'bootstrap')
    } catch {
      if (!boundary.isCurrent(revision)) return
      setBootstrapAvailable(false)
      setLocalBootstrapAvailable(false)
      setPhase('anonymous')
    }
  }, [boundary, resetSession])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const onExpired = () => {
      resetSession()
    }
    window.addEventListener('aic:auth-expired', onExpired)
    return () => window.removeEventListener('aic:auth-expired', onExpired)
  }, [resetSession])

  const login = useCallback(async (username: string, password: string) => {
    const revision = resetSession()
    const session = await authApi.login(username, password)
    if (!boundary.isCurrent(revision)) return
    setUser(session.user)
    setPhase('authenticated')
  }, [boundary, resetSession])

  const bootstrap = useCallback(async (payload: UserCreatePayload, bootstrapToken: string) => {
    const revision = resetSession()
    const session = localBootstrapAvailable
      ? await authApi.bootstrapLocal(payload)
      : await authApi.bootstrap(payload, bootstrapToken)
    if (!boundary.isCurrent(revision)) return
    setUser(session.user)
    setPhase('authenticated')
  }, [boundary, localBootstrapAvailable, resetSession])

  const logout = useCallback(async () => {
    // 等旧注销响应（含 Set-Cookie）结束后才允许新登录。
    const revision = resetSession('loading')
    try {
      await authApi.logout()
    } finally {
      if (boundary.isCurrent(revision)) resetSession()
    }
  }, [boundary, resetSession])

  const value = useMemo<AuthContextValue>(() => ({
    phase,
    user,
    sessionEpoch,
    bootstrapAvailable,
    localBootstrapAvailable,
    login,
    bootstrap,
    logout,
    refresh,
  }), [bootstrap, bootstrapAvailable, localBootstrapAvailable, login, logout, phase, refresh, user, sessionEpoch])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
