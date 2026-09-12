import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  List,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  BarChartOutlined,
  BulbOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CompassOutlined,
  CopyOutlined,
  FileTextOutlined,
  NodeIndexOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { caseApi } from '../../services/cases'
import { knowledgeApi } from '../../services/knowledge'
import { useAuth } from '../../auth/AuthContext'
import LatestCaseResult from '../../components/CaseResult/LatestCaseResult'
import {
  AreaProfile,
  IntelligenceCounterItem,
  LlmContextPack,
  IntelligenceTag,
  PreventionSuggestion,
  SimilarCaseItem,
  caseIntelligenceApi,
} from '../../services/caseIntelligence'
import type { Case, KnowledgeSearchResult, TagCurationResult } from '../../types'
import {
  buildReuseAuditLine,
  canSelectExperienceRecommendation,
  getCaseDiagramSummary,
  getExperienceStatusMeta,
  getKnowledgeAssetStatusMeta,
  getKnowledgeRoute,
  getKnowledgeSourceLabel,
  getReportDraftMeta,
  getReportMarkdown,
} from './caseIntelligencePresentation'
import './CaseIntelligence.css'

const { Paragraph, Text, Title } = Typography

const categoryLabels: Record<string, string> = {
  time: '时间',
  space: '空间',
  vehicle: '车辆',
  tool: '工具',
  defense: '防护',
  capture: '发现',
  oil: '油品',
  manual: '人工',
}

const priorityLabels: Record<string, { text: string; color: string }> = {
  high: { text: '高优先', color: 'red' },
  medium: { text: '中优先', color: 'gold' },
  low: { text: '低优先', color: 'green' },
}

const riskLabels: Record<string, { text: string; color: string }> = {
  high: { text: '高关注', color: 'red' },
  medium: { text: '中关注', color: 'gold' },
  low: { text: '低关注', color: 'green' },
}

const counterLabel = (item: IntelligenceCounterItem, keys: string[]) => {
  for (const key of keys) {
    const value = item[key]
    if (value !== undefined && value !== null) return String(value)
  }
  return '未命名'
}

const pct = (value?: number | null) => Math.max(0, Math.min(100, Math.round(value ?? 0)))

