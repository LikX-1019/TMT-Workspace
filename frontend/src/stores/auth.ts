import { defineStore } from 'pinia'

import {
  getCurrentUser,
  login,
  logout,
  refreshSession,
  type CurrentUser,
  type LoginPayload,
} from '@/api/auth'
import { setRuntimeAccessToken } from '@/utils/runtime-token'

interface AuthState {
  accessToken: string | null
  currentUser: CurrentUser | null
  authInitialized: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    accessToken: null,
    currentUser: null,
    authInitialized: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.accessToken),
    /**
     * 权限判断 helper：仅用于隐藏/禁用无权限的 UI 元素（体验优化）。
     * 前端可见性绝不是安全边界——真正的安全边界永远是后端 require_permission。
     */
    hasPermission: (state) => (code: string): boolean =>
      state.currentUser?.permissions.includes(code) ?? false,
  },
  actions: {
    /**
     * Restore a session from the refresh cookie on first navigation.
     * Router guards must await this once before trusting `isAuthenticated`,
     * otherwise a page reload would bounce the user to /login incorrectly.
     */
    async bootstrap(): Promise<void> {
      if (this.authInitialized) {
        return
      }

      try {
        const refreshed = await refreshSession()
        if (refreshed.success && refreshed.data.access_token) {
          this.accessToken = refreshed.data.access_token
          setRuntimeAccessToken(this.accessToken)
          await this.fetchCurrentUser()
        } else {
          this.clearSession()
        }
      } catch {
        this.clearSession()
      } finally {
        this.authInitialized = true
      }
    },
    async signIn(payload: LoginPayload): Promise<void> {
      const result = await login(payload)

      if (!result.success) {
        throw new Error('登录失败')
      }

      this.accessToken = result.data.access_token
      setRuntimeAccessToken(this.accessToken)
      await this.fetchCurrentUser()
    },
    async signOut(): Promise<void> {
      try {
        await logout()
      } finally {
        this.clearSession()
      }
    },
    clearSession(): void {
      this.accessToken = null
      this.currentUser = null
      setRuntimeAccessToken(null)
    },
    async fetchCurrentUser(): Promise<void> {
      const result = await getCurrentUser()

      if (!result.success) {
        throw new Error('获取当前用户失败')
      }

      this.currentUser = result.data
    },
  },
})
