import { useMemo, useState, useCallback, useRef } from 'react'
import { Input, Table, Switch, message, Select } from 'antd'
import {
  ShareAltOutlined,
  TableOutlined,
  NodeIndexOutlined,
  DownloadOutlined,
  FilterOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { analysisApi, SerialGraph, GraphNode, GraphEdge } from '../../services/analysis'
import { caseApi } from '../../services/cases'
import ReactECharts from 'echarts-for-react'
import './CaseGraph.css'

const EDGE_COLORS: Record<string, string> = {
  modus:            '#13c2c2',
  geo:              '#52c41a',
  time:             '#722ed1',
  type:             '#595959',
  duplicate_anchor: '#fa8c16',
}

const EDGE_LABELS: Record<string, string> = {
  modus:            '相似手法',
  geo:              '地理接近',
  time:             '时间接近',
  type:             '同一类型',
  duplicate_anchor: '重复锚点核验',
}

const EDGE_DASH: Record<string, boolean> = {
  geo:              true,
  time:             true,
  type:             true,
  duplicate_anchor: true,
}

const nodeSize = (count: number) => Math.min(20 + count * 6, 52)

type GraphEdgeDetail = Pick<
  GraphEdge,
  'reasons' | 'score' | 'relation_types' | 'dominant_type'
> & {
  source: string
  target: string
}

// 格式化发案时间
function formatOccurredTime(iso: string | null | undefined): string {
  if (!iso) return '未知'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

const CaseGraph: React.FC = () => {
  const [caseIdsInput, setCaseIdsInput] = useState('')
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([])
  const [graph, setGraph] = useState<SerialGraph | null>(null)
  const [showTables, setShowTables] = useState(false)
  const [onlyStrong, setOnlyStrong] = useState(false)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [selectedEdge, setSelectedEdge] = useState<GraphEdgeDetail | null>(null)
  const echartsRef = useRef<ReactECharts | null>(null)

  // 获取最近50条案件，用于快捷选择
  const { data: recentCases = [] } = useQuery({
    queryKey: ['cases', 'recent50'],
    queryFn: () => caseApi.getCases({ limit: 50 }),
    staleTime: 60_000,
  })

  const buildMutation = useMutation({
    mutationFn: (caseIds: number[]) => analysisApi.graph.buildSerial(caseIds),
    onSuccess: (data) => {
      setGraph(data)
      setSelectedNode(null)
      setSelectedEdge(null)
      message.success(`图谱生成完成，共 ${data.nodes?.length ?? 0} 节点 · ${data.edges?.length ?? 0} 关系`)
    },
    onError: (error: unknown) => {
      const err = error as { response?: { data?: { detail?: string } } }
      message.error(err?.response?.data?.detail || '生成失败')
    },
  })

  // 合并输入框和下拉框 ID，去重
  const parseCaseIds = useCallback((): number[] => {
    const fromInput = caseIdsInput
      .split(',')
      .map((item) => parseInt(item.trim(), 10))
      .filter((id) => !Number.isNaN(id))
    return Array.from(new Set([...fromInput, ...selectedCaseIds]))
  }, [caseIdsInput, selectedCaseIds])

  // 过滤后的边（可选仅显示强关联 score>=0.5）
  const filteredEdges = useMemo(() => {
    if (!graph?.edges) return []
    return onlyStrong ? graph.edges.filter((edge) => edge.score >= 0.5) : graph.edges
  }, [graph, onlyStrong])

  const option = useMemo(() => {
    if (!graph) return {}
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'oklch(0.12 0.012 250)',
        borderColor: 'oklch(0.32 0.014 250 / 0.7)',
        textStyle: { color: 'oklch(0.82 0.010 90)', fontSize: 11 },
        formatter: (params: { dataType?: string; data?: Record<string, unknown> }) => {
          if (params.dataType === 'edge') {
            const d = params.data ?? {}
            const reasons = (d.reasons as string[] | undefined) ?? []
            const relTypes = (d.relation_types as string[] | undefined) ?? []
            const typeLabels = relTypes.map((t) => EDGE_LABELS[t] || t).join('、')
            return [
              `<b>关联评分：${d.score ?? 0}</b>`,
              `类型：${typeLabels}`,
              ...reasons,
            ].join('<br/>')
          }
          const d = params.data ?? {}
          return [
            `<b>${d.case_number || ''}</b>`,
            d.case_type ? `类型：${d.case_type}` : '',
            d.location ? `地点：${d.location}` : '',
            d.occurred_time ? `时间：${formatOccurredTime(d.occurred_time as string)}` : '',
            d.oil_type ? `油品：${d.oil_type}` : '',
            d.facility_type ? `设施：${d.facility_type}` : '',
            d.involved_persons_count != null ? `涉案人员：${d.involved_persons_count} 人` : '',
          ].filter(Boolean).join('<br/>')
        },
      },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          label: { show: true, color: 'oklch(0.82 0.010 90)', fontSize: 11 },
          force: {
            repulsion: 300,
            edgeLength: [80, 200],
            gravity: 0.1,
            layoutAnimation: true,
          },
          emphasis: { focus: 'adjacency', blurScope: 'global' },
          data: graph.nodes.map((node) => ({
            id: String(node.id),
            name: node.case_number,
            symbolSize: nodeSize(node.involved_persons_count || 0),
            itemStyle: { color: 'oklch(0.45 0.12 250)', borderColor: 'rgba(255,255,255,0.2)', borderWidth: 1.5 },
            // 透传字段供 tooltip 和点击详情使用
            case_number: node.case_number,
            case_type: node.case_type,
            location: node.location,
            occurred_time: node.occurred_time,
            oil_type: node.oil_type,
            oil_volume: node.oil_volume,
            facility_type: node.facility_type,
            involved_persons_count: node.involved_persons_count,
            has_vehicle: node.has_vehicle,
          })),
          links: filteredEdges.map((edge) => ({
            source: String(edge.source),
            target: String(edge.target),
            reasons: edge.reasons,
            score: edge.score,
            relation_types: edge.relation_types,
            dominant_type: edge.dominant_type,
            lineStyle: {
              width: EDGE_COLORS[edge.dominant_type]
                ? (edge.dominant_type === 'modus' ? 2 : 1.5)
                : 1,
              opacity: 0.85,
              color: EDGE_COLORS[edge.dominant_type] || '#8c8c8c',
              type: EDGE_DASH[edge.dominant_type] ? 'dashed' : 'solid',
            },
          })),
        },
      ],
    }
  }, [graph, filteredEdges])

  const handleChartClick = useCallback((params: { dataType?: string; data?: Record<string, unknown> }) => {
    if (params.dataType === 'node') {
      setSelectedNode(params.data as unknown as GraphNode)
      setSelectedEdge(null)
    } else if (params.dataType === 'edge') {
      setSelectedEdge((params.data as GraphEdgeDetail | undefined) ?? null)
      setSelectedNode(null)
    }
  }, [])

  const handleBuild = useCallback(() => {
    const ids = parseCaseIds()
    if (!ids.length) { message.warning('请输入有效案件 ID 或从下拉列表中选择'); return }
    buildMutation.mutate(ids)
  }, [parseCaseIds, buildMutation])

  // 导出 PNG
  const handleExport = useCallback(() => {
    if (!echartsRef.current) return
    const instance = echartsRef.current.getEchartsInstance()
    const url = instance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#0d1117' })
    const link = document.createElement('a')
    link.href = url
    link.download = `case-graph-${Date.now()}.png`
    link.click()
  }, [])

  const stats = graph?.stats

  const nodeColumns = [
    { title: '案件ID',   dataIndex: 'id',                    key: 'id' },
    { title: '编号',     dataIndex: 'case_number',            key: 'case_number' },
    { title: '类型',     dataIndex: 'case_type',              key: 'case_type' },
    { title: '地点',     dataIndex: 'location',               key: 'location' },
    { title: '手法',     dataIndex: 'modus_operandi',         key: 'modus_operandi' },
    { title: '涉案人员', dataIndex: 'involved_persons_count', key: 'ipc',
      render: (v: number) => `${v ?? 0}人` },
  ]

  const edgeColumns = [
    { title: '来源',     dataIndex: 'source',       key: 'source' },
    { title: '目标',     dataIndex: 'target',       key: 'target' },
    { title: '主要关联', dataIndex: 'dominant_type', key: 'dt',
      render: (v: string) => (
        <span style={{ color: EDGE_COLORS[v] }}>{EDGE_LABELS[v] || v}</span>
      ) },
    {
      title: '原因',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (value: string[]) => value.map((v) => (
        <span key={v} className="cg-reason-tag">{v}</span>
      )),
    },
    { title: '评分', dataIndex: 'score', key: 'score' },
  ]

  return (
    <div className="page-scrollable">

      {/* 页面标题 */}
      <div className="page-title">
        <h1>案件关系图谱</h1>
        <span className="sub">SERIAL CASE GRAPH</span>
      </div>

      {/* 输入区 */}
      <div className="card" style={{ marginBottom: 'var(--gap)' }}>
        <div className="card-head">
          <NodeIndexOutlined className="ico" />
          <span className="ti">图谱引擎 · 图谱构建</span>
        </div>
        <div className="card-body pad">
          <div className="cg-build-row">
            {/* 快捷下拉多选（最近50案） */}
            <Select
              className="cg-select-field"
              mode="multiple"
              allowClear
              placeholder="从最近50案中选择"
              value={selectedCaseIds}
              onChange={setSelectedCaseIds}
              maxTagCount={4}
              optionFilterProp="label"
              options={recentCases.map((c) => ({
                value: c.id,
                label: `${c.case_number}（${c.case_type || '未知类型'}）`,
              }))}
            />

            {/* 手动输入 ID */}
            <Input
              className="cg-input-field"
              placeholder="或手动输入 ID，逗号分隔：1,2,3"
              value={caseIdsInput}
              onChange={(e) => setCaseIdsInput(e.target.value)}
              onPressEnter={handleBuild}
            />

            <button
              className="btn-primary"
              onClick={handleBuild}
              disabled={buildMutation.isPending}
              style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}
            >
              <ShareAltOutlined />
              {buildMutation.isPending ? '生成中...' : '生成图谱'}
            </button>
            <div className="cg-view-toggle">
              <TableOutlined />
              <span>表格视图</span>
              <Switch className="cg-switch" checked={showTables} onChange={setShowTables} />
            </div>
          </div>
        </div>
      </div>

      {/* 主内容区 */}
      {!showTables ? (
        <div style={{ display: 'flex', gap: 'var(--gap)', alignItems: 'flex-start' }}>

          {/* 左：图谱 */}
          <div className="card" style={{ flex: 1, minWidth: 0 }}>
            <div className="card-head">
              <ShareAltOutlined className="ico" />
              <span className="ti">可视化 · 关联图谱</span>
              <span className="spacer" />
              {/* 强关联过滤 */}
              <div className="cg-filter-row">
                <FilterOutlined style={{ color: 'var(--ink-3)', fontSize: 11 }} />
                <span className="cg-filter-label">仅强关联（≥0.5）</span>
                <Switch className="cg-switch" size="small" checked={onlyStrong} onChange={setOnlyStrong} />
              </div>
              {/* 导出按钮 */}
              {graph && (
                <button className="cg-export-btn" onClick={handleExport} title="导出 PNG">
                  <DownloadOutlined />
                  <span>导出</span>
                </button>
              )}
              <span style={{ fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ink-3)', marginLeft: 8 }}>
                {graph
                  ? `${graph.nodes?.length ?? 0} 节点 · ${filteredEdges.length} 关系`
                  : '待生成'}
              </span>
            </div>
            <div className="card-body">
              {graph ? (
                <ReactECharts
                  ref={echartsRef}
                  option={option}
                  style={{ height: 560 }}
                  className="cg-echarts-container"
                  onEvents={{ click: handleChartClick }}
                />
              ) : (
                <div className="empty-state" style={{ minHeight: 360 }}>
                  <div className="icon"><ShareAltOutlined /></div>
                  <span>输入案件 ID 并点击「生成图谱」</span>
                </div>
              )}
            </div>
          </div>

          {/* 右：统计 + 图例 + 详情 */}
          <div style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 'var(--gap)' }}>

            {/* 统计卡片（2×2 网格） */}
            {stats && (
              <div className="card">
                <div className="card-head"><span className="ti">统计 · 图谱摘要</span></div>
                <div className="card-body pad cg-stats-grid">
                  <div className="cg-stat-card cg-stat-blue">
                    <div className="cg-stat-value">{stats.total_nodes}</div>
                    <div className="cg-stat-label">节点总数</div>
                  </div>
                  <div className="cg-stat-card cg-stat-orange">
                    <div className="cg-stat-value">{stats.total_edges}</div>
                    <div className="cg-stat-label">关联总数</div>
                  </div>
                  <div className="cg-stat-card cg-stat-red">
                    <div className="cg-stat-value">{stats.strong_links}</div>
                    <div className="cg-stat-label">强关联数</div>
                  </div>
                  <div className="cg-stat-card cg-stat-purple">
                    <div className="cg-stat-value">{stats.duplicate_anchor_links ?? 0}</div>
                    <div className="cg-stat-label">重复锚点</div>
                  </div>
                </div>
              </div>
            )}

            {/* 图例 */}
            <div className="card">
              <div className="card-head"><span className="ti">图例 · 边线类型</span></div>
              <div className="card-body pad" style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                {Object.entries(EDGE_LABELS).map(([type, label]) => (
                  <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{
                      width: 32,
                      height: 2,
                      background: EDGE_DASH[type] ? 'transparent' : EDGE_COLORS[type],
                      borderBottom: EDGE_DASH[type] ? `2px dashed ${EDGE_COLORS[type]}` : 'none',
                      borderRadius: 1,
                    }} />
                    <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{label}</span>
                  </div>
                ))}
                <div style={{ marginTop: 4, fontSize: 11, color: 'var(--ink-3)' }}>
                  节点大小 = 涉案人员数
                </div>
              </div>
            </div>

            {/* 选中详情 */}
            {(selectedNode || selectedEdge) && (
              <div className="card">
                <div className="card-head">
                  <span className="ti">{selectedNode ? '节点详情' : '边线详情'}</span>
                  <span className="spacer" />
                  <button
                    style={{ background: 'none', border: 'none', color: 'var(--ink-3)', cursor: 'pointer', fontSize: 13 }}
                    onClick={() => { setSelectedNode(null); setSelectedEdge(null) }}
                  >✕</button>
                </div>
                <div className="card-body pad">
                  {selectedNode && (
                    <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div><span style={{ color: 'var(--ink-3)' }}>编号：</span>{selectedNode.case_number}</div>
                      {selectedNode.case_type && <div><span style={{ color: 'var(--ink-3)' }}>类型：</span>{selectedNode.case_type}</div>}
                      {selectedNode.location && <div><span style={{ color: 'var(--ink-3)' }}>地点：</span>{selectedNode.location}</div>}
                      {selectedNode.occurred_time && (
                        <div><span style={{ color: 'var(--ink-3)' }}>时间：</span>{selectedNode.occurred_time?.slice(0, 10)}</div>
                      )}
                      {selectedNode.oil_type && <div><span style={{ color: 'var(--ink-3)' }}>油品：</span>{selectedNode.oil_type}</div>}
                      {selectedNode.facility_type && <div><span style={{ color: 'var(--ink-3)' }}>设施：</span>{selectedNode.facility_type}</div>}
                      <div><span style={{ color: 'var(--ink-3)' }}>涉案人员：</span>{selectedNode.involved_persons_count ?? 0} 人</div>
                      <div><span style={{ color: 'var(--ink-3)' }}>涉及车辆：</span>{selectedNode.has_vehicle ? '是' : '否'}</div>
                    </div>
                  )}
                  {selectedEdge && (
                    <div style={{ fontSize: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div>
                        <span style={{ color: 'var(--ink-3)' }}>案件关系：</span>
                        ID {selectedEdge.source} → ID {selectedEdge.target}
                      </div>
                      <div>
                        <span style={{ color: 'var(--ink-3)' }}>主要类型：</span>
                        <span style={{ color: EDGE_COLORS[selectedEdge.dominant_type] }}>
                          {EDGE_LABELS[selectedEdge.dominant_type] || selectedEdge.dominant_type}
                        </span>
                      </div>
                      <div><span style={{ color: 'var(--ink-3)' }}>关联评分：</span>{selectedEdge.score}</div>
                      <div style={{ color: 'var(--ink-3)', marginTop: 2 }}>关联原因：</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {(selectedEdge.reasons || []).map((r: string) => (
                          <span key={r} className="cg-reason-tag">{r}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        /* 表格视图 */
        <>
          <div className="card" style={{ marginBottom: 'var(--gap)' }}>
            <div className="card-head"><span className="ti">节点 · 图谱节点</span></div>
            <div className="card-body">
              <Table
                rowKey="id"
                dataSource={graph?.nodes || []}
                columns={nodeColumns}
                pagination={{ pageSize: 8 }}
              />
            </div>
          </div>
          <div className="card">
            <div className="card-head"><span className="ti">边线 · 图谱关系</span></div>
            <div className="card-body">
              <Table
                rowKey={(record) => `${record.source}-${record.target}`}
                dataSource={graph?.edges || []}
                columns={edgeColumns}
                pagination={{ pageSize: 8 }}
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default CaseGraph
