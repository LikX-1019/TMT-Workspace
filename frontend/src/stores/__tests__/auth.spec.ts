import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '../auth'
import { setRuntimeAccessToken } from '@/utils/runtime-token'

const authApi = vi.hoisted(() => ({
  login: vi.fn(),
  logout: vi.fn(),
  refreshSession: vi.fn(),
  getCurrentUser: vi.fn(),
}))

vi.mock('@/api/auth', () => authApi)

const mePayload = {
  success: true,
  data: {
    id: 'u-1',
    employee_no: 'E001',
    username: 'alice',
    name: 'Alice',
    email: null,
    mobile: null,
    employment_status: 'active',
    account_status: 'active',
    roles: ['system_admin'],
    permissions: ['system:user:list'],
    primary_department: null,
    primary_position: null,
    last_login_at: null,
  },
}

beforeEach(() => {
  setActivePinia(createPinia())
  setRuntimeAccessToken(null)
  authApi.login.mockReset()
  authApi.logout.mockReset()
  authApi.refreshSession.mockReset()
  authApi.getCurrentUser.mockReset()
})

describe('authStore.hasPermission', () => {
  it('returns true only for codes present in the effective permission set', async () => {
    authApi.refreshSession.mockResolvedValue({
      success: true,
      data: { access_token: 'bootstrapped-token', token_type: 'bearer', expires_in: 1800 },
    })
    authApi.getCurrentUser.mockResolvedValue(mePayload)
    const auth = useAuthStore()

    await auth.bootstrap()

    expect(auth.hasPermission('system:user:list')).toBe(true)
    expect(auth.hasPermission('system:user:create')).toBe(false)
  })

  it('returns false when no user is loaded', () => {
    const auth = useAuthStore()

    expect(auth.hasPermission('system:user:list')).toBe(false)
  })
})

describe('authStore.bootstrap', () => {
  it('restores the session via refresh cookie then loads current user', async () => {
    authApi.refreshSession.mockResolvedValue({
      success: true,
      data: { access_token: 'bootstrapped-token', token_type: 'bearer', expires_in: 1800 },
    })
    authApi.getCurrentUser.mockResolvedValue(mePayload)
    const auth = useAuthStore()

    await auth.bootstrap()

    expect(authApi.refreshSession).toHaveBeenCalledTimes(1)
    expect(authApi.getCurrentUser).toHaveBeenCalledTimes(1)
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.currentUser?.username).toBe('alice')
    expect(auth.authInitialized).toBe(true)
  })

  it('stays unauthenticated when the refresh cookie is missing or rejected', async () => {
    authApi.refreshSession.mockRejectedValue(new Error('401'))
    const auth = useAuthStore()

    await auth.bootstrap()

    expect(authApi.getCurrentUser).not.toHaveBeenCalled()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.currentUser).toBeNull()
    expect(auth.authInitialized).toBe(true)
  })

  it('runs only once so repeated guard calls do not re-refresh', async () => {
    authApi.refreshSession.mockResolvedValue({ success: false, data: null })
    const auth = useAuthStore()

    await auth.bootstrap()
    await auth.bootstrap()

    expect(authApi.refreshSession).toHaveBeenCalledTimes(1)
    expect(auth.authInitialized).toBe(true)
  })
})

describe('authStore.signIn', () => {
  it('stores the access token in runtime memory and loads the user', async () => {
    authApi.login.mockResolvedValue({
      success: true,
      data: { access_token: 'login-token', token_type: 'bearer', expires_in: 1800 },
    })
    authApi.getCurrentUser.mockResolvedValue(mePayload)
    const auth = useAuthStore()

    await auth.signIn({ username: 'alice', password: 'password-value' })

    expect(auth.accessToken).toBe('login-token')
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.currentUser?.name).toBe('Alice')
  })

  it('propagates failure without storing a session', async () => {
    authApi.login.mockResolvedValue({ success: false, data: null })
    const auth = useAuthStore()

    await expect(auth.signIn({ username: 'alice', password: 'bad-input-value' })).rejects.toThrow(
      '登录失败',
    )

    expect(auth.isAuthenticated).toBe(false)
  })
})

describe('authStore.signOut', () => {
  it('calls the API and always clears the local session', async () => {
    authApi.refreshSession.mockResolvedValue({
      success: true,
      data: { access_token: 'token-x', token_type: 'bearer', expires_in: 1800 },
    })
    authApi.getCurrentUser.mockResolvedValue(mePayload)
    authApi.logout.mockResolvedValue({ success: true, data: { status: 'ok' } })
    const auth = useAuthStore()
    await auth.bootstrap()
    expect(auth.isAuthenticated).toBe(true)

    await auth.signOut()

    expect(authApi.logout).toHaveBeenCalledTimes(1)
    expect(auth.accessToken).toBeNull()
    expect(auth.currentUser).toBeNull()
    expect(auth.isAuthenticated).toBe(false)
  })

  it('clears the local session even when the logout API fails', async () => {
    authApi.refreshSession.mockResolvedValue({
      success: true,
      data: { access_token: 'token-y', token_type: 'bearer', expires_in: 1800 },
    })
    authApi.getCurrentUser.mockResolvedValue(mePayload)
    authApi.logout.mockRejectedValue(new Error('network down'))
    const auth = useAuthStore()
    await auth.bootstrap()

    await expect(auth.signOut()).rejects.toThrow('network down')

    expect(auth.isAuthenticated).toBe(false)
  })
})