const formatEvidence = (value: unknown) => {
  if (value === null || value === undefined) return '未知依据'
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const tagColor = (category: string) => {
  if (category === 'time') return 'blue'
  if (category === 'space') return 'cyan'
  if (category === 'vehicle') return 'orange'
  if (category === 'tool') return 'volcano'
  if (category === 'defense') return 'red'
  if (category === 'capture') return 'green'
  return 'default'
}

const TagWall = ({ tags }: { tags: IntelligenceTag[] }) => {
  if (!tags.length) return <Empty description="暂无标签，需补充案件时间、地点、车辆工具和现场环境描述" />
  return (
    <div className="intel-tag-wall">
      {tags.map(tag => (
        <Tooltip key={tag.key} title={(tag.basis || []).join('；') || '暂无依据'}>
          <Tag color={tagColor(tag.category)} className="intel-tag">
            {categoryLabels[tag.category] || tag.category} · {tag.label}
            <span className="intel-tag-confidence">{Math.round(tag.confidence * 100)}%</span>
          </Tag>
        </Tooltip>
      ))}
    </div>
  )
}

const CounterList = ({
  items,
  keys,
  empty,
}: {
  items?: IntelligenceCounterItem[]
  keys: string[]
  empty: string
}) => {
  if (!items?.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={empty} />
  const max = Math.max(...items.map(item => item.count), 1)
  return (
    <div className="intel-counter-list">
      {items.slice(0, 8).map((item, index) => {
        const label = counterLabel(item, keys)
        return (
          <div className="intel-counter-row" key={`${label}-${index}`}>
            <span>{label}</span>
            <div className="intel-counter-bar">
              <i style={{ width: `${Math.max(8, (item.count / max) * 100)}%` }} />
            </div>
            <b>{item.count}</b>
          </div>
        )
      })}
    </div>
  )
}

const SimilarCaseCard = ({ item }: { item: SimilarCaseItem }) => (
  <Card className="intel-inner-card" size="small">
    <div className="intel-similar-head">
      <div>
        <Text strong>{item.case.case_number}</Text>
        <div className="intel-muted">
          {item.case.location || '未知地点'} · {item.case.occurred_time ? dayjs(item.case.occurred_time).format('YYYY-MM-DD HH:mm') : '未知时间'}
        </div>
      </div>
      <Progress type="circle" size={54} percent={pct(item.similarity_score)} />
    </div>
    <div className="intel-chip-line">
      {item.shared_tags.slice(0, 8).map(tag => <Tag key={tag}>{tag}</Tag>)}
    </div>
    <List
      size="small"
      dataSource={item.reasons}
      renderItem={reason => <List.Item>{reason}</List.Item>}
    />
    {!!item.duplicate_warnings.length && (
      <Alert
        type="warning"
        showIcon
        message="同人/同车锚点仅用于重复录入或同案拆分核验，不作为常态多案规律。"
        description={item.duplicate_warnings.join('；')}
      />
    )}
  </Card>
)

const SuggestionCard = ({ item }: { item: PreventionSuggestion }) => {
  const priority = priorityLabels[item.priority] || { text: item.priority, color: 'default' }
  return (
    <Card className="intel-inner-card" size="small">
      <div className="intel-suggestion-head">
        <Space>
          <BulbOutlined />
          <Text strong>{item.title}</Text>
          <Tag color={priority.color}>{priority.text}</Tag>
        </Space>
        <span className="intel-confidence">依据强度 {Math.round(item.confidence * 100)}%</span>
      </div>
      <Paragraph className="intel-action">{item.action}</Paragraph>
      <div className="intel-section-mini">依据</div>
      <List
        size="small"
        dataSource={item.reason}
        renderItem={reason => <List.Item>{reason}</List.Item>}
      />
      {!!item.evidence.length && (
        <>
          <div className="intel-section-mini">来源</div>
          <div className="intel-chip-line">
            {item.evidence.slice(0, 6).map((evidence, index) => (
              <Tag key={`${item.id}-${index}`}>{formatEvidence(evidence)}</Tag>
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

const AreaProfileCard = ({ profile }: { profile: AreaProfile }) => {
  const risk = riskLabels[profile.risk_level] || { text: profile.risk_level, color: 'default' }
  return (
    <Card className="intel-inner-card" size="small">
      <div className="intel-similar-head">
        <div>
          <Text strong>{profile.asset.name}</Text>
          <div className="intel-muted">
            {profile.asset.asset_type} · {profile.asset.verified ? '已核验' : '待核验'}
          </div>
        </div>
        <Space>
          <Tag color={risk.color}>{risk.text}</Tag>
          <Progress type="circle" size={54} percent={pct(profile.risk_score)} />
        </Space>
      </div>
      <div className="intel-chip-line">
        {profile.common_tags.slice(0, 6).map(item => (
          <Tag key={counterLabel(item, ['label'])}>{counterLabel(item, ['label'])} × {item.count}</Tag>
        ))}
      </div>
      <List
        size="small"
        dataSource={profile.risk_reasons}
        renderItem={reason => <List.Item>{reason}</List.Item>}
      />
      {!!profile.related_cases.length && (
        <div className="intel-muted">
          关联案件：{profile.related_cases.slice(0, 4).map(item => item.case_number).join('、')}
        </div>
      )}
    </Card>
  )
}

const KnowledgeResultCard = ({
  item,
  onOpen,
}: {
  item: KnowledgeSearchResult
  onOpen: (route: string) => void
}) => {
  const route = getKnowledgeRoute(item)
  return (
    <Card className="intel-inner-card" size="small">
      <div className="intel-suggestion-head">
        <Space wrap>
          <FileTextOutlined />
          <Text strong>{item.title}</Text>
          <Tag color="blue">{getKnowledgeSourceLabel(item.source_type)}</Tag>
          <Tag>检索参考 · 非概率</Tag>
        </Space>
        <Button size="small" disabled={!route} onClick={() => route && onOpen(route)}>
          查看来源
        </Button>
      </div>
      <Paragraph className="intel-action">{item.snippet}</Paragraph>
      {!!item.evidence_refs.length && (
        <div className="intel-chip-line">
          {item.evidence_refs.slice(0, 4).map((ref, index) => (
            <Tag key={`${item.source_type}-${item.source_id}-${index}`}>
              {formatEvidence(ref)}
            </Tag>
          ))}
        </div>
      )}
    </Card>
  )
}

const CaseDiagramPanel = ({ diagram }: { diagram: NonNullable<Awaited<ReturnType<typeof caseApi.getCaseDiagram>>> }) => (
  <Card
    title="一案一图"
    className="intel-panel-card intel-diagram-card"
    extra={<Tag>{getCaseDiagramSummary(diagram)}</Tag>}
  >
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <div className="intel-section-mini">事实节点</div>
        <div className="intel-diagram-node-grid">
          {diagram.nodes.map(node => (
            <div key={node.id} className="intel-diagram-node">
              <Tag>{node.type}</Tag>
              <b>{node.label}</b>
              {node.detail && <small>{node.detail}</small>}
            </div>
          ))}
        </div>
      </Col>
      <Col xs={24} lg={12}>
        <div className="intel-section-mini">关系链路</div>
        <List
          size="small"
          dataSource={diagram.edges}
          locale={{ emptyText: '暂无关系链路' }}
          renderItem={edge => (
            <List.Item>
              <Space direction="vertical" size={2}>
                <Text strong>{edge.label}</Text>
                <Text type="secondary">{edge.from} → {edge.to}</Text>
              </Space>
            </List.Item>
          )}
        />
      </Col>
    </Row>
    <Alert type="info" showIcon className="intel-boundary" message={diagram.boundary} />
  </Card>
)

const LlmContextPanel = ({
  contextPack,
  loading,
  onCopy,
}: {
  contextPack?: LlmContextPack
  loading: boolean
  onCopy: () => void
}) => {
  if (loading) return <div className="intel-loading"><Spin /> 正在整理模型上下文…</div>
  if (!contextPack) return <Empty description="暂无模型上下文" />
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card title="事实依据" className="intel-panel-card">
          <List
            size="small"
            dataSource={contextPack.facts}
            renderItem={item => <List.Item>{item}</List.Item>}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="模式推断" className="intel-panel-card">
          <List
            size="small"
            dataSource={contextPack.pattern_inferences.slice(0, 8)}
            renderItem={item => (
              <List.Item>
                <Space direction="vertical" size={2}>
                  <Text strong>{item.claim}</Text>
                  <Text type="secondary">依据：{item.basis?.join('；') || '暂无'}</Text>
                </Space>
              </List.Item>
            )}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="防控参考" className="intel-panel-card">
          <List
            size="small"
            dataSource={contextPack.prevention_references}
            renderItem={item => (
              <List.Item>
                <Space direction="vertical" size={2}>
                  <Text strong>{item.title}</Text>
                  <Text>{item.action}</Text>
                  <Text type="secondary">依据：{item.basis?.join('；') || '暂无'}</Text>
                </Space>
              </List.Item>
            )}
          />
        </Card>
      </Col>
      <Col xs={24} lg={12}>
        <Card title="信息缺口与边界" className="intel-panel-card">
          <div className="intel-section-mini">信息缺口</div>
          <List
            size="small"
            dataSource={contextPack.information_gaps}
            renderItem={item => <List.Item>{item}</List.Item>}
          />
          <div className="intel-section-mini">模型边界</div>
          <List
            size="small"
            dataSource={contextPack.system_boundary}
            renderItem={item => <List.Item>{item}</List.Item>}
          />
        </Card>
      </Col>
      <Col xs={24} lg={10}>
        <Card title="建议追问" className="intel-panel-card">
          <List
            size="small"
            dataSource={contextPack.recommended_questions}
            renderItem={item => <List.Item>{item}</List.Item>}
          />
        </Card>
      </Col>
      <Col xs={24} lg={14}>
        <Card
          title="可复制提示词"
          className="intel-panel-card"
          extra={<Button size="small" icon={<CopyOutlined />} onClick={onCopy}>复制</Button>}
        >
          <pre className="intel-report intel-context-prompt">{contextPack.llm_prompt}</pre>
        </Card>
      </Col>
    </Row>
  )
}

export function intelligenceCaseId(params: URLSearchParams): number | undefined {
  const value = params.get('caseId')
  return value && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : undefined
}

const intelligenceError = (error: unknown) => {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  message.error(typeof detail === 'string' ? detail : '操作未完成，请刷新后重试。原始案件记录未因此改变。')
}

const CaseIntelligence: React.FC = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user, sessionEpoch } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'analyst'
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedCaseId = intelligenceCaseId(searchParams)
  const globalMode = searchParams.get('scope') === 'global' && !selectedCaseId
  const selectCase = (value?: number) => {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous)
      next.delete('tool')
      if (value) { next.set('caseId', String(value)); next.delete('scope') }
      else { next.delete('caseId'); next.set('scope', 'global') }
      return next
    }, { replace: true })
  }
  const [days, setDays] = useState(365)
  const [limit, setLimit] = useState(8)
  const [knowledgeQuery, setKnowledgeQuery] = useState('')
  const [tagCurationResult, setTagCurationResult] = useState<TagCurationResult | null>(null)
  const [selectedExperienceAssetIds, setSelectedExperienceAssetIds] = useState<number[]>([])
  const [legacyAnalysis, setLegacyAnalysis] = useState(searchParams.get('tool') === 'experience')

  const casesQuery = useQuery({
    queryKey: ['cases-for-intelligence', user?.id, sessionEpoch],
    queryFn: () => caseApi.getCases({ limit: 200 }),
    enabled: !selectedCaseId || legacyAnalysis,
  })

  useEffect(() => {
    if (!globalMode && !searchParams.has('caseId') && !casesQuery.isError && casesQuery.data?.length) {
      setSearchParams(previous => {
        const next = new URLSearchParams(previous)
        next.set('caseId', String(casesQuery.data![0].id))
        return next
      }, { replace: true })
    }
  }, [casesQuery.data, casesQuery.isError, searchParams, globalMode, setSearchParams])

  const selectedCaseQuery = useQuery({
    queryKey: ['case-intelligence-selected', selectedCaseId, user?.id, sessionEpoch],
    queryFn: ({ signal }) => caseApi.getCase(selectedCaseId!, signal),
    enabled: !!selectedCaseId,
  })

  useEffect(() => {
    setSelectedExperienceAssetIds([])
    setLegacyAnalysis(searchParams.get('tool') === 'experience')
    setTagCurationResult(null)
    setKnowledgeQuery('')
  }, [selectedCaseId, searchParams])

  const workbenchQuery = useQuery({
    queryKey: ['case-intelligence-workbench', selectedCaseId, days, limit, user?.id, sessionEpoch],
    queryFn: () => caseIntelligenceApi.getWorkbench({
      case_id: selectedCaseId,
      days,
      limit,
      radius_km: 1.5,
    }),
    enabled: !casesQuery.isLoading && (globalMode || (!!selectedCaseId && legacyAnalysis)),
  })

  const contextPackQuery = useQuery({
    queryKey: ['case-intelligence-llm-context', selectedCaseId, days, limit, user?.id, sessionEpoch],
    queryFn: () => caseIntelligenceApi.getLlmContext({
      case_id: selectedCaseId,
      days,
      limit,
      radius_km: 1.5,
    }),
    enabled: !casesQuery.isLoading && (globalMode || (!!selectedCaseId && legacyAnalysis)),
  })

  const diagramQuery = useQuery({
    queryKey: ['case-diagram', selectedCaseId, user?.id, sessionEpoch],
    queryFn: () => caseApi.getCaseDiagram(selectedCaseId as number),
    enabled: !!selectedCaseId && legacyAnalysis,
  })

  const knowledgeSearchQuery = useQuery({
    queryKey: ['case-knowledge-search', knowledgeQuery, selectedCaseId, user?.id, sessionEpoch],
    queryFn: () => knowledgeApi.search({
      q: knowledgeQuery,
      case_id: selectedCaseId,
      limit: 8,
    }),
    enabled: (globalMode || legacyAnalysis) && knowledgeQuery.trim().length > 0,
  })

  const tagCurationMutation = useMutation({
    mutationFn: (confirm: boolean) => caseIntelligenceApi.curateTags(selectedCaseId as number, confirm),
    onSuccess: (result) => {
      setTagCurationResult(result)
      message.info(
        result.applied
          ? `已确认写入 ${result.recommended_tags.length} 个标签`
          : `已生成 ${result.recommended_tags.length} 个候选标签，需人工确认后写入`,
      )
      queryClient.invalidateQueries({ queryKey: ['case-intelligence-workbench'] })
    },
    onError: intelligenceError,
  })

  const workbench = workbenchQuery.isError ? undefined : workbenchQuery.data
  const contextPack = contextPackQuery.isError ? undefined : contextPackQuery.data
  const selectedCase = selectedCaseQuery.isError ? undefined : selectedCaseQuery.data
  const loadedCases = casesQuery.isError ? [] : casesQuery.data || []
  const cases: Case[] = selectedCase && !loadedCases.some(item => item.id === selectedCase.id)
    ? [selectedCase, ...loadedCases] : loadedCases

  const knowledgeAssetsQuery = useQuery({
    queryKey: ['knowledge-assets', selectedCaseId, user?.id, sessionEpoch],
    queryFn: () => knowledgeApi.listAssets({ case_id: selectedCaseId, limit: 50 }),
    enabled: !!selectedCaseId && legacyAnalysis,
  })

  const reuseRecommendationsQuery = useQuery({
    queryKey: ['experience-reuse-recommendations', selectedCaseId, days, user?.id, sessionEpoch],
    queryFn: () => knowledgeApi.getReuseRecommendations(selectedCaseId as number, { days: Math.max(days, 730), limit: 8 }),
    enabled: !!selectedCaseId && legacyAnalysis,
  })

  const reuseRecordsQuery = useQuery({
    queryKey: ['knowledge-reuse-records', selectedCaseId, user?.id, sessionEpoch],
    queryFn: () => knowledgeApi.listReuseRecords(selectedCaseId as number, 50),
    enabled: !!selectedCaseId && legacyAnalysis,
  })

  const refreshKnowledgeAssets = () => {
    queryClient.invalidateQueries({ queryKey: ['knowledge-assets'] })
    queryClient.invalidateQueries({ queryKey: ['experience-reuse-recommendations'] })
    queryClient.invalidateQueries({ queryKey: ['knowledge-reuse-records'] })
    queryClient.invalidateQueries({ queryKey: ['case-knowledge-search'] })
  }

  const generateExperienceAssetMutation = useMutation({
    mutationFn: () => knowledgeApi.generateExperienceAsset(selectedCaseId as number),
    onSuccess: (asset) => {
      message.success(`经验卡 v${asset.version} 已保存为待复核版本`)
      refreshKnowledgeAssets()
      queryClient.invalidateQueries({ queryKey: ['case-intelligence-workbench'] })
    },
    onError: intelligenceError,
  })

  const reviewAssetMutation = useMutation({
    mutationFn: ({ assetId, status }: { assetId: number; status: 'confirmed' | 'archived' }) => (
      knowledgeApi.reviewAsset(assetId, {
        status,
        note: status === 'confirmed' ? '页面人工确认事实、证据和适用边界' : '页面人工归档',
      })
    ),
    onSuccess: (asset) => {
      message.success(asset.status === 'confirmed' ? `v${asset.version} 已确认` : `v${asset.version} 已归档`)
      refreshKnowledgeAssets()
    },
    onError: intelligenceError,
  })

  const reuseDecisionMutation = useMutation({
    mutationFn: ({ assetId, decision }: { assetId: number; decision: 'accepted' | 'rejected' }) => (
      knowledgeApi.recordReuseDecision({
        source_asset_id: assetId,
        target_case_id: selectedCaseId as number,
        decision,
        purpose: decision === 'accepted' ? '作为本案报告参考' : '当前案件不适用',
        note: decision === 'accepted' ? '人工选择，生成报告时仍需核对差异' : '人工判断当前条件不适用',
      })
    ),
    onSuccess: (_record, variables) => {
      if (variables.decision === 'accepted') {
        setSelectedExperienceAssetIds(ids => (
          ids.includes(variables.assetId) ? ids : [...ids, variables.assetId]
        ))
        message.success('已采纳为报告参考，尚未写入正式结论')
      } else {
        setSelectedExperienceAssetIds(ids => ids.filter(id => id !== variables.assetId))
        message.info('已记录为当前案件不适用')
      }
      refreshKnowledgeAssets()
    },
    onError: intelligenceError,
  })

  const reportSnapshotMutation = useMutation({
    mutationFn: () => knowledgeApi.generateReportSnapshot(selectedCaseId as number, {
      experience_asset_ids: selectedExperienceAssetIds,
      days,
      limit,
    }),
    onSuccess: (asset) => {
      message.success(`研判报告 v${asset.version} 已保存为待复核快照`)
      setSelectedExperienceAssetIds([])
      refreshKnowledgeAssets()
    },
    onError: intelligenceError,
  })

  const tags = workbench?.feature_tags.tags || []
  const qualityScore = workbench?.quality?.score ?? selectedCase?.quality_score ?? 0
  const qualityLevel = workbench?.quality?.level || selectedCase?.quality_level || 'unknown'
  const reportMarkdown = getReportMarkdown(workbench?.report)
  const reportMeta = getReportDraftMeta(workbench?.report)
  const experienceStatus = getExperienceStatusMeta(workbench?.experience_card?.manual_review_status)
  const knowledgeAssets = knowledgeAssetsQuery.isError ? [] : knowledgeAssetsQuery.data?.items || []
  const experienceAssetVersions = knowledgeAssets.filter(item => item.asset_type === 'experience_card')
  const reportSnapshots = knowledgeAssets.filter(item => item.asset_type === 'case_report')

  const copyReport = async () => {
    if (!reportMarkdown) return
    await navigator.clipboard.writeText(reportMarkdown)
    message.success('研判报告 Markdown 已复制')
  }

  const copyContextPrompt = async () => {
    if (!contextPack?.llm_prompt) return
    await navigator.clipboard.writeText(contextPack.llm_prompt)
    message.success('模型上下文提示词已复制')
  }

  return (
    <div className="page-scrollable intelligence-page">
      {searchParams.has('caseId') && !selectedCaseId && <Alert type="error" message="案件编号无效，请从案件列表打开。" />}
      {selectedCaseQuery.isError && <Alert type="error" message="案件信息暂不可用或当前账号无权访问，不自动切换到其他案件。" />}
      {casesQuery.isError && !selectedCaseId && <Alert type="error" message="案件列表读取失败，请刷新后重试。" />}
      <section className="intel-hero">
        <div>
          <div className="intel-eyebrow">CASE INTELLIGENCE WORKBENCH</div>
          <Title level={1}>案件研判工作台</Title>
          <Paragraph>
            查看案件自动形成的事实摘要、候选解释和证据，与案件详情及报告中心使用同一份版本化成果。
          </Paragraph>
        </div>
        <div className="intel-hero-card">
          <span>研判边界</span>
          <b>不预测犯罪</b>
          <small>只做规律归纳、条件比对和防控参考</small>
        </div>
      </section>

      <Card className="intel-control-card">
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} lg={11}>
            <Select
              showSearch
              allowClear
              placeholder="选择案件；清空后查看全局规律"
              value={selectedCaseId}
              onChange={selectCase}
              optionFilterProp="label"
              style={{ width: '100%' }}
              loading={casesQuery.isLoading}
              options={cases.map(item => ({
                value: item.id,
                label: `${item.case_number} · ${item.location || '未知地点'}`,
              }))}
            />
          </Col>
          <Col xs={12} lg={4}>
            <InputNumber
              min={30}
              disabled={!!selectedCaseId && !legacyAnalysis}
              max={3650}
              value={days}
              addonBefore="时间窗"
              addonAfter="天"
              onChange={(value) => setDays(Number(value || 365))}
              style={{ width: '100%' }}
            />
          </Col>
          <Col xs={12} lg={4}>
            <InputNumber
              min={3}
              disabled={!!selectedCaseId && !legacyAnalysis}
              max={30}
              value={limit}
              addonBefore="条数"
              onChange={(value) => setLimit(Number(value || 8))}
              style={{ width: '100%' }}
            />
          </Col>
          <Col xs={24} lg={5}>
            <Space wrap>
              <Button icon={<ApartmentOutlined />} onClick={() => selectCase(undefined)}>
                全局研判
              </Button>
              <Button
                type="primary"
                disabled={!!selectedCaseId && !legacyAnalysis}
                icon={<ReloadOutlined />}
                loading={workbenchQuery.isFetching}
                onClick={() => workbenchQuery.refetch()}
              >
                刷新
              </Button>
              <Button
                icon={<TagsOutlined />}
                disabled={!canWrite || !selectedCaseId || !legacyAnalysis}
                loading={tagCurationMutation.isPending}
                onClick={() => tagCurationMutation.mutate(false)}
              >
                标签策展
              </Button>
            </Space>
          </Col>
        </Row>
        {(!selectedCaseId || legacyAnalysis) && <Row gutter={[12, 12]} className="intel-search-row">
          <Col xs={24} lg={16}>
            <Input.Search
              allowClear
              placeholder="大模型研判搜索：案件画像、经验卡、报告、结论、告警"
              enterButton="检索"
              loading={knowledgeSearchQuery.isFetching}
              onSearch={(value) => setKnowledgeQuery(value.trim())}
            />
          </Col>
          <Col xs={24} lg={8}>
            <Text type="secondary">检索结果只返回带来源的事实、经验和引用，不直接生成结论。</Text>
          </Col>
        </Row>}
      </Card>

      {selectedCaseId && <>
        <LatestCaseResult key={selectedCaseId} caseId={selectedCaseId} />
        <Button onClick={() => setLegacyAnalysis(value => !value)} aria-expanded={legacyAnalysis}>
          {legacyAnalysis ? '收起旧版分析工具' : '打开旧版分析工具（兼容）'}
        </Button>
        {legacyAnalysis && <Alert type="warning" showIcon message="旧版动态分析与历史经验工具"
          description="按需使用：下方内容按旧接口即时计算，不是上方冻结成果；不要求每起案件保存经验卡或报告。时间窗仅作用于旧版工具。" />}
      </>}
      {(globalMode || legacyAnalysis) && contextPackQuery.isError && <Alert type="error" message="旧版模型上下文读取失败，不能据此判断证据完整。" />}

      {knowledgeQuery && (globalMode || legacyAnalysis) && (
        <Card
          className="intel-panel-card"
          title={`研判知识检索：${knowledgeQuery}`}
          extra={<Tag>{knowledgeSearchQuery.data?.total ?? 0} 条</Tag>}
        >
          {!knowledgeSearchQuery.isError && knowledgeSearchQuery.data?.state === 'partial' &&
            <Alert type="warning" message="检索尚未完成全部范围，以下是部分结果，不能据此判断没有其他关联。" />}
          {!knowledgeSearchQuery.isError && knowledgeSearchQuery.data?.history?.semantic_index_state === 'unavailable' &&
            <Alert type="warning" message="本地语义模型暂不可用，保留结构条件与词项检索。" />}
          {!knowledgeSearchQuery.isError && knowledgeSearchQuery.data?.history?.semantic_index_state === 'not_enabled' &&
            <Alert type="info" message="当前使用结构条件与词项检索，本地语义模型未启用。" />}
          {knowledgeSearchQuery.isError ? <Alert type="error" message="检索暂不可用，不能据此判断没有相关资料。" /> : knowledgeSearchQuery.isLoading ? (
            <div className="intel-loading intel-loading--small"><Spin /> 正在检索案件底座…</div>
          ) : knowledgeSearchQuery.data?.items.length ? (
            <div className="intel-card-stack">
              {knowledgeSearchQuery.data.items.map((item) => (
                <KnowledgeResultCard
                  key={`${item.source_type}-${item.source_id}`}
                  item={item}
                  onOpen={(route) => navigate(route)}
                />
              ))}
            </div>
          ) : (
            <Empty description={knowledgeSearchQuery.data?.state === 'partial'
              ? '当前部分结果尚无可引用来源，请稍后重试'
              : '本次条件未找到可引用来源，历史材料检索范围见下方说明'} />
          )}
          {knowledgeSearchQuery.data?.boundary && (
            <Alert type="info" showIcon className="intel-boundary" message={knowledgeSearchQuery.data.boundary} />
          )}
        </Card>
      )}

      {tagCurationResult && (
        <Card
          className="intel-panel-card"
          title="智能标签策展候选"
          extra={(
            <Space>
              <Tag color={tagCurationResult.applied ? 'green' : 'gold'}>
                {tagCurationResult.applied ? '已写入' : '待人工确认'}
              </Tag>
              {!tagCurationResult.applied && (
                <Button
                  size="small"
                  type="primary"
                  disabled={!canWrite || !selectedCaseId}
                  loading={tagCurationMutation.isPending}
                  onClick={() => tagCurationMutation.mutate(true)}
                >
                  确认写入标签
                </Button>
              )}
            </Space>
          )}
        >
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <div className="intel-section-mini">推荐标签</div>
              {tagCurationResult.recommended_tags.length ? (
                <div className="intel-tag-wall">
                  {tagCurationResult.recommended_tags.map((tag, index) => (
                    <Tooltip key={`${tag.key || tag.label || index}`} title={formatEvidence(tag.basis || tag.evidence || tag)}>
                      <Tag color="blue">
                        {String(tag.label || tag.key || '候选标签')}
                        {typeof tag.confidence === 'number' && (
                          <span className="intel-tag-confidence">{Math.round(tag.confidence * 100)}%</span>
                        )}
                      </Tag>
                    </Tooltip>
                  ))}
                </div>
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推荐标签" />
              )}
            </Col>
            <Col xs={24} lg={12}>
              <div className="intel-section-mini">合并和低置信提示</div>
              <List
                size="small"
                dataSource={[
                  ...tagCurationResult.merge_suggestions.map(item => `合并建议：${formatEvidence(item)}`),
                  ...tagCurationResult.low_confidence_tags.map(item => `低置信标签：${formatEvidence(item)}`),
                ]}
                locale={{ emptyText: '暂无合并或低置信提示' }}
                renderItem={item => <List.Item>{item}</List.Item>}
              />
            </Col>
          </Row>
          <Alert type="info" showIcon className="intel-boundary" message={tagCurationResult.boundary} />
        </Card>
      )}

      {selectedCaseId && !legacyAnalysis ? null : workbenchQuery.isError ? <Alert type="error" message="旧版分析暂不可用，原有统一成果仍可单独查看。" /> : workbenchQuery.isLoading ? (
        <div className="intel-loading"><Spin /> 正在汇聚案件、地图参考与油区业务资产…</div>
      ) : !workbench ? (
        <Empty description="暂无研判数据" />
      ) : (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={24} md={6}>
              <Card className="intel-kpi-card">
                <span>案件质量</span>
                <b>{Math.round(qualityScore || 0)}</b>
                <small>{qualityLevel}</small>
                <Progress percent={pct(qualityScore)} showInfo={false} />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card className="intel-kpi-card">
                <span>特征标签</span>
                <b>{tags.length}</b>
                <small>{Object.keys(workbench.feature_tags.category_counts || {}).length} 类要素</small>
                <Progress percent={pct(tags.length * 8)} showInfo={false} />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card className="intel-kpi-card">
                <span>相似案件</span>
                <b>{workbench.similar_cases.items.length}</b>
                <small>按作案条件匹配</small>
                <Progress percent={pct(workbench.similar_cases.items.length * 15)} showInfo={false} />
              </Card>
            </Col>
            <Col xs={24} md={6}>
              <Card className="intel-kpi-card">
                <span>防控建议</span>
                <b>{workbench.prevention_suggestions.suggestion_count}</b>
                <small>草案，不派发任务</small>
                <Progress percent={pct(workbench.prevention_suggestions.suggestion_count * 14)} showInfo={false} />
              </Card>
            </Col>
          </Row>

          {selectedCaseId && diagramQuery.data && (
            <CaseDiagramPanel diagram={diagramQuery.data} />
          )}

          <Alert
            type="info"
            showIcon
            className="intel-boundary"
            message="研判边界已收敛"
            description={workbench.prevention_suggestions.boundary}
          />

          <Tabs
            key={`${selectedCaseId ?? 'global'}:${searchParams.get('tool') || 'overview'}`}
            className="intel-tabs"
            defaultActiveKey={searchParams.get('tool') === 'experience' ? 'report' : 'overview'}
            items={[
              {
                key: 'overview',
                label: <span><TagsOutlined /> 总览标签</span>,
                children: (
                  <Row gutter={[16, 16]}>
                    <Col xs={24} lg={15}>
                      <Card title="案件特征标签" className="intel-panel-card">
                        <TagWall tags={tags} />
                      </Card>
                    </Col>
                    <Col xs={24} lg={9}>
                      <Card title="分析就绪度" className="intel-panel-card">
                        <div className="intel-readiness-grid">
                          {Object.entries(workbench.readiness || {}).map(([key, value]) => (
                            <div key={key} className={`intel-readiness-item intel-readiness-item--${value.status}`}>
                              <CheckCircleOutlined />
                              <b>{key}</b>
                              <span>{value.status}</span>
                              {!!value.blockers?.length && <small>{value.blockers.join('；')}</small>}
                            </div>
                          ))}
                        </div>
                      </Card>
                      <Card title="时空洞察" className="intel-panel-card">
                        <List
                          size="small"
                          dataSource={workbench.spatiotemporal.insights}
                          renderItem={item => <List.Item>{item}</List.Item>}
                        />
                      </Card>
                    </Col>
                  </Row>
                ),
              },
              {
                key: 'similar',
                label: <span><NodeIndexOutlined /> 相似条件</span>,
                children: (
                  <Card title="相似案件分析" className="intel-panel-card">
                    <Alert type="success" showIcon message={workbench.similar_cases.principle} />
                    <div className="intel-card-stack">
                      {workbench.similar_cases.items.length ? (
                        workbench.similar_cases.items.map(item => (
                          <SimilarCaseCard key={item.case.id} item={item} />
                        ))
                      ) : (
                        <Empty description="暂无相似案件，可能是历史样本不足或本案字段不完整" />
                      )}
                    </div>
                  </Card>
                ),
              },
              {
                key: 'time-space',
                label: <span><ClockCircleOutlined /> 时空规律</span>,
                children: (
                  <Row gutter={[16, 16]}>
                    <Col xs={24} lg={8}>
                      <Card title="高频时段" className="intel-panel-card">
                        <CounterList items={workbench.spatiotemporal.period_distribution} keys={['period']} empty="暂无时段统计" />
                      </Card>
                    </Col>
                    <Col xs={24} lg={8}>
                      <Card title="高频小时" className="intel-panel-card">
                        <CounterList items={workbench.spatiotemporal.hour_distribution} keys={['hour']} empty="暂无小时统计" />
                      </Card>
                    </Col>
                    <Col xs={24} lg={8}>
                      <Card title="发现方式" className="intel-panel-card">
                        <CounterList items={workbench.spatiotemporal.source_distribution} keys={['source_type']} empty="暂无发现方式统计" />
                      </Card>
                    </Col>
                    <Col xs={24}>
                      <Card title="空间热点网格" className="intel-panel-card">
                        {workbench.spatiotemporal.hotspots.length ? (
                          <List
                            dataSource={workbench.spatiotemporal.hotspots}
                            renderItem={item => (
                              <List.Item>
                                <Space direction="vertical" size={2}>
                                  <Text strong>{item.center.latitude}, {item.center.longitude}</Text>
                                  <Text type="secondary">关联 {item.case_count} 起：{item.case_numbers.join('、')}</Text>
                                </Space>
                              </List.Item>
                            )}
                          />
                        ) : (
                          <Empty description="案件坐标不足，暂不能形成空间热点" />
                        )}
                      </Card>
                    </Col>
                  </Row>
                ),
              },
              {
                key: 'scene',
                label: <span><CompassOutlined /> 现场要素</span>,
                children: (
                  <Row gutter={[16, 16]}>
                    <Col xs={24} lg={12}>
                      <Card title="地点条件" className="intel-panel-card">
                        <TagWall tags={workbench.scene_analysis.location_conditions || []} />
                      </Card>
                    </Col>
                    <Col xs={24} lg={12}>
                      <Card title="抓获/发现经验" className="intel-panel-card">
                        {Array.isArray(workbench.scene_analysis.capture_experience) ? (
                          <CounterList items={workbench.scene_analysis.capture_experience} keys={['label']} empty="暂无发现方式统计" />
                        ) : (
                          <Paragraph>{workbench.scene_analysis.capture_experience.lesson || '暂无发现方式经验'}</Paragraph>
                        )}
                      </Card>
                    </Col>
                    <Col xs={24} lg={8}>
                      <Card title="车辆特征" className="intel-panel-card">
                        <CounterList items={workbench.scene_analysis.vehicle_tool_patterns.vehicles} keys={['label']} empty="暂无车辆特征" />
                      </Card>
                    </Col>
                    <Col xs={24} lg={8}>
                      <Card title="工具痕迹" className="intel-panel-card">
                        <CounterList items={workbench.scene_analysis.vehicle_tool_patterns.tools} keys={['label']} empty="暂无工具痕迹" />
                      </Card>
                    </Col>
                    <Col xs={24} lg={8}>
                      <Card title="现场薄弱点" className="intel-panel-card">
                        <CounterList items={workbench.scene_analysis.site_weaknesses} keys={['label']} empty="暂无薄弱点统计" />
                      </Card>
                    </Col>
                    <Col xs={24}>
                      <Card title="可复用规则" className="intel-panel-card">
                        <List
                          dataSource={workbench.scene_analysis.reusable_rules || []}
                          renderItem={item => <List.Item>{item}</List.Item>}
                          locale={{ emptyText: '暂无规则，需补充现场环境、车辆工具和发现方式' }}
                        />
                      </Card>
                    </Col>
                  </Row>
                ),
              },
              {
                key: 'areas',
                label: <span><BarChartOutlined /> 区域画像</span>,
                children: (
                  <Card title="风险区域画像" className="intel-panel-card">
                    <div className="intel-card-stack">
                      {workbench.area_profiles.items.length ? (
                        workbench.area_profiles.items.map(profile => (
                          <AreaProfileCard key={profile.asset.id} profile={profile} />
                        ))
                      ) : (
                        <Empty description="业务资产或案件坐标不足，暂不能形成区域画像" />
                      )}
                    </div>
                  </Card>
                ),
              },
              {
                key: 'suggestions',
                label: <span><SafetyCertificateOutlined /> 防控建议</span>,
                children: (
                  <Card title="防控建议草案" className="intel-panel-card">
                    <div className="intel-card-stack">
                      {workbench.prevention_suggestions.items.length ? (
                        workbench.prevention_suggestions.items.map(item => (
                          <SuggestionCard key={item.id} item={item} />
                        ))
                      ) : (
                        <Empty description="暂无足够依据生成建议" />
                      )}
                    </div>
                  </Card>
                ),
              },
              {
                key: 'llm-context',
                label: <span><RobotOutlined /> 模型上下文</span>,
                children: (
                  <LlmContextPanel
                    contextPack={contextPack}
                    loading={contextPackQuery.isLoading}
                    onCopy={copyContextPrompt}
                  />
                ),
              },
              {
                key: 'report',
                label: <span><FileTextOutlined /> 复盘报告</span>,
                children: (
                  <Row gutter={[16, 16]}>
                    <Col xs={24} lg={10}>
                      <Card title="案件复盘卡" className="intel-panel-card">
                        {workbench.experience_card ? (
                          <Space direction="vertical" size={12} style={{ width: '100%' }}>
                            <Space wrap>
                              <Tag color={experienceStatus.color}>{experienceStatus.label}</Tag>
                              <Button
                                size="small"
                                icon={<CheckCircleOutlined />}
                                disabled={!canWrite || !selectedCaseId}
                                loading={generateExperienceAssetMutation.isPending}
                                onClick={() => generateExperienceAssetMutation.mutate()}
                              >
                                保存经验卡版本
                              </Button>
                            </Space>
                            <Alert
                              type="info"
                              showIcon
                              message="当前内容是即时预览；保存后形成独立版本，人工确认后才进入历史经验推荐。"
                            />
                            <Paragraph>{workbench.experience_card.summary}</Paragraph>
                            <div className="intel-section-mini">为什么值得沉淀</div>
                            <List
                              size="small"
                              dataSource={workbench.experience_card.why_it_matters}
                              renderItem={item => <List.Item>{item}</List.Item>}
                            />
                            <div className="intel-section-mini">后续关注点</div>
                            <List
                              size="small"
                              dataSource={workbench.experience_card.next_attention_points}
                              renderItem={item => <List.Item>{item}</List.Item>}
                            />
                            <div className="intel-section-mini">版本记录</div>
                            {knowledgeAssetsQuery.isError ? <Alert type="error" message="经验版本读取失败，不能确认当前是否有待确认内容。" /> : knowledgeAssetsQuery.isLoading ? (
                              <div className="intel-loading intel-loading--small"><Spin /> 正在读取版本…</div>
                            ) : experienceAssetVersions.length ? (
                              <List
                                size="small"
                                dataSource={experienceAssetVersions}
                                renderItem={asset => {
                                  const statusMeta = getKnowledgeAssetStatusMeta(asset.status)
                                  return (
                                    <List.Item
                                      actions={[
                                        asset.status === 'draft' ? (
                                          <Button
                                            key="confirm"
                                            size="small"
                                            disabled={!canWrite}
                                            loading={reviewAssetMutation.isPending && reviewAssetMutation.variables?.assetId === asset.id}
                                            onClick={() => reviewAssetMutation.mutate({ assetId: asset.id, status: 'confirmed' })}
                                          >
                                            人工确认
                                          </Button>
                                        ) : null,
                                        asset.status !== 'archived' ? (
                                          <Button
                                            key="archive"
                                            size="small"
                                            disabled={!canWrite}
                                            onClick={() => reviewAssetMutation.mutate({ assetId: asset.id, status: 'archived' })}
                                          >
                                            归档
                                          </Button>
                                        ) : null,
                                      ].filter(Boolean)}
                                    >
                                      <List.Item.Meta
                                        title={<Space><Text strong>v{asset.version}</Text><Tag color={statusMeta.color}>{statusMeta.label}</Tag></Space>}
                                        description={`${asset.evidence_refs.length} 条证据引用 · ${asset.reviewer_label || '尚未复核'}`}
                                      />
                                    </List.Item>
                                  )
                                }}
                              />
                            ) : (
                              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未保存独立经验卡版本" />
                            )}
                          </Space>
                        ) : (
                          <Empty description="全局模式下不生成单案复盘卡，请选择案件" />
                        )}
                      </Card>
                      <Card title="历史优秀案例复用" className="intel-panel-card">
                        {reuseRecommendationsQuery.data?.boundary && (
                          <Alert type="warning" showIcon message={reuseRecommendationsQuery.data.boundary} />
                        )}
                        {reuseRecommendationsQuery.isError ? <Alert type="error" message="历史经验查询暂不可用，不等于没有相关经验。" /> : reuseRecommendationsQuery.isLoading ? (
                          <div className="intel-loading intel-loading--small"><Spin /> 正在召回经验资产…</div>
                        ) : reuseRecommendationsQuery.data?.items.length ? (
                          <List
                            size="small"
                            dataSource={reuseRecommendationsQuery.data.items}
                            renderItem={item => (
                              <List.Item
                                actions={[
                                  <Button
                                    key="accept"
                                    size="small"
                                    type={selectedExperienceAssetIds.includes(item.asset_id) ? 'primary' : 'default'}
                                    disabled={
                                      !canWrite || !canSelectExperienceRecommendation(item)
                                      || selectedExperienceAssetIds.includes(item.asset_id)
                                    }
                                    loading={reuseDecisionMutation.isPending && reuseDecisionMutation.variables?.assetId === item.asset_id}
                                    onClick={() => reuseDecisionMutation.mutate({ assetId: item.asset_id, decision: 'accepted' })}
                                  >
                                    {selectedExperienceAssetIds.includes(item.asset_id)
                                      ? '已选入报告'
                                      : item.already_reused
                                        ? '再次选入报告'
                                        : '采纳并选入'}
                                  </Button>,
                                  <Button
                                    key="reject"
                                    size="small"
                                    disabled={!canWrite || item.already_reused}
                                    onClick={() => reuseDecisionMutation.mutate({ assetId: item.asset_id, decision: 'rejected' })}
                                  >不适用</Button>,
                                  <Button key="source" size="small" onClick={() => navigate(`/case-intelligence?caseId=${item.source_case_id}`)}>来源</Button>,
                                ]}
                              >
                                <List.Item.Meta
                                  title={(
                                    <Space wrap>
                                      <Text strong>{item.title}</Text>
                                      <Tag color="green">已确认 v{item.version}</Tag>
                                      <Tag color="blue">相似度 {Math.round(item.similarity_score)}%</Tag>
                                    </Space>
                                  )}
                                  description={(
                                    <Space direction="vertical" size={4}>
                                      <Text>{item.summary}</Text>
                                      <Text type="secondary">适用依据：{item.applicability_reasons.slice(0, 2).join('；')}</Text>
                                      <Text type="warning">差异提示：{item.mismatch_risks.slice(0, 2).join('；')}</Text>
                                    </Space>
                                  )}
                                />
                              </List.Item>
                            )}
                          />
                        ) : (
                          <Empty description="暂无相似且已人工确认的历史经验资产" />
                        )}
                      </Card>
                    </Col>
                    <Col xs={24} lg={14}>
                      <Card
                        title={workbench.report.title}
                        className="intel-panel-card"
                        extra={(
                          <Space>
                            <Tag>{reportMeta.draftStatus}</Tag>
                            <Tag color="gold">{reportMeta.reviewStatus}</Tag>
                            <Tag color="blue">{reportMeta.modelStatus}</Tag>
                            <Button size="small" onClick={copyReport}>复制报告</Button>
                            <Button
                              size="small"
                              type="primary"
                              disabled={!canWrite || !selectedCaseId}
                              loading={reportSnapshotMutation.isPending}
                              onClick={() => reportSnapshotMutation.mutate()}
                            >
                              保存报告快照{selectedExperienceAssetIds.length ? `（引用 ${selectedExperienceAssetIds.length}）` : ''}
                            </Button>
                          </Space>
                        )}
                      >
                        <Alert
                          type="info"
                          showIcon
                          message={`当前选择 ${selectedExperienceAssetIds.length} 张历史经验卡；保存后仍为待人工复核草稿。`}
                        />
                        <pre className="intel-report">{reportMarkdown}</pre>
                        <div className="intel-section-mini">报告版本</div>
                        <List
                          size="small"
                          dataSource={reportSnapshots}
                          locale={{ emptyText: '尚未保存报告快照' }}
                          renderItem={asset => {
                            const statusMeta = getKnowledgeAssetStatusMeta(asset.status)
                            return (
                              <List.Item
                                actions={asset.status === 'draft' ? [
                                  <Button
                                    key="confirm-report"
                                    size="small"
                                    disabled={!canWrite}
                                    onClick={() => reviewAssetMutation.mutate({ assetId: asset.id, status: 'confirmed' })}
                                  >人工确认</Button>,
                                ] : []}
                              >
                                <List.Item.Meta
                                  title={<Space><Text strong>报告 v{asset.version}</Text><Tag color={statusMeta.color}>{statusMeta.label}</Tag></Space>}
                                  description={`${asset.evidence_refs.length} 条证据引用 · ${asset.content.reused_experience?.length || 0} 张历史经验卡`}
                                />
                              </List.Item>
                            )
                          }}
                        />
                        <div className="intel-section-mini">经验复用轨迹</div>
                        {reuseRecordsQuery.isError && <Alert type="error" message="经验复用轨迹读取失败，当前不能确认历史操作状态。" />}
                        <List
                          size="small"
                          dataSource={reuseRecordsQuery.isError ? [] : reuseRecordsQuery.data?.items || []}
                          locale={{ emptyText: '尚无采纳、排除或报告引用记录' }}
                          renderItem={item => (
                            <List.Item>
                              <Text>{buildReuseAuditLine(item)}</Text>
                            </List.Item>
                          )}
                        />
                      </Card>
                    </Col>
                  </Row>
                ),
              },
            ]}
          />
        </>
      )}
    </div>
  )
}

export default CaseIntelligence
