import axios from 'axios'
import type { AxiosInstance } from 'axios'
import { getRuntimeAccessToken } from '@/utils/runtime-token'

export interface ApiResponse<T> {
  success: boolean
  data: T
  meta?: Record<string, unknown> | null
}

export const request: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: 15_000,
})

request.interceptors.request.use((config) => {
  const token = getRuntimeAccessToken()

  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

request.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      window.location.assign('/login')
    }

    return Promise.reject(error)
  },
)
