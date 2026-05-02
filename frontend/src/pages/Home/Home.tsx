import { useState } from 'react'
import {
  Button, Modal, Alert, Progress, Descriptions,
  Timeline, Collapse, List, Tag, Typography, Space,
} from 'antd'
import {
  DatabaseOutlined, FileTextOutlined,
  ExclamationCircleOutlined, EnvironmentOutlined,
  NodeIndexOutlined,
  ThunderboltOutlined, WarningOutlined,
  SafetyCertificateOutlined, FireOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { caseApi } from '../../services/cases'
import { aiApi } from '../../services/ai'
import { analysisApi, SmartAnalysisReport } from '../../services/analysis'
import type { Case } from '../../types'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import './Home.css'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const { Text, Paragraph } = Typography


const STATUS_LABEL: Record<string, string> = {
  pending: '待处理', processing: '处理中', completed: '已完成',
  failed: '失败', needs_review: '待审核',
}

const RISK_LABEL: Record<string, string> = {
  critical: '极高风险', high: '高风险', medium: '中风险', low: '低风险',
}

/* 快速导航模块 */
const MODULES = [
  { path: '/cases',         icon: '⬛', label: '案件管理',   desc: '录入与管理案件信息' },
  { path: '/case-intelligence', icon: '◈', label: '案件研判', desc: '相似条件与防控参考' },
  { path: '/cases/features', icon: '◇', label: '特征提取', desc: '案件质量与结构化画像' },
  { path: '/cases/spacetime', icon: '◉', label: '时空研判', desc: '时间和空间规律分析' },
  { path: '/jurisdiction',  icon: '▦',  label: '辖区底座',   desc: '道路村屯井口空间基础' },
  { path: '/reports',       icon: '▤',  label: '研判报告',   desc: '沉淀复盘和专题材料' },
  { path: '/assistant',     icon: '◎',  label: '智能助手',   desc: '自然语言问答分析' },
]

const INTELLIGENCE_ACTIONS = [
  { title: '进入案件研判工作台', desc: '从单案出发生成标签、相似条件、区域画像和报告', path: '/case-intelligence' },
  { title: '补齐案件结构化字段', desc: '提升时空、相似条件和现场要素分析质量', path: '/cases/features' },
  { title: '维护辖区底座', desc: '道路、村屯、井口和重点区域是判断条件类似的基础', path: '/jurisdiction' },
  { title: '查看阶段性研判报告', desc: '把分析结果转为可复用材料', path: '/reports' },
]

const Home: React.FC = () => {
  const navigate = useNavigate()
  const [analysisModal, setAnalysisModal] = useState(false)
  const [analysisResult, setAnalysisResult] = useState<SmartAnalysisReport | null>(null)

  const smartAnalysisMutation = useMutation({
    mutationFn: () => analysisApi.smart.analyze({ time_window_days: 90, min_cases: 2 }),
    onSuccess: (data) => { setAnalysisResult(data); setAnalysisModal(true) },
  })

  const { data: cases }       = useQuery({ queryKey: ['cases'],       queryFn: () => caseApi.getCases() })
  const { data: conclusions } = useQuery({ queryKey: ['conclusions'], queryFn: () => aiApi.conclusion.list() })

  const stats = {
    totalCases:          cases?.length || 0,
    pendingCases:        cases?.filter((c: Case) => c.status === 'pending').length || 0,
    casesWithGeo:        cases?.filter((c: Case) => c.latitude != null && c.longitude != null).length || 0,
    highQualityCases:    cases?.filter((c: Case) => (c.quality_score || 0) >= 80).length || 0,
    analyzableCases:     cases?.filter((c: Case) => c.occurred_time && c.location && c.description).length || 0,
    pendingReview:       conclusions?.filter((c: any) => c.status === 'needs_review').length || 0,
  }

  const recentCases    = (cases    || []).slice(-5).reverse()

  /* ── KPI pills 数据 ── */
  const kpis = [
    { lbl: '案件总数',   val: stats.totalCases,        sub: '↗ 全部案件',    path: '/cases' },
    { lbl: '待处理',     val: stats.pendingCases,       sub: '需立即跟进',    path: '/cases' },
    { lbl: '带坐标案件', val: stats.casesWithGeo,       sub: '可做空间研判',  path: '/cases/map' },
    { lbl: '高质量案件', val: stats.highQualityCases,   sub: '可复用样本',    path: '/cases/features' },
    { lbl: '可研判案件', val: stats.analyzableCases,    sub: '具备核心字段',  path: '/case-intelligence' },
    { lbl: '待审核结论', val: stats.pendingReview,       sub: '等待人工确认',  path: '/conclusions' },
  ]

  return (
    <div className="page-scrollable">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>指挥中心</h1>
        <span className="sub">涉油案件 · AI 多智能体协作分析平台</span>
        <div style={{ marginLeft: 'auto' }}>
          <button
            className="btn-primary"
            onClick={() => smartAnalysisMutation.mutate()}
            disabled={smartAnalysisMutation.isPending}
          >
            <ThunderboltOutlined style={{ marginRight: 6 }} />
            {smartAnalysisMutation.isPending ? '分析中…' : '一键智能研判'}
          </button>
        </div>
      </div>

      {/* ── KPI 行 ── */}
      <div className="home-kpis-row">
        {kpis.map((k, i) => (
          <div key={i} className="kpill home-kpill--link" onClick={() => navigate(k.path)} title={k.lbl}>
            <div className="lbl">{k.lbl}</div>
            <div className="val">{k.val}</div>
            <div className="sub">{k.sub}</div>
          </div>
        ))}
      </div>

      {/* ── 快速导航模块 ── */}
      <div className="section-head" style={{ marginTop: 'var(--gap)' }}>快速导航</div>
      <div className="home-modules">
        {MODULES.map(m => (
          <div
            key={m.path}
            className="card home-module-card"
            onClick={() => navigate(m.path)}
          >
            <div className="card-head">
              <span className="ico">{m.icon}</span>
              <span className="ti">{m.label}</span>
            </div>
            <div className="card-body pad">
              <span style={{ color: 'var(--ink-2)', fontSize: 12 }}>{m.desc}</span>
            </div>
          </div>
        ))}
      </div>

      {/* ── 动态信息 2 列 ── */}
      <div className="home-activity">

        {/* 最近案件 */}
        <div className="card">
          <div className="card-head">
            <DatabaseOutlined className="ico" />
            <span className="ti">最近案件</span>
            <span className="spacer" />
            <button className="btn-ghost-sm" onClick={() => navigate('/cases')}>查看全部</button>
          </div>
          <div className="card-body scroll">
            {recentCases.length === 0 ? (
              <div className="empty-state"><span className="icon">📂</span>暂无案件记录</div>
            ) : recentCases.map((c: Case) => {
              const st = c.status as string
              const sevClass = st === 'failed' ? 'sev-crit'
                : st === 'needs_review' ? 'sev-hi'
                : st === 'processing'   ? 'sev-med'
                : 'sev-low'
              return (
                <div
                  key={c.id}
                  className={`alert-row ${sevClass}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate('/cases')}
                >
                  <div className="sev" />
                  <div className="glyph">C</div>
                  <div className="body">
                    <div className="ti">
                      <span className="no">{c.case_number}</span>
                      {STATUS_LABEL[c.status] || c.status}
                    </div>
                    <div className="sub">{c.location || '未知地点'}</div>
                  </div>
                  <div className="t">{dayjs(c.occurred_time).format('MM-DD HH:mm')}</div>
                </div>
              )
            })}
          </div>
        </div>

        {/* 研判入口 */}
        <div className="card">
          <div className="card-head">
            <SafetyCertificateOutlined className="ico" />
            <span className="ti">研判工作入口</span>
            <span className="spacer" />
            <button className="btn-ghost-sm" onClick={() => navigate('/case-intelligence')}>进入工作台</button>
          </div>
          <div className="card-body scroll">
            {INTELLIGENCE_ACTIONS.map((item, index) => (
                <div
                  key={item.path}
                  className={`alert-row ${index === 0 ? 'sev-hi' : index === 1 ? 'sev-med' : 'sev-low'}`}
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(item.path)}
                >
                  <div className="sev" />
                  <div className="glyph">R</div>
                  <div className="body">
                    <div className="ti">
                      <span className="no">{String(index + 1).padStart(2, '0')}</span>
                      {item.title}
                    </div>
                    <div className="sub">{item.desc}</div>
                  </div>
                  <div className="t">进入</div>
                </div>
            ))}
          </div>
        </div>

      </div>

      {/* ── 智能研判报告 Modal ── */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ThunderboltOutlined style={{ color: 'var(--accent)' }} />
            <span style={{ fontFamily: 'var(--serif)', color: 'var(--accent)', fontSize: 16, fontWeight: 500 }}>
              智能研判报告
            </span>
          </div>
        }
        open={analysisModal}
        onCancel={() => { setAnalysisModal(false); setAnalysisResult(null) }}
        footer={[
          <Button key="close" onClick={() => setAnalysisModal(false)}>关闭</Button>,
          <Button key="dep" type="primary" onClick={() => { setAnalysisModal(false); navigate('/case-intelligence') }}>
            进入案件研判工作台
          </Button>,
        ]}
        width={900}
        styles={{
          content: { background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 0 },
          header:  { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)' },
        }}
      >
        {analysisResult && (
          <div>
            <Alert
              message={
                <Space>
                  {analysisResult.summary.overall_risk_level === 'critical' && <FireOutlined style={{ color: 'var(--err)' }} />}
                  {analysisResult.summary.overall_risk_level === 'high'     && <WarningOutlined style={{ color: 'var(--warn)' }} />}
                  {analysisResult.summary.overall_risk_level === 'medium'   && <ExclamationCircleOutlined style={{ color: 'var(--warn)' }} />}
                  {analysisResult.summary.overall_risk_level === 'low'      && <SafetyCertificateOutlined style={{ color: 'var(--ok)' }} />}
                  <span>
                    整体风险等级：
                    <Tag color={analysisResult.summary.overall_risk_level === 'critical' ? 'red' : analysisResult.summary.overall_risk_level === 'high' ? 'orange' : analysisResult.summary.overall_risk_level === 'medium' ? 'gold' : 'green'}>
                      {RISK_LABEL[analysisResult.summary.overall_risk_level]}
                    </Tag>
                  </span>
                  <Progress percent={analysisResult.summary.overall_risk_score} size="small" style={{ width: 100 }}
                    status={analysisResult.summary.overall_risk_score >= 70 ? 'exception' : 'active'} />
                </Space>
              }
              type={['critical','high'].includes(analysisResult.summary.overall_risk_level) ? 'error' : analysisResult.summary.overall_risk_level === 'medium' ? 'warning' : 'success'}
              showIcon style={{ marginBottom: 16 }}
            />

            {analysisResult.summary.key_insights.length > 0 && (
              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', padding: '14px 16px', marginBottom: 12 }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>关键洞察</div>
                <List size="small"
                  dataSource={analysisResult.summary.key_insights}
                  renderItem={(item: string) => (
                    <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0' }}>
                      <span style={{ color: 'var(--ink-1)', fontSize: 13 }}>
                        <span style={{ color: 'var(--accent)', marginRight: 8, fontFamily: 'var(--mono)' }}>›</span>{item}
                      </span>
                    </List.Item>
                  )}
                />
              </div>
            )}

            {analysisResult.priority_actions.length > 0 && (
              <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', padding: '14px 16px', marginBottom: 12 }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>优先行动</div>
                <Timeline items={analysisResult.priority_actions.map(action => ({
                  color: action.priority === 1 ? 'var(--err)' : action.priority === 2 ? 'var(--warn)' : 'var(--info)',
                  children: (
                    <div>
                      <Text strong style={{ color: 'var(--ink-0)', fontSize: 13 }}>{action.action}</Text>
                      <br />
                      <Text style={{ color: 'var(--ink-2)', fontSize: 12 }}>{action.description}</Text>
                    </div>
                  ),
                }))} />
              </div>
            )}

            <Collapse items={[
              {
                key: 'hotspots',
                label: <Space><EnvironmentOutlined />热点区域 <Tag>{analysisResult.modules.hotspots?.hotspot_count || 0} 个</Tag></Space>,
                children: (
                  <Descriptions column={2} size="small">
                    <Descriptions.Item label="分析案件数">{analysisResult.modules.hotspots?.case_count || 0}</Descriptions.Item>
                    <Descriptions.Item label="识别热点数">{analysisResult.modules.hotspots?.hotspot_count || 0}</Descriptions.Item>
                    <Descriptions.Item label="高风险热点">{analysisResult.modules.hotspots?.high_risk_count || 0}</Descriptions.Item>
                  </Descriptions>
                ),
              },
              {
                key: 'gangs',
                label: <Space><NodeIndexOutlined />条件聚类 <Tag>{analysisResult.modules.gangs?.gang_count || 0} 个</Tag></Space>,
                children: (
                  <Descriptions column={2} size="small">
                    <Descriptions.Item label="相似条件组">{analysisResult.modules.gangs?.gang_count || 0}</Descriptions.Item>
                    <Descriptions.Item label="高关注条件组">{analysisResult.modules.gangs?.high_risk_gang_count || 0}</Descriptions.Item>
                    <Descriptions.Item label="涉及案件总数">{analysisResult.modules.gangs?.total_cases_in_gangs || 0}</Descriptions.Item>
                  </Descriptions>
                ),
              },
              {
                key: 'jurisdiction',
                label: (
                  <Space>
                    <DatabaseOutlined />
                    辖区底座
                    <Tag>{analysisResult.modules.jurisdiction?.data_quality?.coverage_score ?? 0} 分</Tag>
                  </Space>
                ),
                children: (
                  <div>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="底座要素">{analysisResult.modules.jurisdiction?.asset_summary?.total || 0}</Descriptions.Item>
                      <Descriptions.Item label="预防控点">{analysisResult.modules.jurisdiction?.patrol_plan?.control_points.length || 0}</Descriptions.Item>
                      <Descriptions.Item label="缺坐标">{analysisResult.modules.jurisdiction?.data_quality?.missing_coordinates || 0}</Descriptions.Item>
                      <Descriptions.Item label="疑似重复">{analysisResult.modules.jurisdiction?.data_quality?.duplicate_candidates || 0}</Descriptions.Item>
                    </Descriptions>
                    <List
                      size="small"
                      dataSource={analysisResult.modules.jurisdiction?.patrol_plan?.control_points || []}
                      renderItem={(item: any) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                          <List.Item.Meta
                            title={<Space><Tag color="gold">控点</Tag><span style={{ fontSize: 13 }}>{item.asset.name}</span></Space>}
                            description={<span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{item.reason}</span>}
                          />
                        </List.Item>
                      )}
                    />
                  </div>
                ),
              },
              {
                key: 'case-intelligence',
                label: (
                  <Space>
                    <SafetyCertificateOutlined />
                    案件研判
                    <Tag>{analysisResult.modules.case_intelligence?.suggestion_count || 0} 条建议</Tag>
                  </Space>
                ),
                children: (
                  <div>
                    <Descriptions column={2} size="small">
                      <Descriptions.Item label="特征标签">{analysisResult.modules.case_intelligence?.tag_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="相似案件">{analysisResult.modules.case_intelligence?.similar_case_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="区域画像">{analysisResult.modules.case_intelligence?.area_profile_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="防控建议">{analysisResult.modules.case_intelligence?.suggestion_count || 0}</Descriptions.Item>
                    </Descriptions>
                    <List
                      size="small"
                      dataSource={analysisResult.modules.case_intelligence?.insights || []}
                      renderItem={(item: string) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>{item}</List.Item>
                      )}
                    />
                  </div>
                ),
              },
              {
                key: 'deployment',
                label: <Space><FileTextOutlined />防控参考 <Tag>{analysisResult.modules.deployment?.suggestion_count || 0} 条</Tag></Space>,
                children: (
                  <List size="small"
                    dataSource={analysisResult.modules.deployment?.suggestions || []}
                    renderItem={(item: any) => (
                      <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                        <List.Item.Meta
                          title={<Space>
                            <Tag color={item.priority === 'high' ? 'red' : 'orange'}>{item.priority === 'high' ? '高优先级' : '中优先级'}</Tag>
                            <span style={{ fontSize: 13 }}>{item.action}</span>
                          </Space>}
                          description={<span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{item.reason}</span>}
                        />
                      </List.Item>
                    )}
                  />
                ),
              },
            ]} />

            {analysisResult.recommendations.length > 0 && (
              <div style={{ marginTop: 12, background: 'var(--bg-2)', border: '1px solid var(--line)', padding: '14px 16px' }}>
                <div style={{ fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase', marginBottom: 8 }}>综合建议</div>
                <List size="small"
                  dataSource={analysisResult.recommendations}
                  renderItem={(item: string, index: number) => (
                    <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0' }}>
                      <Space>
                        <Tag style={{ fontFamily: 'var(--mono)', fontSize: 10, borderRadius: 0 }}>{index + 1}</Tag>
                        <Paragraph style={{ color: 'var(--ink-1)', fontSize: 13, margin: 0 }}>{item}</Paragraph>
                      </Space>
                    </List.Item>
                  )}
                />
              </div>
            )}

            <div style={{ marginTop: 12, textAlign: 'right' }}>
              <Text style={{ fontSize: 11, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
                分析耗时：{analysisResult.duration_seconds?.toFixed(2) || '-'}s
              </Text>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

export default Home
