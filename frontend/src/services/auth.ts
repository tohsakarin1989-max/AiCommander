import api from './api'

export type UserRole = 'admin' | 'analyst' | 'viewer'

export interface AuthUser {
  id: number
  username: string
  display_name: string
  role: UserRole
  is_active: boolean
  last_login_at?: string
  created_at: string
}

export interface BootstrapStatus {
  initialized: boolean
  bootstrap_available: boolean
}

export interface SessionResponse {
  user: AuthUser
  expires_at: string
}

export interface UserCreatePayload {
  username: string
  display_name?: string
  password: string
  role: UserRole
}

export interface UserUpdatePayload {
  display_name?: string
  password?: string
  role?: UserRole
  is_active?: boolean
}

export const authApi = {
  bootstrapStatus: async () => {
    const response = await api.get<BootstrapStatus>('/auth/bootstrap-status')
    return response.data
  },
  bootstrap: async (payload: UserCreatePayload, bootstrapToken: string) => {
    const response = await api.post<SessionResponse>('/auth/bootstrap', payload, {
      headers: { 'X-Bootstrap-Token': bootstrapToken },
    })
    return response.data
  },
  login: async (username: string, password: string) => {
    const response = await api.post<SessionResponse>('/auth/login', { username, password })
    return response.data
  },
  logout: async () => {
    await api.post('/auth/logout')
  },
  me: async () => {
    const response = await api.get<AuthUser>('/auth/me')
    return response.data
  },
  users: {
    list: async () => {
      const response = await api.get<AuthUser[]>('/auth/users')
      return response.data
    },
    create: async (payload: UserCreatePayload) => {
      const response = await api.post<AuthUser>('/auth/users', payload)
      return response.data
    },
    update: async (id: number, payload: UserUpdatePayload) => {
      const response = await api.put<AuthUser>(`/auth/users/${id}`, payload)
      return response.data
    },
  },
}
