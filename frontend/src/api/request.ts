import axios from 'axios'
import type { AxiosError, AxiosInstance, InternalAxiosRequestConfig } from 'axios'

import { createRefreshCoordinator } from './session-refresh'
import { redirectToLogin } from '@/utils/session-navigation'
import { getRuntimeAccessToken, setRuntimeAccessToken } from '@/utils/runtime-token'

export interface ApiResponse<T> {
  success: boolean
  data: T
  meta?: Record<string, unknown> | null
}

interface RetriableRequestConfig extends InternalAxiosRequestConfig {
  _authRetried?: boolean
}

export const request: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 15_000,
  // Refresh 依赖 HttpOnly Cookie，浏览器必须随请求携带。
  withCredentials: true,
})

request.interceptors.request.use((config) => {
  const token = getRuntimeAccessToken()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

function isAuthEndpoint(url: string | undefined): boolean {
  return url === '/auth/login' || url === '/auth/refresh' || url === '/auth/logout'
}

async function requestAccessTokenFromCookie(): Promise<string | null> {
  try {
    const { refreshSession } = await import('./auth')
    const result = await refreshSession()
    if (result.success && result.data?.access_token) {
      setRuntimeAccessToken(result.data.access_token)
      return result.data.access_token
    }
    return null
  } catch {
    return null
  }
}

const coordinator = createRefreshCoordinator(requestAccessTokenFromCookie)

request.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableRequestConfig | undefined
    const status = error.response?.status

    if (
      status !== 401 ||
      config === undefined ||
      config._authRetried ||
      isAuthEndpoint(config.url)
    ) {
      return Promise.reject(error)
    }

    const accessToken = await coordinator.refreshOnce()

    if (accessToken === null) {
      setRuntimeAccessToken(null)
      redirectToLogin()
      return Promise.reject(error)
    }

    config._authRetried = true
    config.headers.Authorization = `Bearer ${accessToken}`
    return request(config)
  },
)
