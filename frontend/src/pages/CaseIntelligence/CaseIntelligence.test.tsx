import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CaseIntelligence, { ExperienceEvidence, FeatureTagDetails, FrozenReportPanel, intelligenceCaseId, intelligenceErrorMessage, RetiredAreaProfiles, SemanticObservations, SimilarCaseCard, SimilarCasesPanel } from './CaseIntelligence'
import type { AreaProfilesPayload, ExperienceCardPayload, IntelligenceObservation, SimilarCaseItem } from '../../services/caseIntelligence'
import type { KnowledgeAssetRecord } from '../../services/knowledge'
import { caseIntelligenceApi } from '../../services/caseIntelligence'
import { ApiError, ErrorCode } from '../../utils/errors'

const state = vi.hoisted(() => ({ search: '?caseId=42', role: 'analyst',
  queries: [] as Array<{ queryKey: unknown[]; enabled?: boolean; queryFn?: () => unknown }>, failed: false,
}))
vi.mock('../../services/caseIntelligence', () => ({ caseIntelligenceApi: {
  getWorkbench: vi.fn(), getLlmContext: vi.fn(),
} }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 2, role: state.role }, sessionEpoch: 1 }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useSearchParams: () => [new URLSearchParams(state.search), vi.fn()] }))
vi.mock('../../components/CaseResult/LatestCaseResult', () => ({ default: ({ caseId }: { caseId: number }) => <div>统一成果案件 #{caseId}</div> }))
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ isPending: false, mutate: vi.fn() }),
  useQuery: (options: typeof state.queries[number]) => {
    state.queries.push(options)
    const name = options.queryKey[0]
    return { isLoading: false, isFetching: false,
      isError: name === 'case-intelligence-selected' && state.failed,
      data: name === 'cases-for-intelligence' ? [] : name === 'case-intelligence-selected'
        ? { id: options.queryKey[1], case_number: '超出近期列表的案件' } : undefined,
    }
  },
}))

