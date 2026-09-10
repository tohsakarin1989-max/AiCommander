import type { QueryClient, QueryKey } from '@tanstack/react-query'

export async function clearDeniedShowcaseHistory(client: QueryClient, key: QueryKey) {
  const cancelled = client.cancelQueries({ queryKey: key, exact: true })
  client.setQueryData(key, { items: [] })
  await cancelled
  client.setQueryData(key, { items: [] })
}
