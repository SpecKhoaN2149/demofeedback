import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { login as apiLogin, logout as apiLogout } from '../api/client'

const TOKEN_KEY = 'auth_token'
const USERNAME_KEY = 'auth_username'

interface AuthContextType {
  token: string | null
  username: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

function loadPersistedState(): { token: string | null; username: string | null } {
  try {
    const token = localStorage.getItem(TOKEN_KEY)
    const username = localStorage.getItem(USERNAME_KEY)
    return { token, username }
  } catch {
    return { token: null, username: null }
  }
}

function persistState(token: string | null, username: string | null): void {
  try {
    if (token && username) {
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USERNAME_KEY, username)
    } else {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USERNAME_KEY)
    }
  } catch {
    // localStorage may be unavailable in some environments
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => loadPersistedState().token)
  const [username, setUsername] = useState<string | null>(() => loadPersistedState().username)

  const isAuthenticated = token !== null

  const login = useCallback(async (user: string, password: string): Promise<void> => {
    const response = await apiLogin(user, password)
    setToken(response.token)
    setUsername(response.username)
    persistState(response.token, response.username)
  }, [])

  const logout = useCallback(async (): Promise<void> => {
    if (token) {
      try {
        await apiLogout(token)
      } catch {
        // Even if the server logout fails, clear local state
      }
    }
    setToken(null)
    setUsername(null)
    persistState(null, null)
  }, [token])

  return (
    <AuthContext.Provider value={{ token, username, isAuthenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
