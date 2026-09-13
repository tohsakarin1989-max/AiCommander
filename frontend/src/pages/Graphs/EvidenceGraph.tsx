import { useEffect, useMemo, useRef, useState } from 'react'
import { App as AntdApp, Select, Switch } from 'antd'
import { DownloadOutlined, NodeIndexOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import ReactECharts from 'echarts-for-react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { parseCaseDeepLinkId } from '../Cases/caseSearch'

import { caseApi } from '../../services/cases'
import {
  evidenceGraphApi,
  type EvidenceGraphEdge,
  type EvidenceGraphNode,
} from '../../services/evidenceGraph'
import {
  LAYER_PRESENTATION,
  buildEvidenceGraphOption,
  filterEvidenceGraph,
  getGraphHealthPresentation,
  getStatusPresentation,
} from './evidenceGraphPresentation'
import './EvidenceGraph.css'


function detailValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未记录'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function detailLabel(key: string): string {
  const labels: Record<string, string> = {
    case_type: '案件类型',
    status: '当前状态',
    quality_score: '质量评分',
    field: '字段',
    value: '记录值',
    required: '是否必需',
    evidence_type: '材料类型',
    requirement_key: '材料要求',
    captured_at: '采集时间',
    sensitive: '敏感材料',
    asset_type: '资产类型',
    version: '版本',
    source_data_version: '来源版本',
    reviewed_at: '复核时间',
    facility_type: '设施类型',
    occurred_time: '发生时间',
    distance_km: '距离（公里）',
    verified: '坐标已核验',
    is_high_production: '高产井标记',
    region: '作业区',
    coordinate_value: '精确坐标',
    run_id: '运行编号',
    task_type: '任务类型',
    run_status: '运行状态',
    artifact_type: '成果类型',
    source_signature: '来源签名',
    reference: '引用编号',
    asset_id: '资产编号',
    artifact_id: '成果编号',
    referenced_as: '原引用编号',
  }
  return labels[key] ?? key
}

