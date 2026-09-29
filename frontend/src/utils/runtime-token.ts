let accessToken: string | null = null

export function setRuntimeAccessToken(value: string | null): void {
  accessToken = value
}

export function getRuntimeAccessToken(): string | null {
  return accessToken
}

