/**
 * Single-flight refresh coordination.
 *
 * Concurrency contract: when several API calls fail with 401 at the same
 * time, exactly one refresh request may be in flight; every waiter receives
 * the same new access token. After the attempt settles, the next 401 may
 * start a fresh refresh. A failed refresh resolves to `null` so callers can
 * drop the runtime session.
 */
export interface RefreshCoordinator {
  refreshOnce(): Promise<string | null>
}

export function createRefreshCoordinator(
  refresh: () => Promise<string | null>,
): RefreshCoordinator {
  let inFlight: Promise<string | null> | null = null

  return {
    refreshOnce(): Promise<string | null> {
      if (inFlight === null) {
        inFlight = refresh().finally(() => {
          inFlight = null
        })
      }
      return inFlight
    },
  }
}
