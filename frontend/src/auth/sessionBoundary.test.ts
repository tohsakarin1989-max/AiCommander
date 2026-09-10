import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { createSessionBoundary } from './sessionBoundary'

describe('authentication query boundary', () => {
  it('clears cached private rows and cancels old in-flight responses', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const boundary = createSessionBoundary(client)
    client.setQueryData(['cases', 'page', 1], { secret: 'former user' })
    let finish!: (value: string) => void
    const pending = client.fetchQuery({ queryKey: ['cases', 'detail', 1, 125],
      queryFn: () => new Promise<string>(resolve => { finish = resolve }) }).catch(() => undefined)
    const oldRevision = boundary.reset()
    expect(client.getQueryCache().getAll()).toHaveLength(0)
    boundary.reset()
    expect(boundary.isCurrent(oldRevision)).toBe(false)
    finish('former user private detail')
    await pending
    expect(client.getQueryCache().getAll()).toHaveLength(0)
  })
})
