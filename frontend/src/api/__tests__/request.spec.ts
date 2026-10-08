import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import type { AxiosRequestConfig, AxiosResponse } from 'axios'

import { request } from '../request'
import { getRuntimeAccessToken, setRuntimeAccessToken } from '@/utils/runtime-token'

const navigation = vi.hoisted(() => ({
  redirectToLogin: vi.fn(),
}))

vi.mock('@/utils/session-navigation', () => navigation)

interface StubRoute {
  /** Matches against config.url, e.g. /auth/refresh or /tasks/list. */
  pattern: RegExp
  respond: (config: AxiosRequestConfig) => { status: number; data?: unknown }
}

function installStubAdapter(routes: StubRoute[], callLog: string[]): void {
  request.defaults.adapter = async (config) => {
    const url = config.url ?? ''
    callLog.push(`${(config.method ?? 'get').toUpperCase()} ${url}`)
    for (const route of routes) {
      if (route.pattern.test(url)) {
        const outcome = route.respond(config)
        const response: AxiosResponse = {
          data: outcome.data ?? {},
          status: outcome.status,
          statusText: '',
          headers: {},
          config,
          request: {},
        }
        // Real adapters reject non-2xx with an AxiosError that carries the
        // response; the interceptor depends on that contract.
        if (outcome.status >= 200 && outcome.status < 300) {
          return response
        }
        throw new AxiosError(
          `Request failed with status code ${outcome.status}`,
          AxiosError.ERR_BAD_RESPONSE,
          config,
          {},
          response,
        )
      }
    }
    throw new Error(`No stub route for ${url}`)
  }
}

function tokenResponse(token: string): unknown {
  return {
    success: true,
    data: { access_token: token, token_type: 'bearer', expires_in: 1800 },
  }
}

beforeEach(() => {
  setRuntimeAccessToken(null)
  navigation.redirectToLogin.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('axios 401 refresh interceptor', () => {
  it('refreshes once and retries the original request with the new token', async () => {
    const calls: string[] = []
    installStubAdapter(
      [
        {
          pattern: /\/auth\/refresh$/,
          respond: () => ({ status: 200, data: tokenResponse('fresh-token') }),
        },
        {
          pattern: /\/auth\/me$/,
          respond: (config) => ({
            status: String(config.headers?.Authorization).includes('fresh-token') ? 200 : 401,
            data: { success: true, data: {} },
          }),
        },
      ],
      calls,
    )

    const response = await request.get('/auth/me')

    expect(response.status).toBe(200)
    expect(calls).toEqual(['GET /auth/me', 'POST /auth/refresh', 'GET /auth/me'])
    expect(getRuntimeAccessToken()).toBe('fresh-token')
    expect(navigation.redirectToLogin).not.toHaveBeenCalled()
  })

  it('deduplicates parallel 401s into a single refresh request', async () => {
    const calls: string[] = []
    installStubAdapter(
      [
        {
          pattern: /\/auth\/refresh$/,
          respond: () => ({ status: 200, data: tokenResponse('shared-token') }),
        },
        {
          pattern: /\/items/,
          respond: (config) => ({
            status: String(config.headers?.Authorization).includes('shared-token') ? 200 : 401,
            data: { success: true, data: [] },
          }),
        },
      ],
      calls,
    )

    const responses = await Promise.all([
      request.get('/items/1'),
      request.get('/items/2'),
      request.get('/items/3'),
    ])

    expect(responses.every((response) => response.status === 200)).toBe(true)
    expect(calls.filter((call) => call === 'POST /auth/refresh')).toHaveLength(1)
  })

  it('clears the runtime session and redirects to login when refresh fails', async () => {
    const calls: string[] = []
    setRuntimeAccessToken('stale-token')
    installStubAdapter(
      [
        {
          pattern: /\/auth\/refresh$/,
          respond: () => ({ status: 401, data: {} }),
        },
        {
          pattern: /\/tasks/,
          respond: () => ({ status: 401, data: {} }),
        },
      ],
      calls,
    )

    await expect(request.get('/tasks/list')).rejects.toMatchObject({
      response: { status: 401 },
    })

    expect(getRuntimeAccessToken()).toBeNull()
    expect(navigation.redirectToLogin).toHaveBeenCalledTimes(1)
    expect(calls).toEqual(['GET /tasks/list', 'POST /auth/refresh'])
  })

  it('never refreshes on login endpoint failures', async () => {
    const calls: string[] = []
    installStubAdapter(
      [
        {
          pattern: /\/auth\/login$/,
          respond: () => ({ status: 401, data: {} }),
        },
      ],
      calls,
    )

    await expect(
      request.post('/auth/login', { username: 'alice', password: 'input-value' }),
    ).rejects.toMatchObject({ response: { status: 401 } })

    expect(calls).toEqual(['POST /auth/login'])
    expect(getRuntimeAccessToken()).toBeNull()
    expect(navigation.redirectToLogin).not.toHaveBeenCalled()
  })

  it('does not retry the same request twice', async () => {
    const calls: string[] = []
    installStubAdapter(
      [
        {
          pattern: /\/auth\/refresh$/,
          respond: () => ({ status: 200, data: tokenResponse('still-invalid') }),
        },
        {
          pattern: /\/locked/,
          respond: () => ({ status: 401, data: {} }),
        },
      ],
      calls,
    )

    await expect(request.get('/locked/resource')).rejects.toMatchObject({
      response: { status: 401 },
    })

    expect(calls).toEqual(['GET /locked/resource', 'POST /auth/refresh', 'GET /locked/resource'])
    expect(navigation.redirectToLogin).not.toHaveBeenCalled()
  })
})
