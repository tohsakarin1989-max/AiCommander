import { useState } from 'react'
import { Table, Descriptions, Modal, message } from 'antd'
import {
  FilterOutlined,
  SyncOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  ApartmentOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { caseApi } from '../../services/cases'
import type { Case } from '../../types'
import './CaseFeatures.css'

const CaseFeatures: React.FC = () => {
  const queryClient = useQueryClient()
  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: preprocessStatus } = useQuery({
    queryKey: ['preprocess-status'],
    queryFn: () => caseApi.getPreprocessStatus(),
    refetchInterval: 5000,
  })

  const [selected, setSelected] = useState<Case | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [batchSummary, setBatchSummary] = useState<{
    processed: number
    success: number
    failed: number
    skipped: number
    modeText: string
  } | null>(null)

  const batchMutation = useMutation({
    mutationFn: (payload?: { case_ids?: number[]; only_missing?: boolean; use_llm?: boolean }) =>
      caseApi.preprocessCasesBatch(payload),
    onSuccess: (result) => {
      const modeText = Object.entries(result.mode_counts || {})
        .map(([mode, count]) => `${mode} ${count}`)
        .join('，') || '暂无'
      setBatchSummary({
        processed: result.processed,
        success: result.success,
        failed: result.failed,
        skipped: result.skipped,
        modeText,
      })
      message.success(`清洗完成：成功 ${result.success} 条，失败 ${result.failed} 条`)
      setSelectedRowKeys([])
      queryClient.invalidateQueries({ queryKey: ['cases'] })
      queryClient.invalidateQueries({ queryKey: ['preprocess-status'] })
    },
    onError: (e: any) => {
      message.error(`批量清洗失败：${e.message || e}`)
    },
  })

  const renderQuality = (record: Case) => {
    if (record.quality_score == null) return <span style={{ color: 'var(--ink-3)' }}>—</span>
    const ok = record.quality_score >= 80
    const warn = record.quality_score < 60
    return (
      <span className={`cf-badge ${ok ? 'cf-badge--done' : warn ? 'cf-badge--pending' : ''}`}>
        {warn ? <WarningOutlined style={{ marginRight: 3 }} /> : <CheckCircleOutlined style={{ marginRight: 3 }} />}
        {Math.round(record.quality_score)}
      </span>
    )
  }

  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
      render: (num: string) => <span className="cno">{num}</span>,
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      render: (t: string) => <span className="time">{t ? t.slice(0, 10) : '—'}</span>,
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
      render: (loc: string) => <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{loc || '—'}</span>,
    },
    {
      title: '质量',
      dataIndex: 'quality_score',
      key: 'quality_score',
      width: 86,
      render: (_: unknown, record: Case) => renderQuality(record),
    },
    {
      title: '状态',
      dataIndex: 'features',
      key: 'features',
      render: (features: Record<string, unknown> | null) =>
        features && Object.keys(features).length > 0 ? (
          <span className="cf-badge cf-badge--done">
            <CheckCircleOutlined style={{ marginRight: 3 }} />已预处理
          </span>
        ) : (
          <span className="cf-badge cf-badge--pending">未处理</span>
        ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
    onSelect: (record: Case) => setSelected(record),
  }

  const handleBatchPreprocess = async () => {
    if (!selectedRowKeys.length) {
      message.warning('请先选择需要预处理的案件')
      return
    }
    batchMutation.mutate({
      case_ids: selectedRowKeys.map((id) => Number(id)),
      only_missing: false,
      use_llm: true,
    })
  }

  const handlePreprocessAll = () => {
    Modal.confirm({
      title: '全量清洗后台案件数据',
      content: '将按现有案件预处理方式重跑全部案件，默认使用不消耗 token 的确定性清洗，适合测试阶段快速看整体效果。',
      okText: '开始清洗',
      cancelText: '取消',
      onOk: () => batchMutation.mutateAsync({ only_missing: false, use_llm: false }),
    })
  }

  const renderDetail = () => {
    if (!selected) {
      return (
        <div className="empty-state" style={{ minHeight: 200 }}>
          <div className="icon"><ApartmentOutlined /></div>
          <span>请选择左侧案件以查看预处理结果</span>
        </div>
      )
    }
    const features = (selected.features || {}) as Record<string, any>
    const basic = features.basic || {}
    const geo = features.geo || {}
    const actors = features.actors || {}
    const oil = features.oil || {}
    const flow = features.flow || {}
    const risk = features.risk || {}
    const management = features.management || {}
    const readiness = features.analysis_readiness || {}
    const confidence = typeof features.confidence === 'number' ? features.confidence : null
    const lowConfidence = confidence !== null && confidence < 0.7

    const actorFacts = actors.facts || {}
    const actorClues = actors.clues || {}
    const actorHypotheses = actors.hypotheses || {}
    const oilFacts = oil.facts || {}
    const oilClues = oil.clues || {}
    const oilHypotheses = oil.hypotheses || {}

    return (
      <>
        {/* 标准化摘要 */}
        <div className="card cf-detail-card">
          <div className="card-head">
            <span className="ti">NORMALIZED SUMMARY · 标准化摘要</span>
            {confidence !== null && (
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', fontSize: 10, color: confidence >= 0.7 ? 'var(--ok)' : 'var(--warn)' }}>
                置信度 {(confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="card-body pad">
            {lowConfidence && (
              <div className="cf-low-confidence">
                <WarningOutlined />
                <span>置信度较低（{(confidence! * 100).toFixed(0)}%），建议人工仔细复核以下内容。</span>
              </div>
            )}
            <div className="cf-summary-title">{basic.title || '（未生成案名）'}</div>
            <div className="cf-summary-body">{basic.summary || '暂无摘要，请确认预处理任务是否完成。'}</div>
          </div>
        </div>

        {/* 结构化特征 */}
        <div className="card cf-detail-card">
          <div className="card-head">
            <span className="ti">STRUCTURED FEATURES · 结构化特征</span>
          </div>
          <div className="card-body pad">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="信息质量">
                评分：{selected.quality_score ?? management.report_quality_score ?? '未计算'} ·
                等级：{selected.quality_level || management.report_quality_level || '未知'}<br />
                缺项：{selected.quality_issues?.missing_required?.map(i => i.label).slice(0, 5).join('，') || (management.missing_fields || []).join('，') || '无明显缺项'}
              </Descriptions.Item>
              <Descriptions.Item label="研判可用性">
                时空：{readiness.spacetime || '未评估'} · 同伙：{readiness.gang || '未评估'} ·
                巡逻：{readiness.patrol || '未评估'} · 圆桌：{readiness.roundtable || '未评估'}
              </Descriptions.Item>
              <Descriptions.Item label="案件类型">{basic.case_type || selected.case_type || '未知'}</Descriptions.Item>
              <Descriptions.Item label="时间（标准化）">{basic.time || selected.occurred_time}</Descriptions.Item>
              <Descriptions.Item label="地点（标准化）">{basic.location || selected.location}</Descriptions.Item>
              <Descriptions.Item label="地理信息">
                纬度：{geo.latitude ?? selected.latitude ?? '未知'} ，经度：{geo.longitude ?? selected.longitude ?? '未知'} ，区域：{geo.region || '未知'} ，地点类型：{geo.place_type || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="涉案人员/车辆（事实）">
                角色：{(actorFacts.known_roles || []).join('，') || '未知'}<br />
                车辆：{(actorFacts.known_vehicles || []).map((v: any) => `${v.plate || '未知车牌'}（${v.type || '类型未知'}）`).join('，') || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="涉案人员/车辆（线索）">
                可能角色：{(actorClues.possible_roles || []).join('，') || '暂无明显线索'}<br />
                备注：{actorClues.notes || '—'}
              </Descriptions.Item>
              <Descriptions.Item label="涉案人员/车辆（推测）">
                团伙结构推测：{actorHypotheses.suspected_structure || '暂无可靠推测'}
              </Descriptions.Item>
              <Descriptions.Item label="涉油特征（事实）">
                油品：{oilFacts.oil_type || selected.oil_type || '未知'} · 性质：{selected.oil_nature || '未知'} · 数量：{oilFacts.volume ?? selected.oil_volume ?? '未知'}<br />
                价值（元）：{oilFacts.value ?? selected.oil_value ?? '未知'} · 设施：{oilFacts.facility_type || selected.facility_type || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="涉油特征（线索）">
                {(oilClues.scene_observations || []).join('，') || '暂无明显线索'}
              </Descriptions.Item>
              <Descriptions.Item label="涉油特征（推测）">
                {oilHypotheses.possible_risk || '暂无可靠推测'}
              </Descriptions.Item>
              <Descriptions.Item label="油品流向">
                上游：{flow.upstream_source || selected.upstream_source || '未知'}<br />
                下游：{(flow.downstream_destination || []).join('，') || selected.downstream_destination || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="风险评估">
                等级：{risk.level || '未知'} · 因素：{(risk.factors || []).join('，') || '未知'}
              </Descriptions.Item>
              <Descriptions.Item label="标签">
                {(features.tags || []).length ? (features.tags || []).join('，') : '暂无标签'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
      </>
    )
  }

  return (
    <div className="page-scrollable">

      {/* 页面标题 */}
      <div className="page-title">
        <h1>案件预处理</h1>
        <span className="sub">FEATURE EXTRACTION</span>
        <span style={{ flex: 1 }} />
        <button
          className="btn"
          onClick={handlePreprocessAll}
          disabled={batchMutation.isPending}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <SyncOutlined spin={batchMutation.isPending} />
          全量清洗
        </button>
        <button
          className="btn-primary"
          onClick={handleBatchPreprocess}
          disabled={!selectedRowKeys.length || batchMutation.isPending}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <FilterOutlined />
          批量预处理 {selectedRowKeys.length > 0 ? `(${selectedRowKeys.length})` : ''}
        </button>
      </div>

      {/* 状态条 */}
      {preprocessStatus && (
        <div className="cf-status-bar">
          <SyncOutlined spin={preprocessStatus.processing > 0} style={{ color: 'var(--info)' }} />
          <span>排队</span>
          <span className="cf-status-bar__num">{preprocessStatus.pending}</span>
          <span style={{ color: 'var(--line)' }}>·</span>
          <span>处理中</span>
          <span className="cf-status-bar__num" style={{ color: preprocessStatus.processing > 0 ? 'var(--warn)' : 'var(--accent)' }}>
            {preprocessStatus.processing}
          </span>
          <span style={{ color: 'var(--line)' }}>·</span>
          <span>平均耗时</span>
          <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)', marginLeft: 2 }}>
            {preprocessStatus.avg_duration_seconds != null
              ? `${Math.round(preprocessStatus.avg_duration_seconds)} 秒`
              : '暂无数据'}
          </span>
          <span style={{ color: 'var(--line)' }}>·</span>
          <span>失败</span>
          <span className="cf-status-bar__num" style={{ color: preprocessStatus.failed > 0 ? 'var(--err)' : 'var(--ink-3)' }}>
            {preprocessStatus.failed}
          </span>
        </div>
      )}

      {batchSummary && (
        <div className="cf-batch-result">
          <CheckCircleOutlined />
          <span>本次清洗</span>
          <b>{batchSummary.processed}</b>
          <span>条，成功</span>
          <b>{batchSummary.success}</b>
          <span>条，失败</span>
          <b className={batchSummary.failed > 0 ? 'err' : ''}>{batchSummary.failed}</b>
          <span>条，跳过</span>
          <b>{batchSummary.skipped}</b>
          <span>条；模式：{batchSummary.modeText}</span>
        </div>
      )}

      {/* 主体双栏 */}
      <div className="cf-body">
        {/* 左侧案件列表 */}
        <div className="card cf-list-card">
          <div className="card-head">
            <span className="ti">案件列表</span>
            <span className="spacer" />
            <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)' }}>
              {selectedRowKeys.length > 0 ? `已选 ${selectedRowKeys.length} 条` : '点击行选中'}
            </span>
          </div>
          <div className="card-body">
            <Table
              rowSelection={rowSelection}
              columns={columns}
              dataSource={cases}
              loading={isLoading}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 10 }}
              rowClassName={(record) => record.id === selected?.id ? 'cf-row--selected' : ''}
              onRow={(record) => ({
                onClick: () => setSelected(record),
              })}
            />
          </div>
        </div>

        {/* 右侧详情 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>
          {renderDetail()}
        </div>
      </div>
    </div>
  )
}

export default CaseFeatures