describe('案件上下文与按需旧版工具', () => {
  beforeEach(() => { state.search = '?caseId=42'; state.role = 'analyst'; state.failed = false; state.queries = []; vi.clearAllMocks() })
  it('当前URL决定选中案件，不受最近200条案件列表限制', () => {
    const html = renderToStaticMarkup(<CaseIntelligence />)
    expect(html).toContain('统一成果案件 #42')
    expect(state.queries.find(item => item.queryKey[0] === 'case-intelligence-selected')?.queryKey[1]).toBe(42)
    expect(state.queries.find(item => item.queryKey[0] === 'cases-for-intelligence')?.enabled).toBe(false)
    state.search = '?caseId=999'
    expect(renderToStaticMarkup(<CaseIntelligence />)).toContain('统一成果案件 #999')
  })
  it('日常查看不自动请求旧版分析、图谱或经验生成相关资料', () => {
    renderToStaticMarkup(<CaseIntelligence />)
    for (const key of ['case-intelligence-workbench', 'case-diagram',
      'knowledge-assets', 'experience-reuse-recommendations', 'knowledge-reuse-records']) {
      expect(state.queries.find(item => item.queryKey[0] === key)?.enabled).toBe(false)
    }
    expect(state.queries.some(item => item.queryKey[0] === 'case-intelligence-llm-context')).toBe(false)
  })
  it.each(['?caseId=42&tool=experience', '?scope=global'])('兼容分析 %s 只请求一次工作台，不再重复请求模型上下文', async search => {
    state.search = search
    const html = renderToStaticMarkup(<CaseIntelligence />)
    const workbench = state.queries.filter(item => item.queryKey[0] === 'case-intelligence-workbench')
    expect(workbench).toHaveLength(1)
    expect(workbench[0].enabled).toBe(true)
    await workbench[0].queryFn?.()
    expect(caseIntelligenceApi.getWorkbench).toHaveBeenCalledTimes(1)
    expect(caseIntelligenceApi.getLlmContext).not.toHaveBeenCalled()
    expect(state.queries.some(item => item.queryKey[0] === 'case-intelligence-llm-context')).toBe(false)
    expect(html).toContain('空间邻近不等于涉案关联')
  })
  it('明确经验确认链接仍能打开兼容工具，普通查看不要求创建经验卡', () => {
    state.search = '?caseId=42&tool=experience'
    const html = renderToStaticMarkup(<CaseIntelligence />)
    expect(html).toContain('收起旧版分析工具')
    expect(html).toContain('不要求每起案件保存经验卡或报告')
    expect(state.queries.find(item => item.queryKey[0] === 'knowledge-assets')?.enabled).toBe(true)
  })
  it('无效编号和读取失败都不静默改为其他案件', () => {
    expect(intelligenceCaseId(new URLSearchParams('?caseId=-1'))).toBeUndefined()
    state.failed = true
    expect(renderToStaticMarkup(<CaseIntelligence />)).toContain('不自动切换到其他案件')
  })

  it('旧评分区只展示退役和替代入口，即使收到旧契约也不展示分数', () => {
    const payload: AreaProfilesPayload = { days: 30, radius_km: 1.5, profile_count: 1,
      items: [{ asset: { id: 'legacy-area', name: '不应作为新结果展示的旧区域', asset_type: 'area' },
        risk_score: 99, risk_level: 'high', case_count: 1, related_cases: [],
        common_tags: [], top_hours: [], risk_reasons: ['旧评分依据不应显示'],
      }],
    }
    const html = renderToStaticMarkup(<RetiredAreaProfiles payload={payload} onOpen={vi.fn()} />)
    expect(html).toContain('旧区域风险评分已停用')
    expect(html).toContain('查看区域综合研判')
    expect(html).not.toContain('不应作为新结果展示的旧区域')
    expect(html).not.toContain('99')
  })

  it.each([
    ['partial', '尚未获得完整检索结果'],
    ['unavailable', '统一历史检索暂不可用，不代表没有匹配案件'],
  ] as const)('历史检索 %s 不解释为无匹配或零风险', (state, text) => {
    const html = renderToStaticMarkup(<SimilarCasesPanel payload={{ state, principle: '检索支持度不是概率', items: [], coverage: { complete: false } }} />)
    expect(html).toContain(text)
    expect(html).toContain('授权候选 未知 起')
    expect(html).toContain('不能据此判断没有其他相关资料')
  })

  it('历史参考保留差异、版本与证据，不把匹配分显示为概率', () => {
    const item: SimilarCaseItem = { case: { id: 10, case_number: '历史参考-A' },
      similarity_score: 80, score: 0.8, reasons: ['共同条件仅供参考'], shared_tags: [], duplicate_warnings: [], components: {},
      different_conditions: [['tool', '软管', 'negated']], unmatched_query_conditions: [['oil', '原油', 'stated']],
      versions: { source_version: 'frozen-1' }, evidence_refs: [{ id: 'EV-1' }],
    }
    const html = renderToStaticMarkup(<SimilarCaseCard item={item} />)
    expect(html).toContain('检索支持度 0.800（非概率）')
    expect(html).toContain('不同条件：软管')
    expect(html).toContain('frozen-1')
    expect(html).toContain('EV-1')
    expect(html).not.toContain('80%')
    expect(html).toContain('/cases?caseId=10')
  })

  it('报告缺少冻结成果时保留409服务端提示，不建议同步重算', () => {
    const detail = '当前没有可访问的冻结案件成果，请等待后台成果生成后再整理报告；本操作不重新研判案情'
    expect(intelligenceErrorMessage({ response: { status: 409, data: { detail } } })).toBe(detail)
  })

  it('归一化ApiError保留冻结成果409提示，不退化为泛化错误', () => {
    const detail = '当前没有可访问的冻结案件成果，请等待后台成果生成后再整理报告；本操作不重新研判案情'
    const error = new ApiError(detail, ErrorCode.CONFLICT, 409, '保存报告快照', { detail })
    expect(intelligenceErrorMessage(error)).toBe(detail)
  })

  it('报告未保存时仅指向上方冻结成果，不展示或复制旧即时正文', () => {
    const html = renderToStaticMarkup(<FrozenReportPanel caseId={42} caseNumber="当前案件" selectedExperienceCount={1}
      canWrite saving={false} reports={[]} readError={false} onSave={vi.fn()} onReview={vi.fn()} onCopy={vi.fn()} />)
    expect(html).toContain('当前案件 · 冻结成果报告')
    expect(html).toContain('href="#case-frozen-result"')
    expect(html).toContain('查看实际快照正文')
    expect(html).toContain('尚未保存报告快照')
    expect(html).not.toContain('复制报告')
    expect(html).not.toContain('复制此版本')
    expect(html).not.toContain('规则兜底')
    expect(html).not.toContain('模型生成')
    expect(html).not.toContain('<pre')
  })

  it('报告版本只展示实际保存正文与其来源，保留经验引用和人工确认', () => {
    const asset: KnowledgeAssetRecord = { id: 77, version: 2, asset_type: 'case_report', status: 'draft', evidence_refs: [{ id: 'E-1' }],
      source_case_id: 42, title: '当前案件冻结成果报告', source_signature: 'case-result-12', source_data_version: 'frozen-12',
      content: { report: { markdown: '冻结结果B的保存正文' }, frozen_result: { id: 12 }, reused_experience: [{ id: 4 }],
        legacy_instant_report: { markdown: '旧即时结果A', title: '错误标题A' } },
    }
    const html = renderToStaticMarkup(<FrozenReportPanel caseId={42} caseNumber="当前案件" selectedExperienceCount={0}
      canWrite saving={false} reports={[asset]} readError={false} onSave={vi.fn()} onReview={vi.fn()} onCopy={vi.fn()} />)
    expect(html).toContain('冻结结果B的保存正文')
    expect(html).toContain('冻结成果 #12')
    expect(html).toContain('1 张历史经验卡')
    expect(html).toContain('复制此版本')
    expect(html).toContain('人工确认')
    expect(html).not.toContain('旧即时结果A')
    expect(html).not.toContain('错误标题A')
  })

  it('报告版本读取失败时不显示已缓存正文或空结果', () => {
    const asset: KnowledgeAssetRecord = { id: 77, version: 2, asset_type: 'case_report', status: 'draft',
      source_case_id: 42, title: '当前案件冻结成果报告', source_signature: 'case-result-12', source_data_version: 'frozen-12',
      evidence_refs: [], content: { report: { markdown: '不应显示的缓存正文' } },
    }
    const html = renderToStaticMarkup(<FrozenReportPanel caseId={42} selectedExperienceCount={0}
      canWrite={false} saving={false} reports={[asset]} readError onSave={vi.fn()} onReview={vi.fn()} onCopy={vi.fn()} />)
    expect(html).toContain('报告版本读取失败')
    expect(html).not.toContain('不应显示的缓存正文')
    expect(html).not.toContain('尚未保存报告快照')
  })

  it.each([
    ['negated', '否定陈述'], ['uncertain', '待核表述'], ['conflicting', '矛盾表述'],
  ] as const)('非肯定表述 %s 默认折叠并显示分类、状态与原文引用', (kind, label) => {
    const observation: IntelligenceObservation = { key: 'vehicle_tanker', label: '罐车', category: 'vehicle', kind,
      references: [{ field: 'description', quote: '未发现罐车，现场车辆类型待核' }],
    }
    const html = renderToStaticMarkup(<SemanticObservations observations={[observation]} />)
    expect(html).toContain('<details><summary>否定与待核表述（1）</summary>')
    expect(html).not.toContain('<details open')
    expect(html).toContain(label)
    expect(html).toContain('车辆')
    expect(html).toContain('案情描述')
    expect(html).toContain('未发现罐车，现场车辆类型待核')
    expect(html).toContain('不作为肯定标签或已确认事实')
    expect(html).not.toContain('<button')
  })

  it('肯定标签和非肯定表述分层，信息缺口在折叠区之外可见', () => {
    const html = renderToStaticMarkup(<FeatureTagDetails payload={{
      tags: [{ key: 'tool_hose', label: '软管', category: 'tool', confidence: 0.9, basis: ['明确记载'] }],
      observations: [{ key: 'vehicle_tanker', label: '罐车', category: 'vehicle', kind: 'negated',
        references: [{ field: 'description', quote: '未发现罐车' }] }],
      information_gaps: ['车辆类型尚需补充'], rule_version: 'semantic-compat-2',
    }} />)
    const positiveSection = html.slice(0, html.indexOf('<details>'))
    expect(positiveSection).toContain('软管')
    expect(positiveSection).not.toContain('罐车')
    expect(positiveSection).toContain('规则支持度 0.90（非概率）')
    expect(positiveSection).not.toContain('90%')
    expect(html.indexOf('车辆类型尚需补充')).toBeGreaterThan(html.indexOf('</details>'))
    expect(html).toContain('整理规则版本：semantic-compat-2')
  })

  it('经验预览复用同一非肯定引用与缺口展示，不生成额外流程', () => {
    const card: ExperienceCardPayload = { case_id: 42, case_number: '合成案件', summary: '经验摘要',
      what_happened: {}, why_it_matters: [], how_it_was_found: [], reusable_lessons: [], next_attention_points: [],
      evidence_basis: { observations: [{ key: 'vehicle_type', label: '车辆类型不一致', category: 'vehicle', kind: 'conflicting',
        references: [{ field: 'vehicle_info', path: ['vehicles', 0, 'type'], value: '皮卡' }, { field: 'description', quote: '车辆可能为罐车' }] }] },
      evidence_gaps: ['两处车辆记录不一致，需核实'],
    }
    const html = renderToStaticMarkup(<ExperienceEvidence card={card} />)
    expect(html).toContain('矛盾表述')
    expect(html).toContain('车辆信息 · vehicles.0.type')
    expect(html).toContain('皮卡')
    expect(html).toContain('车辆可能为罐车')
    expect(html.indexOf('两处车辆记录不一致，需核实')).toBeGreaterThan(html.indexOf('</details>'))
    expect(html).not.toContain('<button')
  })

  it('旧响应未提供非肯定记录时显示能力缺口，不解释为不存在', () => {
    const html = renderToStaticMarkup(<FeatureTagDetails payload={{ tags: [] }} />)
    expect(html).toContain('暂无肯定标签')
    expect(html).toContain('尚未提供否定与待核记录，不能据此判断不存在此类表述')
    expect(html).not.toContain('准确概率')
  })
})
