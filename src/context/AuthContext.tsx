import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../services/api'
import type { AuthUser } from '../types/domain'

type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  createAccount: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    void api.getCurrentUser().then((current) => {
      if (mounted) setUser(current)
    }).catch(() => {
      if (mounted) setUser(null)
    }).finally(() => {
      if (mounted) setLoading(false)
    })
    return () => { mounted = false }
  }, [])

  async function login(email: string, password: string) {
    setUser(await api.login(email, password))
  }

  async function createAccount(name: string, email: string, password: string) {
    if (!name.trim() || !email.trim() || password.length < 8) throw new Error('Enter a name, valid email, and password with at least 8 characters.')
    setUser(await api.createAccount(name.trim(), email.trim(), password))
  }

  function logout() {
    void api.logout().catch(() => undefined)
    setUser(null)
  }

  const value = useMemo(() => ({ user, loading, login, createAccount, logout }), [user, loading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider.')
  return context
}
