import { QueryClient } from '@tanstack/react-query'
import { expect, it } from 'vitest'
import { clearDeniedShowcaseHistory } from './showcaseCache'

it('a late history response cannot repopulate a denied user cache', async () => {
  const client = new QueryClient()
  const key = ['showcase-history', 1, 4]
  client.setQueryData(key, { items: ['old'] })
  client.setQueryData(['showcase-history', 2, 4], { items: ['other'] })
  let release: (value: { items: string[] }) => void = () => {}
  const pending = client.fetchQuery({ queryKey: key,
    queryFn: () => new Promise<{ items: string[] }>(resolve => { release = resolve }) }).catch(() => undefined)
  await clearDeniedShowcaseHistory(client, key)
  release({ items: ['late'] })
  await pending
  expect(client.getQueryData(key)).toEqual({ items: [] })
  expect(client.getQueryData(['showcase-history', 2, 4])).toEqual({ items: ['other'] })
  client.clear()
})
