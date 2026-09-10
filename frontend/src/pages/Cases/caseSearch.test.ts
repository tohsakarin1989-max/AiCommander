import { describe, expect, it } from 'vitest'
import { buildCaseSearchParams, parseCaseDeepLinkId, caseDetailKey, visibleCaseDetail } from './caseSearch'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
import type { Case } from '../../types'

describe('case search contracts', () => {
  it('invalidates deep links with cases and hides cached data after a denied refetch', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const key = caseDetailKey(1, 1, 125)
    client.setQueryData(key, { id: 125, description: 'private' } as Case)
    const observer = new QueryObserver<Case>(client, { queryKey: key,
      queryFn: async () => { throw new Error('403') }, enabled: false })
    await client.invalidateQueries({ queryKey: ['cases'] })
    expect(client.getQueryState(key)?.isInvalidated).toBe(true)
    const denied = await observer.refetch()
    expect(denied.data?.description).toBe('private')
    expect(visibleCaseDetail(denied)).toBeNull()
    expect(caseDetailKey(2, 1, 125)).not.toEqual(key)
    expect(caseDetailKey(1, 2, 125)).not.toEqual(key)
    observer.destroy()
    client.clear()
  })
  it('sends multi-select filters to the server instead of filtering the loaded page', () => {
    expect(buildCaseSearchParams({ keyword: '  重点井 ', statuses: ['pending', 'resolved'], caseTypes: ['盗油'], oilTypes: ['原油'], startDate: '', endDate: '' }))
      .toMatchObject({ keyword: '重点井', statuses: ['pending', 'resolved'], case_types: ['盗油'], oil_types: ['原油'] })
  })

  it('includes the whole end date using a half-open China business-day interval', () => {
    expect(buildCaseSearchParams({ startDate: '2026-09-09', endDate: '2026-09-09' }))
      .toMatchObject({ start_date: '2026-09-08T16:00:00.000Z', end_date: '2026-09-09T16:00:00.000Z' })
  })

  it('omits empty selections and keyword', () => {
    expect(buildCaseSearchParams({ keyword: ' ', statuses: [], caseTypes: [], oilTypes: [] })).toEqual({})
  })

  it('rejects malformed deep links rather than opening a different case', () => {
    for (const value of [null, '', '12bad', '0', '-1', '1.5', '9007199254740992']) {
      expect(parseCaseDeepLinkId(value)).toBeNull()
    }
    expect(parseCaseDeepLinkId('125')).toBe(125)
  })
})
