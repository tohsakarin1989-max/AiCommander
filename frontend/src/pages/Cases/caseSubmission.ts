import type { CaseCreate, CaseUpdatePayload } from '../../types'

export interface CaseSubmission {
  key: string
  caseId?: number
  payload: CaseCreate | CaseUpdatePayload
}

/** One logical submission owns an immutable JSON payload until its outcome is known. */
export function prepareCaseSubmission(payload: CaseCreate | CaseUpdatePayload, caseId?: number): CaseSubmission {
  return { key: crypto.randomUUID(), caseId, payload: JSON.parse(JSON.stringify(payload)) }
}

export function caseSaveFailure(error: unknown): { state: 'rejected' | 'unconfirmed' | 'conflict'; message: string } {
  const status = typeof error === 'object' && error !== null && 'status' in error ? Number(error.status) : undefined
  const detail = error instanceof Error ? error.message : '保存未完成'
  if (status === 409) return { state: 'conflict', message: `${detail}。本次提交内容和凭证已保留，请核对保存结果；不能换凭证另建案件。` }
  if (status && status >= 400 && status < 500 && status !== 408) {
    return { state: 'rejected', message: `${detail}。输入已保留，请核对后再保存。` }
  }
  return { state: 'unconfirmed', message: '尚未确认是否保存成功。输入和本次提交凭证已保留；请核对结果或用原请求安全重试，不要另建案件。' }
}

export async function resolveCaseSubmission(
  submission: CaseSubmission,
  api: {
    getCaseSubmission: (key: string) => Promise<{ status: 'completed' | 'unconfirmed'; case_id: number | null }>
    createCase: (payload: CaseCreate, key?: string) => Promise<{ id: number }>
    updateCase: (id: number, payload: CaseUpdatePayload) => Promise<{ id: number }>
  },
  retry = false,
): Promise<number | null> {
  if (submission.caseId !== undefined) {
    // PUT targets the same case; a GET cannot prove that this specific edit completed.
    return retry ? (await api.updateCase(submission.caseId, submission.payload as CaseUpdatePayload)).id : null
  }
  const receipt = await api.getCaseSubmission(submission.key)
  if (receipt.status === 'completed' && receipt.case_id !== null) return receipt.case_id
  // Unconfirmed can also mean permission changed. It never authorizes a new key.
  return retry ? (await api.createCase(submission.payload as CaseCreate, submission.key)).id : null
}
