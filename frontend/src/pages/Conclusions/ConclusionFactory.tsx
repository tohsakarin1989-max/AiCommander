import { useEffect, useState } from 'react'
import {
  InputNumber,
  Space,
  message,
  Select,
  Drawer,
  List,
  Collapse,
  Spin,
  Input,
  Tooltip,
} from 'antd'
import {
  LinkOutlined,
  FileTextOutlined,
  FilterOutlined,
  SyncOutlined,
  CheckOutlined,
  CloseOutlined,
  FlagOutlined,
  CopyOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { aiApi } from '../../services/ai'
import type { Conclusion, ConclusionFilters } from '../../types'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getConclusionDraftMeta, getConclusionMarkdown } from './conclusionPresentation'
import './ConclusionFactory.css'

/* ── 状态标签辅助 ─────────────────────────────────────────── */
const STATUS_TAG_CLASS: Record<string, string> = {
  published:    'tag t-d',
  needs_review: 'tag t-p',
  flagged:      'tag t-p',
  rejected:     'tag t-x',
  draft:        'tag',
}

const STATUS_LABEL: Record<string, string> = {
  published:    'PUBLISHED',
  needs_review: 'REVIEW',
  flagged:      'FLAGGED',
  rejected:     'REJECTED',
  draft:        'DRAFT',
}

/* ── 置信度颜色 ───────────────────────────────────────────── */
function confidenceColor(val: number | null | undefined): string {
  if (val == null) return 'var(--ink-3)'
  if (val >= 0.8)  return 'var(--ok)'
  if (val >= 0.6)  return 'var(--warn)'
  return 'var(--err)'
}

/* ── 风险标签辅助 ─────────────────────────────────────────── */
const RISK_TAG_CLASS: Record<string, string> = {
  high:    'tag t-x',
  medium:  'tag t-p',
  low:     'tag t-d',
  unknown: 'tag',
}

const RISK_LABEL: Record<string, string> = {
  high: 'HIGH', medium: 'MED', low: 'LOW', unknown: '—',
}

