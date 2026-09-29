import { request, type ApiResponse } from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface LoginResult {
  access_token: string
  refresh_token: string
}

export interface CurrentUser {
  id: string
  username: string
  name: string
  roles: string[]
  permissions: string[]
}

export function login(payload: LoginPayload): Promise<ApiResponse<LoginResult>> {
  return request.post<ApiResponse<LoginResult>>('/auth/login', payload).then((response) => response.data)
}

export function getCurrentUser(): Promise<ApiResponse<CurrentUser>> {
  return request.get<ApiResponse<CurrentUser>>('/auth/me').then((response) => response.data)
}

