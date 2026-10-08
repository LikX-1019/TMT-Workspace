/**
 * Central navigation helper for forced session termination.
 *
 * Keeping the redirect behind a function lets tests stub navigation without
 * touching the unforgeable `window.location` property.
 */
export function redirectToLogin(): void {
  window.location.assign('/login')
}