const ConclusionFactory: React.FC = () => {
  const [caseId, setCaseId]       = useState<number | null>(null)
  const [meetingId, setMeetingId] = useState<string>('')
  const [filters, setFilters]     = useState<ConclusionFilters>({})
  const [detailId, setDetailId]   = useState<number | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  useEffect(() => {
    const conclusionId = Number(searchParams.get('conclusionId'))
    if (!Number.isFinite(conclusionId) || conclusionId <= 0) return
    setDetailId(conclusionId)
    setDetailOpen(true)
  }, [searchParams])

  const { data, refetch, isFetching } = useQuery({
    queryKey: ['conclusions', filters],
    queryFn: () => aiApi.conclusion.list(filters),
  })

  const generateMutation = useMutation({
    mutationFn: (id: number) => aiApi.conclusion.generate(id),
    onSuccess: () => { message.success('结论生成完成'); refetch() },
    onError: (error: any) => { message.error(error?.response?.data?.detail || '结论生成失败') },
  })

  const generateFromMeetingMutation = useMutation({
    mutationFn: (id: string) => aiApi.conclusion.generateFromMeeting(id),
    onSuccess: () => { message.success('从会议生成结论完成'); setMeetingId(''); refetch() },
    onError: (error: any) => { message.error(error?.response?.data?.detail || '从会议生成结论失败') },
  })

  const reviewMutation = useMutation({
    mutationFn: (payload: { id: number; action: 'approve' | 'reject' | 'flag' }) =>
      aiApi.conclusion.review(payload.id, { action: payload.action }),
    onSuccess: () => { message.success('已更新结论状态'); refetch() },
    onError: (error: any) => { message.error(error?.response?.data?.detail || '操作失败') },
  })

  const { data: detail, isFetching: isDetailLoading } = useQuery({
    queryKey: ['conclusion-detail', detailId],
    queryFn: () => aiApi.conclusion.get(detailId as number),
    enabled: detailOpen && !!detailId,
  })

  const rows = data || []
  const pendingCount = rows.filter((c: any) => c.status === 'needs_review').length
  const detailMeta = getConclusionDraftMeta(detail)
  const detailMarkdown = getConclusionMarkdown(detail)

  const handleCopyConclusionMarkdown = async () => {
    if (!detailMarkdown) {
      message.warning('暂无可复制草稿')
      return
    }

    try {
      await navigator.clipboard.writeText(detailMarkdown)
      message.success('已复制标准化结论草稿')
    } catch {
      message.error('复制失败，请手动选择文本复制')
    }
  }

  return (
    <div className="page-scrollable">

      {/* ── 页面标题 ── */}
      <div className="page-title">
        <h1>结论工厂</h1>
        <span className="sub">低人力模式 · AI 自动生成与审核</span>
      </div>

      {/* ── 统计行 ── */}
      <div className="cf-stats-row">
        <div className="kpill">
          <div className="lbl">待审核结论</div>
          <div className="val" style={{ color: pendingCount > 0 ? 'var(--warn)' : 'var(--accent)' }}>
            {pendingCount}
          </div>
          <div className="sub">需要人工确认</div>
        </div>
        <div className="kpill">
          <div className="lbl">结论总数</div>
          <div className="val">{rows.length}</div>
          <div className="sub">全部记录</div>
        </div>
      </div>

      {/* ── 生成面板 ── */}
      <div className="card cf-generate-card">
        <div className="card-head">
          <span className="ico">⚡</span>
          <span className="ti">生成结论</span>
        </div>
        <div className="card-body pad">
          <div className="cf-generate-row">
            <InputNumber
              placeholder="案件 ID"
              value={caseId ?? undefined}
              onChange={(value) => setCaseId(value as number)}
              style={{ width: 130 }}
            />
            <button
              className="btn-primary"
              disabled={generateMutation.isPending}
              onClick={() => {
                if (!caseId) { message.warning('请先输入案件 ID'); return }
                generateMutation.mutate(caseId)
              }}
            >
              {generateMutation.isPending ? '生成中…' : '从案件生成'}
            </button>

            <span className="cf-divider">OR</span>

            <Input
              placeholder="输入会议 ID"
              value={meetingId}
              onChange={(e) => setMeetingId(e.target.value)}
              style={{ width: 300 }}
            />
            <button
              className="btn-primary"
              disabled={generateFromMeetingMutation.isPending}
              onClick={() => {
                if (!meetingId.trim()) { message.warning('请先输入会议 ID'); return }
                generateFromMeetingMutation.mutate(meetingId.trim())
              }}
            >
              <LinkOutlined style={{ marginRight: 5 }} />
              {generateFromMeetingMutation.isPending ? '生成中…' : '从会议生成'}
            </button>
          </div>
        </div>
      </div>

      {/* ── 过滤面板 ── */}
      <div className="card cf-filter-card">
        <div className="card-head">
          <FilterOutlined className="ico" style={{ fontSize: 12 }} />
          <span className="ti">筛选</span>
        </div>
        <div className="card-body pad">
          <div className="cf-filter-row">
            <Select
              placeholder="状态"
              allowClear
              style={{ width: 148 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, status: value }))}
              options={[
                { value: 'draft',        label: 'Draft' },
                { value: 'needs_review', label: 'Needs Review' },
                { value: 'published',    label: 'Published' },
                { value: 'flagged',      label: 'Flagged' },
                { value: 'rejected',     label: 'Rejected' },
              ]}
            />
            <Select
              placeholder="风险等级"
              allowClear
              style={{ width: 130 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, risk_level: value }))}
              options={[
                { value: 'low',     label: 'Low' },
                { value: 'medium',  label: 'Medium' },
                { value: 'high',    label: 'High' },
                { value: 'unknown', label: 'Unknown' },
              ]}
            />
            <InputNumber
              placeholder="置信度 ≥"
              min={0} max={1} step={0.05}
              style={{ width: 110 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, min_confidence: value as number }))}
            />
            <InputNumber
              placeholder="置信度 ≤"
              min={0} max={1} step={0.05}
              style={{ width: 110 }}
              onChange={(value) => setFilters((prev) => ({ ...prev, max_confidence: value as number }))}
            />
            <button className="btn-ghost" onClick={() => refetch()} disabled={isFetching}>
              <SyncOutlined style={{ marginRight: 5 }} />应用
            </button>
            <button
              className="btn-ghost"
              style={{ borderColor: 'oklch(0.80 0.16 75 / 0.4)', color: 'var(--warn)' }}
              onClick={() => setFilters({ status: 'needs_review' })}
            >
              异常队列
            </button>
            <button className="btn-ghost" onClick={() => setFilters({})}>重置</button>
          </div>
        </div>
      </div>

      {/* ── 结论表格 ── */}
      <div className="card">
        <div className="card-head">
          <FileTextOutlined className="ico" />
          <span className="ti">结论列表</span>
          <span className="spacer" />
          <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
            {rows.length} 条记录
          </span>
        </div>
        <div className="card-body scroll">
          {isFetching ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <Spin />
            </div>
          ) : rows.length === 0 ? (
            <div className="empty-state">
              <span className="icon"><FileTextOutlined /></span>
              暂无结论记录
            </div>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>案件编号</th>
                  <th>结论 ID</th>
                  <th>关联会议</th>
                  <th>结论摘要</th>
                  <th>置信度</th>
                  <th>风险</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((record: Conclusion) => (
                  <tr key={record.id}>
                    {/* 案件编号 */}
                    <td>
                      <span className="cno" onClick={() => navigate(`/cases?caseId=${record.case_id}`)}>
                        #{record.case_id}
                      </span>
                    </td>

                    {/* 结论 ID */}
                    <td>
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                        {record.id}
                      </span>
                    </td>

                    {/* 关联会议 */}
                    <td>
                      {record.meeting_id ? (
                        <Tooltip title={record.meeting_info?.status ? `状态: ${record.meeting_info.status}` : ''}>
                          <button
                            className="btn-ghost-sm"
                            style={{ color: 'var(--accent)', borderColor: 'var(--accent-line)' }}
                            onClick={() => navigate(`/meetings?meetingId=${record.meeting_id}`)}
                          >
                            <LinkOutlined style={{ marginRight: 3 }} />
                            {record.meeting_id.slice(0, 10)}…
                          </button>
                        </Tooltip>
                      ) : (
                        <span style={{ fontFamily: 'var(--mono)', color: 'var(--ink-3)', fontSize: 11 }}>—</span>
                      )}
                    </td>

                    {/* 结论摘要 */}
                    <td style={{ maxWidth: 280 }}>
                      <span style={{ fontSize: 12, color: 'var(--ink-2)', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {record.summary || '—'}
                      </span>
                    </td>

                    {/* 置信度 */}
                    <td>
                      <div className="cf-confidence">
                        <span
                          className="cf-confidence__num"
                          style={{ color: confidenceColor(record.confidence) }}
                        >
                          {record.confidence != null ? (record.confidence * 100).toFixed(0) : '—'}%
                        </span>
                        <div className="cf-confidence__bar">
                          <div
                            className="cf-confidence__fill"
                            style={{
                              width: `${(record.confidence || 0) * 100}%`,
                              background: confidenceColor(record.confidence),
                            }}
                          />
                        </div>
                      </div>
                    </td>

                    {/* 风险 */}
                    <td>
                      <span className={RISK_TAG_CLASS[record.risk_level] || 'tag'}>
                        {RISK_LABEL[record.risk_level] || '—'}
                      </span>
                    </td>

                    {/* 状态 */}
                    <td>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <span className={STATUS_TAG_CLASS[record.status] || 'tag'}>
                          {STATUS_LABEL[record.status] || record.status}
                        </span>
                        <span className="tag">{getConclusionDraftMeta(record).reviewStatus}</span>
                        <span className="tag">{getConclusionDraftMeta(record).modelStatus}</span>
                      </div>
                    </td>

                    {/* 操作 */}
                    <td>
                      <div className="cf-action-group">
                        <button
                          className="cf-action-btn cf-action-btn--view"
                          onClick={() => { setDetailId(record.id); setDetailOpen(true) }}
                        >
                          <FileTextOutlined style={{ marginRight: 3 }} />证据
                        </button>
                        <button
                          className="cf-action-btn cf-action-btn--approve"
                          onClick={() => reviewMutation.mutate({ id: record.id, action: 'approve' })}
                        >
                          <CheckOutlined style={{ marginRight: 3 }} />通过
                        </button>
                        <button
                          className="cf-action-btn cf-action-btn--reject"
                          onClick={() => reviewMutation.mutate({ id: record.id, action: 'reject' })}
                        >
                          <CloseOutlined style={{ marginRight: 3 }} />退回
                        </button>
                        <button
                          className="cf-action-btn cf-action-btn--flag"
                          onClick={() => reviewMutation.mutate({ id: record.id, action: 'flag' })}
                        >
                          <FlagOutlined style={{ marginRight: 3 }} />标记
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── 证据链抽屉 ── */}
      <Drawer
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FileTextOutlined style={{ color: 'var(--accent)' }} />
            <span style={{ fontFamily: 'var(--serif)', fontSize: 14, color: 'var(--accent)', fontWeight: 500 }}>
              证据链详情
            </span>
            <span style={{ flex: 1 }} />
            {detail && (
              <button className="btn-ghost-sm" onClick={handleCopyConclusionMarkdown}>
                <CopyOutlined style={{ marginRight: 4 }} />
                复制草稿
              </button>
            )}
          </div>
        }
        open={detailOpen}
        width={640}
        onClose={() => setDetailOpen(false)}
        styles={{
          body:   { background: 'var(--bg-1)', padding: '16px 20px' },
          header: { background: 'var(--bg-1)', borderBottom: '1px solid var(--line)' },
          footer: { background: 'var(--bg-1)' },
        }}
      >
        {isDetailLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
            <Spin />
          </div>
        ) : detail ? (
          <Space direction="vertical" size={0} style={{ width: '100%' }}>

            {/* 基础信息 */}
            <div className="cf-drawer-section">
              <div className="cf-drawer-section__title">基础信息</div>
              {[
                { label: '结论 ID',  value: String(detail.id),        mono: true },
                { label: '案件 ID',  value: String(detail.case_id),   mono: true },
                { label: '状态',     value: detail.status },
                { label: '草稿状态', value: detailMeta.draftStatus },
                { label: '复核状态', value: detailMeta.reviewStatus },
                { label: '模型状态', value: detailMeta.modelStatus },
                { label: '置信度',   value: detail.confidence != null ? `${(detail.confidence * 100).toFixed(1)}%` : '—', mono: true },
                { label: '风险等级', value: detail.risk_level || '—' },
                { label: '摘要',     value: detail.summary || '—' },
              ].map(({ label, value, mono }) => (
                <div className="cf-drawer-row" key={label}>
                  <span className="cf-drawer-row__label">{label}</span>
                  <span className={`cf-drawer-row__value${mono ? ' cf-drawer-row__value--mono' : ''}`}>{value}</span>
                </div>
              ))}

              {detail.meeting_id && (
                <div className="cf-drawer-row">
                  <span className="cf-drawer-row__label">关联会议</span>
                  <div className="cf-drawer-row__value">
                    <button
                      className="btn-ghost-sm"
                      style={{ color: 'var(--accent)', borderColor: 'var(--accent-line)' }}
                      onClick={() => navigate(`/meetings?meetingId=${detail.meeting_id}`)}
                    >
                      <LinkOutlined style={{ marginRight: 4 }} />
                      {detail.meeting_id}
                    </button>
                    {detail.meeting_info && (
                      <span className={STATUS_TAG_CLASS[detail.meeting_info.status] || 'tag'} style={{ marginLeft: 8 }}>
                        {STATUS_LABEL[detail.meeting_info.status] || detail.meeting_info.status}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* 标准化草稿 */}
            <div className="cf-drawer-section">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <div className="cf-drawer-section__title" style={{ marginBottom: 0, flex: 1 }}>
                  标准化研判草稿
                </div>
                <button className="btn-ghost-sm" onClick={handleCopyConclusionMarkdown}>
                  <CopyOutlined style={{ marginRight: 4 }} />
                  复制 Markdown
                </button>
              </div>
              <pre className="cf-pre">{detailMarkdown || '暂无标准化草稿'}</pre>
            </div>

            {/* 处置建议 */}
            {(detail.evidence?.recommendations?.length ?? 0) > 0 && (
              <div className="cf-drawer-section">
                <div className="cf-drawer-section__title">处置建议</div>
                {(detail.evidence!.recommendations as string[]).map((item: string, idx: number) => (
                  <div key={idx} className="cf-evidence-item">
                    <div className="cf-evidence-item__dot" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 折叠证据 */}
            <Collapse
              style={{ background: 'transparent', border: 'none' }}
              items={[
                {
                  key: 'key',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      关键证据 ({detail.evidence?.key_evidence?.length || 0})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <List
                      size="small"
                      dataSource={detail.evidence?.key_evidence || []}
                      renderItem={(item: string) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)', padding: '5px 0' }}>
                          <div className="cf-evidence-item">
                            <div className="cf-evidence-item__dot" />
                            <span style={{ fontSize: 12.5, color: 'var(--ink-1)' }}>{item}</span>
                          </div>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'case',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      案件详情
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <Space>
                      <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)' }}>
                        {detail.evidence?.raw?.case?.case_number || '—'}
                      </span>
                      <button
                        className="btn-ghost-sm"
                        onClick={() => navigate(`/cases?caseId=${detail.case_id}`)}
                      >
                        查看案件
                      </button>
                    </Space>
                  ),
                },
                {
                  key: 'similar',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      相似案件 ({detail.evidence?.raw?.similar_cases?.length || 0})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <List
                      size="small"
                      dataSource={detail.evidence?.raw?.similar_cases || []}
                      renderItem={(item: any) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                          <Space>
                            <span className="tag" style={{ fontFamily: 'var(--mono)', fontSize: 10 }}>
                              #{item.case_id}
                            </span>
                            <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
                              相似度 {item.similarity}
                            </span>
                            <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
                              {item.metadata?.case_type || ''}
                            </span>
                            <button
                              className="btn-ghost-sm"
                              onClick={() => navigate(`/cases?caseId=${item.case_id}`)}
                            >
                              查看
                            </button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'meetings',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      关联会议 ({detail.evidence?.raw?.related_meetings?.length || 0})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <List
                      size="small"
                      dataSource={detail.evidence?.raw?.related_meetings || []}
                      renderItem={(item: any) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                          <Space>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--accent)' }}>
                              {item.meeting_id}
                            </span>
                            <span className={STATUS_TAG_CLASS[item.status] || 'tag'}>
                              {STATUS_LABEL[item.status] || item.status}
                            </span>
                            <button
                              className="btn-ghost-sm"
                              onClick={() => navigate(`/meetings?meetingId=${item.meeting_id}`)}
                            >
                              查看
                            </button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'reports',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      关联报告 ({detail.evidence?.raw?.related_reports?.length || 0})
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <List
                      size="small"
                      dataSource={detail.evidence?.raw?.related_reports || []}
                      renderItem={(item: any) => (
                        <List.Item style={{ borderColor: 'var(--line-soft)' }}>
                          <Space>
                            <span style={{ fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                              #{item.report_id}
                            </span>
                            <span style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>{item.report_type}</span>
                            <button
                              className="btn-ghost-sm"
                              onClick={() => navigate(`/meetings?meetingId=${item.meeting_id}`)}
                            >
                              查看
                            </button>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ),
                },
                {
                  key: 'raw',
                  label: (
                    <span style={{ fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '0.18em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                      原始证据
                    </span>
                  ),
                  style: { background: 'var(--bg-2)', border: '1px solid var(--line)', borderRadius: 0, marginBottom: 6 },
                  children: (
                    <pre className="cf-pre">
                      {JSON.stringify(detail.evidence?.raw || {}, null, 2)}
                    </pre>
                  ),
                },
              ]}
            />
          </Space>
        ) : (
          <div className="empty-state">
            <span className="icon"><FileTextOutlined /></span>
            暂无证据数据
          </div>
        )}
      </Drawer>
    </div>
  )
}

export default ConclusionFactory
