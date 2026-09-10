import type { CasePageParams } from '../../services/cases'
import type { Case } from '../../types'

export const caseDetailKey = (userId: number | undefined, sessionEpoch: number, caseId: number | null) =>
  ['cases', 'detail', userId, sessionEpoch, caseId] as const

export function visibleCaseDetail(query: { data?: Case; isSuccess: boolean }): Case | null {
  // React Query retains old data on a failed refetch; never show it after access denial.
  return query.isSuccess ? query.data ?? null : null
}

export interface CaseSearchDraft {
  keyword?: string
  statuses?: string[]
  caseTypes?: string[]
  oilTypes?: string[]
  startDate?: string
  endDate?: string
}

export function buildCaseSearchParams(draft: CaseSearchDraft): CasePageParams {
  const params: CasePageParams = {}
  if (draft.keyword?.trim()) params.keyword = draft.keyword.trim()
  if (draft.statuses?.length) params.statuses = [...draft.statuses]
  if (draft.caseTypes?.length) params.case_types = [...draft.caseTypes]
  if (draft.oilTypes?.length) params.oil_types = [...draft.oilTypes]
  // 两市业务日期按北京时间；显式时区不依赖浏览器所在时区。
  if (draft.startDate) params.start_date = new Date(`${draft.startDate}T00:00:00+08:00`).toISOString()
  if (draft.endDate) params.end_date = new Date(new Date(`${draft.endDate}T00:00:00+08:00`).getTime() + 86_400_000).toISOString()
  return params
}

export function parseCaseDeepLinkId(value: string | null): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null
  const id = Number(value)
  return Number.isSafeInteger(id) ? id : null
}
