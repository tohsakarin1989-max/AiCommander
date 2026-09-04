import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { authApi, type AuthUser, type UserCreatePayload } from '../services/auth'

type AuthPhase = 'loading' | 'authenticated' | 'anonymous' | 'bootstrap'

interface AuthContextValue {
  phase: AuthPhase
  user: AuthUser | null
  bootstrapAvailable: boolean
  localBootstrapAvailable: boolean
  login: (username: string, password: string) => Promise<void>
  bootstrap: (payload: UserCreatePayload, bootstrapToken: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<AuthPhase>('loading')
  const [user, setUser] = useState<AuthUser | null>(null)
  const [bootstrapAvailable, setBootstrapAvailable] = useState(false)
  const [localBootstrapAvailable, setLocalBootstrapAvailable] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const currentUser = await authApi.me()
      setUser(currentUser)
      setPhase('authenticated')
      return
    } catch {
      setUser(null)
    }

    try {
      const status = await authApi.bootstrapStatus()
      setBootstrapAvailable(status.bootstrap_available)
      setLocalBootstrapAvailable(status.local_bootstrap_available)
      setPhase(status.initialized ? 'anonymous' : 'bootstrap')
    } catch {
      setBootstrapAvailable(false)
      setLocalBootstrapAvailable(false)
      setPhase('anonymous')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const onExpired = () => {
      setUser(null)
      setPhase('anonymous')
    }
    window.addEventListener('aic:auth-expired', onExpired)
    return () => window.removeEventListener('aic:auth-expired', onExpired)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const session = await authApi.login(username, password)
    setUser(session.user)
    setPhase('authenticated')
  }, [])

  const bootstrap = useCallback(async (payload: UserCreatePayload, bootstrapToken: string) => {
    const session = localBootstrapAvailable
      ? await authApi.bootstrapLocal(payload)
      : await authApi.bootstrap(payload, bootstrapToken)
    setUser(session.user)
    setPhase('authenticated')
  }, [localBootstrapAvailable])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
      setPhase('anonymous')
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    phase,
    user,
    bootstrapAvailable,
    localBootstrapAvailable,
    login,
    bootstrap,
    logout,
    refresh,
  }), [bootstrap, bootstrapAvailable, localBootstrapAvailable, login, logout, phase, refresh, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