const EvidenceGraph: React.FC = () => {
  const { message } = AntdApp.useApp()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user, sessionEpoch } = useAuth()
  const caseId = parseCaseDeepLinkId(searchParams.get('caseId')) ?? undefined
  const [wellRadiusKm, setWellRadiusKm] = useState(5)
  const [showContext, setShowContext] = useState(true)
  const [showInferred, setShowInferred] = useState(true)
  const [showGaps, setShowGaps] = useState(true)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const chartRef = useRef<ReactECharts | null>(null)

  const casesQuery = useQuery({
    queryKey: ['cases', 'evidence-graph-recent', user?.id, sessionEpoch],
    queryFn: () => caseApi.getCases({ limit: 50 }),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!searchParams.has('caseId') && !casesQuery.isError && casesQuery.data?.length) {
      const firstId = casesQuery.data[0].id
      setSearchParams({ caseId: String(firstId) }, { replace: true })
    }
  }, [caseId, casesQuery.data, casesQuery.isError, setSearchParams, searchParams])

  const graphQuery = useQuery({
    queryKey: ['evidence-graph', caseId, wellRadiusKm, user?.id, sessionEpoch],
    queryFn: () => evidenceGraphApi.getCaseGraph(caseId!, { wellRadiusKm }),
    enabled: Boolean(caseId),
  })
  const graph = graphQuery.isError ? undefined : graphQuery.data
  const filtered = useMemo(() => (
    graph
      ? filterEvidenceGraph(graph, { showContext, showInferred, showGaps })
      : { nodes: [], edges: [] }
  ), [graph, showContext, showInferred, showGaps])
  const option = useMemo(
    () => buildEvidenceGraphOption(filtered.nodes, filtered.edges),
    [filtered],
  )
  const selectedNode = graph?.nodes.find(item => item.id === selectedNodeId) ?? null
  const selectedEdge = graph?.edges.find(item => item.id === selectedEdgeId) ?? null
  const health = graph ? getGraphHealthPresentation(graph.summary.graph_health) : null

  const chooseCase = (value: number) => {
    setSelectedNodeId(null)
    setSelectedEdgeId(null)
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.set('caseId', String(value)); return next })
  }

  const onChartClick = (params: { dataType?: string; data?: EvidenceGraphNode | EvidenceGraphEdge }) => {
    if (params.dataType === 'node' && params.data?.id) {
      setSelectedNodeId(params.data.id)
      setSelectedEdgeId(null)
    }
    if (params.dataType === 'edge' && params.data?.id) {
      setSelectedEdgeId(params.data.id)
      setSelectedNodeId(null)
    }
  }

  const focusIssue = (nodeIds: string[]) => {
    const visible = nodeIds.find(id => filtered.nodes.some(item => item.id === id))
    if (!visible) {
      message.info('该断链节点当前被筛选器隐藏，请打开“缺口”或“未确认推断”。')
      return
    }
    setSelectedNodeId(visible)
    setSelectedEdgeId(null)
    chartRef.current?.getEchartsInstance().dispatchAction({ type: 'focusNodeAdjacency', dataIndex: filtered.nodes.findIndex(item => item.id === visible) })
  }

  const exportSummary = () => {
    if (!graph) return
    const blob = new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `evidence-graph-${graph.case_number}-${graph.source_snapshot.data_version.slice(0, 8)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="page-scrollable evidence-graph-page">
      <section className="eg-hero">
        <div>
          <span className="eg-kicker">v2.9 · EVIDENCE CORRIDOR</span>
          <h1>单案证据关系图谱</h1>
          <p>从原始记录到人工确认成果逐层追溯；断开的引用、未确认推断和空间参考不会被包装成事实。</p>
        </div>
        <div className="eg-hero-controls">
          <Select
            showSearch
            value={caseId}
            loading={casesQuery.isLoading}
            placeholder="选择案件"
            optionFilterProp="searchText"
            onChange={chooseCase}
            options={(casesQuery.data ?? []).map(item => ({
              value: item.id,
              label: item.case_number,
              searchText: [item.case_number, item.case_type, item.location].filter(Boolean).join(' '),
            }))}
          />
          <Select
            value={wellRadiusKm}
            onChange={setWellRadiusKm}
            options={[1, 3, 5, 10, 20].map(value => ({ value, label: `井点参考半径 ${value}km` }))}
          />
          <button className="btn-ghost" disabled={!graph} onClick={exportSummary}>
            <DownloadOutlined /> 导出证据摘要
          </button>
        </div>
      </section>

      {graphQuery.isError ? (
        <div className="empty-state eg-error">
          <span className="icon">!</span>
          <span>证据图谱暂不可用，不影响案件和研判主流程。</span>
          <button className="btn-ghost" onClick={() => void graphQuery.refetch()}>重新读取</button>
        </div>
      ) : !graph ? (
        <div className="empty-state eg-loading"><span className="icon">⌛</span>正在组织证据路径</div>
      ) : (
        <>
          <section className="eg-kpis" aria-label="证据图谱摘要">
            <div className={`eg-health eg-health--${health?.tone}`}>
              <span>图谱状态</span><strong>{health?.label}</strong><small>只读诊断</small>
            </div>
            <div><span>可追溯率</span><strong>{graph.summary.traceability_rate}%</strong><small>派生成果有来源</small></div>
            <div><span>原始来源</span><strong>{graph.summary.source_nodes}</strong><small>字段与材料</small></div>
            <div><span>人工确认</span><strong>{graph.summary.confirmed_nodes}</strong><small>确认节点</small></div>
            <div><span>待确认</span><strong>{graph.summary.inferred_nodes}</strong><small>草稿与派生</small></div>
            <div><span>断链缺口</span><strong>{graph.summary.gap_nodes}</strong><small>{graph.review_queue.length} 项待复核</small></div>
          </section>

          <section className="eg-stage-strip" aria-label="证据层级">
            {Object.entries(LAYER_PRESENTATION).map(([key, value], index) => (
              <div key={key} style={{ '--layer-color': value.color } as React.CSSProperties}>
                <i>{String(index + 1).padStart(2, '0')}</i><span>{value.label}</span>
              </div>
            ))}
          </section>

          <section className="eg-toolbar card">
            <div className="card-head">
              <NodeIndexOutlined className="ico" /><span className="ti">证据走廊 · {graph.case_number}</span>
              <span className="spacer" /><code>SNAP {graph.source_snapshot.data_version.slice(0, 12)}</code>
            </div>
            <div className="eg-filter-row">
              <label><Switch size="small" checked={showContext} onChange={setShowContext} /> 双域背景</label>
              <label><Switch size="small" checked={showInferred} onChange={setShowInferred} /> 未确认推断</label>
              <label><Switch size="small" checked={showGaps} onChange={setShowGaps} /> 断链缺口</label>
              <span>{filtered.nodes.length} 节点 · {filtered.edges.length} 路径</span>
            </div>
          </section>

          <section className="eg-main-grid">
            <div className="card eg-canvas-card">
              <ReactECharts
                ref={chartRef}
                option={option}
                className="eg-canvas"
                style={{ height: 650 }}
                onEvents={{ click: onChartClick }}
              />
              <div className="eg-canvas-tip">滚轮缩放 · 拖动画布 · 点击节点或连线查看依据边界</div>
            </div>

            <aside className="eg-side">
              <section className="card eg-inspector">
                <div className="card-head"><span className="ico">▤</span><span className="ti">证据检查器</span></div>
                {selectedNode ? (
                  <div className="eg-inspector-body">
                    <div className="eg-node-head">
                      <span className={`eg-status eg-status--${getStatusPresentation(selectedNode.status).tone}`}>
                        {getStatusPresentation(selectedNode.status).label}
                      </span>
                      <code>{selectedNode.source_ref}</code>
                    </div>
                    <h2>{selectedNode.label}</h2>
                    <p>{selectedNode.subtitle}</p>
                    <dl>
                      {Object.entries(selectedNode.detail).map(([key, value]) => (
                        <div key={key}><dt>{detailLabel(key)}</dt><dd>{detailValue(value)}</dd></div>
                      ))}
                    </dl>
                    <div className="eg-confirm-state">
                      {selectedNode.is_human_confirmed ? '✓ 已有人工作出确认' : '◇ 未标记为人工确认'}
                    </div>
                  </div>
                ) : selectedEdge ? (
                  <div className="eg-inspector-body">
                    <div className="eg-node-head">
                      <span className={`eg-status eg-status--${getStatusPresentation(selectedEdge.status).tone}`}>
                        {getStatusPresentation(selectedEdge.status).label}
                      </span>
                      <code>{Math.round(selectedEdge.confidence * 100)}%</code>
                    </div>
                    <h2>{selectedEdge.label}</h2>
                    <p>{selectedEdge.source} → {selectedEdge.target}</p>
                    <div className="eg-boundary-note">{selectedEdge.boundary}</div>
                    <div className="eg-ref-list">
                      <span>路径依据</span>
                      {selectedEdge.evidence_refs.map(ref => <code key={ref}>{ref}</code>)}
                    </div>
                  </div>
                ) : (
                  <div className="empty-state eg-inspector-empty"><span className="icon">◇</span>选择节点或连线查看来源</div>
                )}
              </section>

              <section className="card eg-review-queue">
                <div className="card-head">
                  <SafetyCertificateOutlined className="ico" /><span className="ti">断链复核队列</span>
                  <span className="spacer" /><span className="chip warn">{graph.review_queue.length}</span>
                </div>
                <div className="eg-issue-list">
                  {graph.review_queue.length ? graph.review_queue.map(item => (
                    <button key={item.id} onClick={() => focusIssue(item.related_node_ids)}>
                      <span className={`eg-severity eg-severity--${item.severity}`}>{item.severity === 'high' ? '关键' : item.severity === 'medium' ? '复核' : '提示'}</span>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                      <small>{item.next_action}</small>
                    </button>
                  )) : (
                    <div className="empty-state eg-issues-empty"><span className="icon">✓</span>当前没有自动发现的断链</div>
                  )}
                </div>
              </section>
            </aside>
          </section>

          <section className="eg-boundary">
            <strong>证据边界</strong>
            {graph.boundary.statements.map(item => <span key={item}>{item}</span>)}
          </section>
        </>
      )}
    </div>
  )
}

export default EvidenceGraph
