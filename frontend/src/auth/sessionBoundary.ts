import type { QueryClient } from '@tanstack/react-query'

/** A new identity must never inherit cached data or late authentication responses. */
export function createSessionBoundary(client: QueryClient) {
  let revision = 0
  return {
    reset() {
      revision += 1
      // clear also cancels running queries; a late promise cannot reinsert its data.
      client.clear()
      return revision
    },
    isCurrent(value: number) { return value === revision },
  }
}
