import { defineStore } from 'pinia'

import { login, type CurrentUser, type LoginPayload } from '@/api/auth'
import { setRuntimeAccessToken } from '@/utils/runtime-token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: null as string | null,
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
      setRuntimeAccessToken(this.accessToken)
    },
    signOut(): void {
      this.accessToken = null
      this.currentUser = null
      setRuntimeAccessToken(null)
    },
  },
})
