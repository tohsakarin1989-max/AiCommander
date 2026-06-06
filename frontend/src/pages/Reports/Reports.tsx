import { useState } from 'react'
import {
  Button,
  Modal,
  Collapse,
  List,
  Space,
  Spin,
  message,
} from 'antd'
import {
  EyeOutlined,
  DownloadOutlined,
  FileTextOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  BulbOutlined,
  TeamOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { aiApi } from '../../services/ai'
import { knowledgeApi } from '../../services/knowledge'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { buildReportPresentation, getReportDraftMeta, getReportExportMarkdown } from './reportPresentationModel'
import './Reports.css'

const Reports: React.FC = () => {
  const navigate = useNavigate()
  const { data: meetings, isLoading } = useQuery({
    queryKey: ['meetings'],
    queryFn: () => aiApi.meeting.list(),
  })

  const completedMeetings = meetings?.filter((m) => m.status === 'completed') || []

  const handleExportReport = (meetingId: string, report: any) => {
    try {
      const markdown = getReportExportMarkdown(meetingId, report, dayjs().format('YYYY-MM-DD HH:mm:ss'))
      const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `报告_${meetingId}_${dayjs().format('YYYYMMDD_HHmmss')}.md`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      message.success('Markdown 报告导出成功')
    } catch {
      message.error('导出失败')
    }
  }

  return (
    <div className="page-scrollable">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>分析报告</h1>
        <span className="sub">AI 圆桌会议 · 综合研判结果</span>
        <div style={{ marginLeft: 'auto' }}>
          <button className="btn-ghost" onClick={() => navigate('/meetings')}>
            <TeamOutlined style={{ marginRight: 6 }} />
            查看所有会议
          </button>
        </div>
      </div>

      {/* ── 统计条 ── */}
      <div className="rp-stats-row">
        <div className="kpill">
          <div className="lbl">已完成报告</div>
          <div className="val">{completedMeetings.length}</div>
          <div className="sub">会议研判结果</div>
        </div>
        <div className="kpill">
          <div className="lbl">覆盖案件</div>
          <div className="val">
            {completedMeetings.reduce((acc, m) => acc + (m.case_ids?.length || 0), 0)}
          </div>
          <div className="sub">已分析案件总数</div>
        </div>
      </div>

      {/* ── 过滤标签行 ── */}
      <div className="rp-filter-row">
        <span className="rp-filter-chip rp-filter-chip--active">全部</span>
        <span className="rp-filter-chip">待审核</span>
        <span className="rp-filter-chip">已完成</span>
      </div>

      {/* ── 主内容 ── */}
      {isLoading ? (
        <div className="rp-skeleton-list">
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton rp-skeleton-card" />
          ))}
        </div>
      ) : completedMeetings.length === 0 ? (
        <div className="empty-state">
          <div className="icon"><FileTextOutlined /></div>
          <div>暂无分析报告</div>
          <div style={{ fontSize: 11, color: 'var(--ink-3)', textAlign: 'center', maxWidth: 280 }}>
            请先创建并完成圆桌会议，完成后会在此显示研判结果
          </div>
          <button className="btn-primary" onClick={() => navigate('/meetings')}>
            <ArrowRightOutlined style={{ marginRight: 6 }} />
            前往会议管理
          </button>
        </div>
      ) : (
        <div className="rp-list">
          {completedMeetings.map((meeting) => (
            <ReportCard
              key={meeting.meeting_id}
              meetingId={meeting.meeting_id}
              meeting={meeting}
              onExport={handleExportReport}
              onViewDetail={() => navigate(`/meetings?meetingId=${meeting.meeting_id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── 报告卡片 ─────────────────────────────────────────────── */
interface ReportCardProps {
  meetingId: string
  meeting?: any
  onExport: (meetingId: string, report: any) => void
  onViewDetail: () => void
}

const ReportCard: React.FC<ReportCardProps> = ({ meetingId, meeting, onExport, onViewDetail }) => {
  const [detailModalVisible, setDetailModalVisible] = useState(false)

  const { data: report, isLoading } = useQuery({
    queryKey: ['report', meetingId],
    queryFn: () => aiApi.meeting.getReport(meetingId),
  })

  const { data: analyses } = useQuery({
    queryKey: ['analyses', meetingId],
    queryFn: () => aiApi.meeting.getAnalyses(meetingId),
    enabled: detailModalVisible,
  })

  const { data: rankings } = useQuery({
    queryKey: ['rankings', meetingId],
    queryFn: () => aiApi.meeting.getRankings(meetingId),
    enabled: detailModalVisible,
  })

  if (isLoading) {
    return (
      <div className="card rp-card--loading">
        <Spin size="small" />
      </div>
    )
  }

  if (!report) return null

  const presentation = buildReportPresentation(report)
  const reportMeta = getReportDraftMeta(report)
  const displayDate = meeting
    ? dayjs(meeting.completed_at || meeting.created_at).format('YYYY-MM-DD HH:mm')
    : '—'

  const consensusCount    = presentation.consensusPoints.length
  const disagreementCount = presentation.disagreementPoints.length
  const insightCount      = presentation.keyInsights.length + presentation.chainCorrelations.length
  const caseCount         = meeting?.case_ids?.length || 0

  const summaryText = presentation.summary

  const { data: citationAssist } = useQuery({
    queryKey: ['report-citation-assist', meetingId, summaryText],
    queryFn: () => knowledgeApi.citationAssist({ query: summaryText || meetingId }),
    enabled: detailModalVisible && !!summaryText,
  })

  return (
    <>
      <div className="card rp-card">
        {/* 卡片头 */}
        <div className="card-head">
          <span className="ico" style={{ fontFamily: 'var(--mono)', fontSize: 11 }}>
            {meetingId.slice(0, 14)}…
          </span>
          <span className="tag t-d" style={{ marginLeft: 6 }}>已完成</span>
          <span className="tag" style={{ marginLeft: 6 }}>{reportMeta.draftStatus}</span>
          <span className="tag t-p" style={{ marginLeft: 6 }}>{reportMeta.reviewStatus}</span>
          <span className="tag t-o" style={{ marginLeft: 6 }}>{reportMeta.modelStatus}</span>
          <span className="spacer" />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
            {displayDate}
          </span>
        </div>

        {/* 卡片体 */}
        <div className="card-body pad">
          <p className="rp-summary">{summaryText}</p>
          <div className="rp-tag-row">
            {caseCount > 0 && (
              <span className="tag t-o">
                <FileTextOutlined style={{ marginRight: 3 }} />{caseCount} 件案件
              </span>
            )}
            {consensusCount > 0 && (
              <span className="tag t-d">
                <CheckCircleOutlined style={{ marginRight: 3 }} />{consensusCount} 共识
              </span>
            )}
            {disagreementCount > 0 && (
              <span className="tag t-p">
                <ExclamationCircleOutlined style={{ marginRight: 3 }} />{disagreementCount} 分歧
              </span>
            )}
            {insightCount > 0 && (
              <span className="tag t-r">
                <BulbOutlined style={{ marginRight: 3 }} />{insightCount} 洞察
              </span>
            )}
          </div>
        </div>

        {/* 卡片底部操作 */}
        <div className="rp-card-footer">
          <button className="btn-ghost-sm" onClick={() => setDetailModalVisible(true)}>
            <EyeOutlined style={{ marginRight: 4 }} />报告详情
          </button>
          <button className="btn-ghost-sm" onClick={() => onExport(meetingId, report)}>
            <DownloadOutlined style={{ marginRight: 4 }} />导出
          </button>
          <button className="btn-ghost-sm" onClick={onViewDetail}>
            <ArrowRightOutlined style={{ marginRight: 4 }} />会议
          </button>
        </div>
      </div>

      {/* ── 详情 Modal ── */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FileTextOutlined style={{ color: 'var(--accent)' }} />
            <div>
              <div style={{ fontFamily: 'var(--serif)', fontSize: 15, color: 'var(--accent)', fontWeight: 500 }}>
                报告详情
              </div>
              <div style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)', letterSpacing: '0.06em', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {meetingId}
              </div>
            </div>
          </div>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>关闭</Button>,
          <Button key="export" type="primary" icon={<DownloadOutlined />}
            onClick={() => { onExport(meetingId, report); setDetailModalVisible(false) }}>
            导出报告
          </Button>,
          <Button key="view" icon={<EyeOutlined />} onClick={onViewDetail}>查看完整会议</Button>,
        ]}
        width={900}
        styles={{
          content: { background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 0 },
          header:  { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)' },
          footer:  { borderTop: '1px solid var(--line)', background: 'var(--bg-1)' },
        }}
      >
        {/* 执行摘要 */}
        <div className="rp-modal-section">
          <div className="rp-modal-section__title">执行摘要</div>
          <p className="rp-modal-section__text">
            {presentation.summary}
          </p>
        </div>

        {/* 综合结论 */}
        {presentation.conclusions !== '暂无' && (
          <div className="rp-modal-section">
            <div className="rp-modal-section__title">综合结论</div>
            <p className="rp-modal-section__text">{presentation.conclusions}</p>
          </div>
        )}

        {citationAssist?.citations?.length ? (
          <div className="rp-modal-section">
            <div className="rp-modal-section__title">引用助手</div>
            {citationAssist.citations.slice(0, 4).map((item, index) => (
              <div key={`${item.source_type}-${item.source_id}-${index}`} className="rp-modal-list-item">
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent)', flexShrink: 0 }}>
                  Q{index + 1}
                </span>
                <span>{item.snippet}</span>
              </div>
            ))}
          </div>
        ) : null}

        {/* 共识 / 分歧 / 洞察 / 建议 */}
        <Collapse
          defaultActiveKey={['consensus', 'recommendations']}
          style={{ background: 'transparent', border: 'none', marginBottom: 12 }}
          items={[
            {
              key: 'consensus',
              label: (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ok)', textTransform: 'uppercase' }}>
                  共识点 ({consensusCount})
                </span>
              ),
              style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
              children: presentation.consensusPoints.length > 0 ? (
                <div>
                  {presentation.consensusPoints.map((point, idx) => (
                    <div key={idx} className="rp-modal-list-item">
                      <CheckCircleOutlined style={{ color: 'var(--ok)', flexShrink: 0, marginTop: 1 }} />
                      <span>{point}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>无共识点</span>
              ),
            },
            {
              key: 'disagreement',
              label: (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--warn)', textTransform: 'uppercase' }}>
                  分歧点 ({disagreementCount})
                </span>
              ),
              style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
              children: presentation.disagreementPoints.length > 0 ? (
                <div>
                  {presentation.disagreementPoints.map((point, idx) => (
                    <div key={idx} className="rp-modal-list-item">
                      <ExclamationCircleOutlined style={{ color: 'var(--warn)', flexShrink: 0, marginTop: 1 }} />
                      <span>{point}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>无分歧点</span>
              ),
            },
            ...(presentation.keyInsights.length > 0
              ? [{
                  key: 'insights',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--info)', textTransform: 'uppercase' as const }}>
                      关键洞察 ({presentation.keyInsights.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <div>
                      {presentation.keyInsights.map((insight, idx) => (
                        <div key={idx} className="rp-modal-list-item">
                          <BulbOutlined style={{ color: 'var(--info)', flexShrink: 0, marginTop: 1 }} />
                          <span>{insight}</span>
                        </div>
                      ))}
                    </div>
                  ),
                }]
              : []),
            ...(presentation.areaRisks.length > 0
              ? [{
                  key: 'areaRisks',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--warn)', textTransform: 'uppercase' as const }}>
                      风险区域 ({presentation.areaRisks.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <div>
                      {presentation.areaRisks.map((item, idx) => (
                        <div key={idx} className="rp-modal-list-item">
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--warn)', flexShrink: 0 }}>
                            R{idx + 1}
                          </span>
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  ),
                }]
              : []),
            ...(presentation.chainCorrelations.length > 0
              ? [{
                  key: 'correlations',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--accent)', textTransform: 'uppercase' as const }}>
                      链条关系 ({presentation.chainCorrelations.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <div>
                      {presentation.chainCorrelations.map((item, idx) => (
                        <div key={idx} className="rp-modal-list-item">
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--accent)', flexShrink: 0 }}>
                            C{idx + 1}
                          </span>
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  ),
                }]
              : []),
            {
              key: 'recommendations',
              label: (
                <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                  建议 ({presentation.actionSuggestions.length})
                </span>
              ),
              style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
              children: presentation.actionSuggestions.length > 0 ? (
                <div>
                  {presentation.actionSuggestions.map((rec, idx) => (
                    <div key={idx} className="rp-modal-list-item">
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', flexShrink: 0 }}>
                        {String(idx + 1).padStart(2, '0')}
                      </span>
                      <span>{rec}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <span style={{ color: 'var(--ink-3)', fontSize: 12 }}>无建议</span>
              ),
            },
            ...(presentation.experienceCards.length > 0
              ? [{
                  key: 'experience',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ok)', textTransform: 'uppercase' as const }}>
                      经验沉淀 ({presentation.experienceCards.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <div>
                      {presentation.experienceCards.map((item, idx) => (
                        <div key={idx} className="rp-modal-list-item">
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ok)', flexShrink: 0 }}>
                            E{idx + 1}
                          </span>
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  ),
                }]
              : []),
            ...(analyses && analyses.length > 0
              ? [{
                  key: 'analyses',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' as const }}>
                      第一阶段分析 ({analyses.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <Collapse
                      size="small"
                      style={{ background: 'transparent', border: 'none' }}
                      items={analyses.map((analysis: any, index: number) => ({
                        key: index,
                        label: (
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)' }}>
                            分析结果 {String(index + 1).padStart(2, '0')}
                          </span>
                        ),
                        style: { background: 'var(--bg-1)', border: '1px solid var(--line-soft)', borderRadius: 0, marginBottom: 4 },
                        children: (
                          <pre className="rp-pre">
                            {typeof analysis.result_content === 'string'
                              ? analysis.result_content
                              : JSON.stringify(analysis.result_content, null, 2)}
                          </pre>
                        ),
                      }))}
                    />
                  ),
                }]
              : []),
            ...(rankings && rankings.length > 0
              ? [{
                  key: 'rankings',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' as const }}>
                      第二阶段排名 ({rankings.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <Collapse
                      size="small"
                      style={{ background: 'transparent', border: 'none' }}
                      items={rankings.map((ranking: any, index: number) => ({
                        key: index,
                        label: (
                          <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--ink-3)' }}>
                            评价者 {String(index + 1).padStart(2, '0')}
                          </span>
                        ),
                        style: { background: 'var(--bg-1)', border: '1px solid var(--line-soft)', borderRadius: 0, marginBottom: 4 },
                        children: (
                          <pre className="rp-pre">{JSON.stringify(ranking, null, 2)}</pre>
                        ),
                      }))}
                    />
                  ),
                }]
              : []),
            ...(presentation.modelContributions.length > 0
              ? [{
                  key: 'contributions',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' as const }}>
                      各模型贡献 ({presentation.modelContributions.length})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <List
                      size="small"
                      dataSource={presentation.modelContributions}
                      renderItem={(item) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                          <Space direction="vertical" style={{ width: '100%' }}>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, color: 'var(--accent)', letterSpacing: '0.06em' }}>
                              {item.model}
                            </span>
                            <span style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>{item.contribution}</span>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                }]
              : []),
          ]}
        />
      </Modal>
    </>
  )
}

export default Reports
