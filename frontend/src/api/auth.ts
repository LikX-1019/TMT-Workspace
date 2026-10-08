import { request, type ApiResponse } from './request'

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResult {
  access_token: string
  token_type: string
  expires_in: number
}

export interface PrimaryAssignment {
  id: string
  name: string
}

export interface CurrentUser {
  id: string
  employee_no: string
  username: string
  name: string
  email: string | null
  mobile: string | null
  employment_status: string
  account_status: string
  /** Stable role codes, resolved from active user_roles (Phase 2A). */
  roles: string[]
  /** Effective permission codes (union of active grants, sorted). */
  permissions: string[]
  primary_department: PrimaryAssignment | null
  primary_position: PrimaryAssignment | null
  last_login_at: string | null
}

export function login(payload: LoginPayload): Promise<ApiResponse<TokenResult>> {
  return request
    .post<ApiResponse<TokenResult>>('/auth/login', payload)
    .then((response) => response.data)
}

/**
 * Exchange the HttpOnly refresh cookie for a new access token.
 * The refresh token itself never appears in JavaScript.
 */
export function refreshSession(): Promise<ApiResponse<TokenResult>> {
  return request
    .post<ApiResponse<TokenResult>>('/auth/refresh')
    .then((response) => response.data)
}

export function logout(): Promise<ApiResponse<{ status: string }>> {
  return request
    .post<ApiResponse<{ status: string }>>('/auth/logout')
    .then((response) => response.data)
}

export function getCurrentUser(): Promise<ApiResponse<CurrentUser>> {
  return request
    .get<ApiResponse<CurrentUser>>('/auth/me')
    .then((response) => response.data)
}
