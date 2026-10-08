import { describe, expect, it, vi } from 'vitest'
import { caseSaveFailure, prepareCaseSubmission, resolveCaseSubmission } from './caseSubmission'
import type { CaseCreate } from '../../types'

const draft = () => ({ description: '合成原文', initial_locations: [{ role: 'discovery', description: '合成点', precision: 'unknown' }] }) as CaseCreate
const api = () => ({
  getCaseSubmission: vi.fn().mockResolvedValue({ status: 'unconfirmed', case_id: null }),
  createCase: vi.fn().mockResolvedValue({ id: 17 }),
  updateCase: vi.fn().mockResolvedValue({ id: 17 }),
})

describe('案件一次逻辑提交与不确定结果', () => {
  it('冻结整份payload，后续表单改变不能改写原请求', () => {
    const original = draft(), attempt = prepareCaseSubmission(original)
    original.description = '后来改写'
    original.initial_locations![0].description = '后来地点'
    expect(attempt.payload.description).toBe('合成原文')
    expect(attempt.payload.initial_locations![0].description).toBe('合成点')
    expect(attempt.key).toMatch(/^[0-9a-f-]{36}$/)
  })
  it('超时查到已完成，返回本案并且不再POST', async () => {
    const client = api(), attempt = prepareCaseSubmission(draft())
    client.getCaseSubmission.mockResolvedValue({ status: 'completed', case_id: 29 })
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(29)
    expect(client.createCase).not.toHaveBeenCalled()
  })
  it('unconfirmed不是未执行；只读查询不POST，安全重试仍用同key和payload', async () => {
    const client = api(), attempt = prepareCaseSubmission(draft())
    expect(await resolveCaseSubmission(attempt, client)).toBeNull()
    expect(client.createCase).not.toHaveBeenCalled()
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(17)
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(17)
    expect(client.createCase.mock.calls).toEqual([[attempt.payload, attempt.key], [attempt.payload, attempt.key]])
  })
  it('查询断网或撤权不能转为新建', async () => {
    const client = api(), attempt = prepareCaseSubmission(draft())
    client.getCaseSubmission.mockRejectedValue(Object.assign(new Error('不可访问'), { status: 403 }))
    await expect(resolveCaseSubmission(attempt, client, true)).rejects.toThrow('不可访问')
    expect(client.createCase).not.toHaveBeenCalled()
  })
  it('编辑重试只PUT同一案件；不能以当前GET内容证明这笔编辑成功', async () => {
    const client = api(), attempt = prepareCaseSubmission(draft(), 17)
    expect(await resolveCaseSubmission(attempt, client)).toBeNull()
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(17)
    expect(client.updateCase).toHaveBeenCalledWith(17, attempt.payload)
    expect(client.createCase).not.toHaveBeenCalled(); expect(client.getCaseSubmission).not.toHaveBeenCalled()
  })
  it('区分确定拒绝、提交冲突及网络/服务不确定，均说明保留输入', () => {
    expect(caseSaveFailure(Object.assign(new Error('字段格式不符'), { status: 422 }))).toEqual({ state: 'rejected', message: expect.stringContaining('输入已保留') })
    expect(caseSaveFailure(Object.assign(new Error('凭证冲突'), { status: 409 }))).toEqual({ state: 'conflict', message: expect.stringContaining('不能换凭证另建案件') })
    for (const error of [new Error('timeout'), Object.assign(new Error('gateway'), { status: 504 })]) {
      expect(caseSaveFailure(error).state).toBe('unconfirmed')
    }
  })
  it('已消费草稿必须核对冻结请求，不能仅凭草稿已提交认定本页成功', async () => {
    const client = { ...api(), getDraft: vi.fn().mockResolvedValue({ status: 'submitted', submitted_case_id: 31 }), submitDraft: vi.fn().mockResolvedValue({ case_id: 31 }) }
    const attempt = prepareCaseSubmission(draft(), undefined, { key: 'persisted-key', draftId: 'private-draft', draftRevision: 3 })
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(31)
    expect(client.submitDraft).toHaveBeenCalledWith('private-draft', 3, attempt.payload, true); expect(client.createCase).not.toHaveBeenCalled()
    expect(attempt.key).toBe('persisted-key')
  })
  it('另一页已提交不同内容时核对失败，不拿其case id冒充本页保存成功', async () => {
    const client = { ...api(), getDraft: vi.fn().mockResolvedValue({ status: 'submitted', submitted_case_id: 31 }),
      submitDraft: vi.fn().mockRejectedValue(Object.assign(new Error('草稿已提交，重试内容不一致'), { status: 409 })) }
    const attempt = prepareCaseSubmission(draft(), undefined, { key: 'persisted-key', draftId: 'private-draft', draftRevision: 3 })
    await expect(resolveCaseSubmission(attempt, client)).rejects.toThrow('重试内容不一致')
    expect(attempt.payload.description).toBe('合成原文'); expect(client.createCase).not.toHaveBeenCalled()
  })
  it('未提交草稿安全重试保持同草稿版本与payload，撤权不绕行普通新增', async () => {
    const client = { ...api(), getDraft: vi.fn().mockResolvedValue({ status: 'active', submitted_case_id: null }), submitDraft: vi.fn().mockResolvedValue({ case_id: 32 }) }
    const attempt = prepareCaseSubmission(draft(), undefined, { key: 'persisted-key', draftId: 'private-draft', draftRevision: 3 })
    expect(await resolveCaseSubmission(attempt, client)).toBeNull()
    expect(client.submitDraft).not.toHaveBeenCalled()
    expect(await resolveCaseSubmission(attempt, client, true)).toBe(32)
    expect(client.submitDraft).toHaveBeenCalledWith('private-draft', 3, attempt.payload)
    client.getDraft.mockRejectedValue(Object.assign(new Error('不可访问'), { status: 404 }))
    await expect(resolveCaseSubmission(attempt, client, true)).rejects.toThrow('不可访问')
    expect(client.createCase).not.toHaveBeenCalled(); expect(client.submitDraft).toHaveBeenCalledTimes(1)
  })
  it('版本化编辑重试仍带原revision，冲突不回退旧PUT', async () => {
    const client = { ...api(), updateEditSnapshot: vi.fn().mockRejectedValue(Object.assign(new Error('case_revision_conflict'), { status: 409 })) }
    const attempt = prepareCaseSubmission(draft(), 17, { sourceRevision: 4 })
    await expect(resolveCaseSubmission(attempt, client, true)).rejects.toThrow('case_revision_conflict')
    expect(client.updateEditSnapshot).toHaveBeenCalledWith(17, 4, attempt.payload)
    expect(client.updateCase).not.toHaveBeenCalled(); expect(client.createCase).not.toHaveBeenCalled()
  })
})
