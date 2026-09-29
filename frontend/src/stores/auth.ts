import { defineStore } from 'pinia'

import { login, type CurrentUser, type LoginPayload } from '@/api/auth'

const ACCESS_TOKEN_KEY = 'tmt_workspace.access_token'
const REFRESH_TOKEN_KEY = 'tmt_workspace.refresh_token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem(ACCESS_TOKEN_KEY),
    refreshToken: localStorage.getItem(REFRESH_TOKEN_KEY),
    currentUser: null as CurrentUser | null,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.accessToken),
  },
  actions: {
    async signIn(payload: LoginPayload): Promise<void> {
      const result = await login(payload)

      if (!result.success) {
        throw new Error('登录失败')
      }

      this.accessToken = result.data.access_token
      this.refreshToken = result.data.refresh_token
      localStorage.setItem(ACCESS_TOKEN_KEY, this.accessToken)
      localStorage.setItem(REFRESH_TOKEN_KEY, this.refreshToken)
    },
    signOut(): void {
      this.accessToken = null
      this.refreshToken = null
      this.currentUser = null
      localStorage.removeItem(ACCESS_TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    },
  },
})
