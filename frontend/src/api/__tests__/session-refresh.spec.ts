import { describe, expect, it, vi } from 'vitest'

import { createRefreshCoordinator } from '../session-refresh'

describe('createRefreshCoordinator', () => {
  it('shares one in-flight refresh across parallel callers', async () => {
    const refresh = vi.fn().mockResolvedValue('token-a')
    const coordinator = createRefreshCoordinator(refresh)

    const [first, second, third] = await Promise.all([
      coordinator.refreshOnce(),
      coordinator.refreshOnce(),
      coordinator.refreshOnce(),
    ])

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(first).toBe('token-a')
    expect(second).toBe('token-a')
    expect(third).toBe('token-a')
  })

  it('starts a new refresh after the previous one settles', async () => {
    const refresh = vi
      .fn()
      .mockResolvedValueOnce('token-a')
      .mockResolvedValueOnce('token-b')
    const coordinator = createRefreshCoordinator(refresh)

    const first = await coordinator.refreshOnce()
    const second = await coordinator.refreshOnce()

    expect(refresh).toHaveBeenCalledTimes(2)
    expect(first).toBe('token-a')
    expect(second).toBe('token-b')
  })

  it('propagates failure result to every waiter without retry storms', async () => {
    const refresh = vi.fn().mockResolvedValue(null)
    const coordinator = createRefreshCoordinator(refresh)

    const results = await Promise.all([
      coordinator.refreshOnce(),
      coordinator.refreshOnce(),
      coordinator.refreshOnce(),
    ])

    expect(refresh).toHaveBeenCalledTimes(1)
    expect(results).toEqual([null, null, null])
  })
})
