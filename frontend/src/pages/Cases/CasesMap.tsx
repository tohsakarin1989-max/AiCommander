import React, { useState } from 'react'
import { Button, List, Spin, Switch } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  FireOutlined,
  LinkOutlined,
  FieldTimeOutlined,
  EnvironmentOutlined,
  AppstoreOutlined,
} from '@ant-design/icons'
import { caseApi } from '../../services/cases'
import LeafletMap from '../../components/Map/LeafletMap'
import type { CaseMarker, ChainLinkLine, ChainPosition, SerialGroup, Hotspot, SerialCaseGroup } from '../../types'
import type { Case } from '../../types'
import { chainPositionMeta, getChainPosition } from '../../utils/chainType'
import './CasesMap.css'

const RISK_LEVEL = (score: number): 'high' | 'medium' | 'low' =>
  score > 0.6 ? 'high' : score > 0.3 ? 'medium' : 'low'

const CHAIN_FILTERS: ChainPosition[] = ['upstream', 'midstream', 'downstream', 'unknown']

const LEGEND_ITEMS: Array<{ label: string; type: 'dot' | 'line'; color: string; shape?: string }> = [
  { label: '盗采环节',  type: 'dot',  color: chainPositionMeta.upstream.color, shape: 'hexagon' },
  { label: '运输环节',  type: 'dot',  color: chainPositionMeta.midstream.color, shape: 'diamond' },
  { label: '囤储环节',  type: 'dot',  color: chainPositionMeta.downstream.color, shape: 'square' },
  { label: '未分类',  type: 'dot',  color: chainPositionMeta.unknown.color, shape: 'circle' },
  { label: '链条推断', type: 'line', color: '#f59e0b' },
  { label: '确认链条', type: 'line', color: '#22c55e' },
]

const CasesMap: React.FC = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [showSerial, setShowSerial] = useState(true)
  const [showChainLinks, setShowChainLinks] = useState(true)
  const [visiblePositions, setVisiblePositions] = useState<ChainPosition[]>(['upstream', 'midstream', 'downstream', 'unknown'])
  const [selectedCase, setSelectedCase] = useState<Case | null>(null)
  const selectedCaseId = Number(searchParams.get('caseId') || 0) || undefined

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: hotspots } = useQuery({
    queryKey: ['hotspots'],
    queryFn: () => caseApi.getHotspots(),
  })

  const { data: serialCases } = useQuery({
    queryKey: ['serialCases'],
    // 仅用地理分析，关闭语义搜索（向量库未就绪时会超时 20s+）
    queryFn: () => caseApi.getSerialCases(undefined, 2.0, 30, false, true),
  })

  const { data: chainMapData } = useQuery({
    queryKey: ['chain-map-data', selectedCaseId],
    queryFn: () => caseApi.getChainMapData({ case_id: selectedCaseId, min_confidence: 0.5 }),
  })

  // 有坐标的案件 → LeafletMap markers
  const markers: CaseMarker[] = (cases || [])
    .filter((c) => c.latitude != null && c.longitude != null)
    .map((c) => {
      const chainPosition = getChainPosition(c)
      return {
        id: c.id,
        lat: c.latitude!,
        lng: c.longitude!,
        title: c.case_number,
        caseNumber: c.case_number,
        caseType: c.case_type,
        riskLevel: 'medium' as const,
        chainPosition,
        occurredTime: c.occurred_time,
        modus: c.modus_operandi,
      }
    })
    .filter((marker) => visiblePositions.includes(marker.chainPosition || 'unknown'))

  const chainLinks: ChainLinkLine[] = showChainLinks
    ? (chainMapData?.chain_links || [])
        .filter(link => link.from_case?.latitude != null && link.from_case.longitude != null && link.to_case?.latitude != null && link.to_case.longitude != null)
        .map((link): ChainLinkLine => ({
          id: link.id,
          status: link.status === 'confirmed' ? 'confirmed' : 'inferred' as const,
          confidence: link.confidence,
          distanceKm: link.distance_km,
          timeDiffDays: link.time_diff_days,
          reasoning: link.reasoning,
          from: {
            id: link.from_case!.id,
            lat: link.from_case!.latitude!,
            lng: link.from_case!.longitude!,
            caseNumber: link.from_case!.case_number,
            chainPosition: link.from_case!.chain_position,
          },
          to: {
            id: link.to_case!.id,
            lat: link.to_case!.latitude!,
            lng: link.to_case!.longitude!,
            caseNumber: link.to_case!.case_number,
            chainPosition: link.to_case!.chain_position,
          },
        }))
        .filter(link => visiblePositions.includes(link.from.chainPosition) || visiblePositions.includes(link.to.chainPosition))
        .slice(0, 50)
    : []

  // 串案组
  const serialGroups: SerialGroup[] = showSerial
    ? (serialCases || []).map((group: SerialCaseGroup, i: number) => ({
        caseIds: group.case_ids,
        color: ['#a78bfa', '#f472b6', '#34d399', '#fb923c'][i % 4],
      }))
    : []

  // 热点列表（取前5）
  const topHotspots = (hotspots || []).slice(0, 5)

  React.useEffect(() => {
    if (!selectedCaseId || !cases) return
    const found = cases.find(item => item.id === selectedCaseId)
    if (found) setSelectedCase(found)
  }, [selectedCaseId, cases])

  const toggleChainPosition = (position: ChainPosition) => {
    setVisiblePositions(prev => (
      prev.includes(position)
        ? prev.filter(item => item !== position)
        : [...prev, position]
    ))
  }

  return (
    <div className="cases-map-wrap">

      {/* ── 页面头 ── */}
      <div className="ds-page-hdr" style={{ paddingBottom: 16, marginBottom: 14 }}>
        <div className="ds-page-hdr__left">
          <div className="ds-eyebrow">空间分布分析</div>
          <h1 className="ds-page-title">案件地图</h1>
        </div>
        <div className="ds-page-hdr__right">
          <Button
            className="cases-map-filter__spacetime-btn"
            icon={<FieldTimeOutlined />}
            onClick={() => navigate('/cases/spacetime')}
          >
            时空研判
          </Button>
        </div>
      </div>

      {/* ── 筛选/图层控制卡片（顶部） ── */}
      <div className="cases-map-filter">
        <span className="cases-map-filter__label">
          <AppstoreOutlined style={{ marginRight: 6 }} />
          图层控制
        </span>
        <div className="cases-map-filter__layer">
          <span className="cases-map-filter__layer-text">串案连线</span>
          <Switch
            size="small"
            checked={showSerial}
            onChange={setShowSerial}
          />
        </div>
        <div className="cases-map-filter__layer">
          <span className="cases-map-filter__layer-text">链条推断</span>
          <Switch
            size="small"
            checked={showChainLinks}
            onChange={setShowChainLinks}
          />
        </div>
        {CHAIN_FILTERS.map(position => (
          <button
            key={position}
            className={`cases-map-chain-filter${visiblePositions.includes(position) ? ' is-on' : ''}`}
            style={{ '--chain-c': chainPositionMeta[position].color } as React.CSSProperties}
            onClick={() => toggleChainPosition(position)}
          >
            {chainPositionMeta[position].shortLabel}
          </button>
        ))}
        <span className="cases-map-filter__label" style={{ marginLeft: 12 }}>
          <EnvironmentOutlined style={{ marginRight: 6 }} />
          标记点：{markers.length} / {(cases || []).length} 件含坐标
        </span>
      </div>

      {/* ── 主体 ── */}
      <div className="cases-map-body">

        {/* 左侧面板 */}
        <div className="cases-map-panel">

          {/* 热点区域 */}
          <div className="cases-map-card">
            <div className="cases-map-card__hdr">
              <FireOutlined style={{ color: 'var(--c-warning)', fontSize: 11 }} />
              <span className="cases-map-card__title">热点区域</span>
            </div>
            <div className="cases-map-card__body">
              {topHotspots.length === 0 ? (
                <span className="cases-map-empty">暂无热点数据</span>
              ) : (
                topHotspots.map((h: Hotspot, i: number) => {
                  const level = RISK_LEVEL(h.risk_score)
                  return (
                    <div key={i} className={`cases-map-hotspot cases-map-hotspot--${level}`}>
                      <div className="cases-map-hotspot__coords">
                        {h.center.latitude.toFixed(4)}, {h.center.longitude.toFixed(4)}
                      </div>
                      <div className="cases-map-hotspot__meta">
                        {h.case_count} 起 · 半径 {h.radius_km.toFixed(1)} km
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* 图例 */}
          <div className="cases-map-card">
            <div className="cases-map-card__hdr">
              <span className="cases-map-card__title">图例</span>
            </div>
            <div className="cases-map-card__body">
              {LEGEND_ITEMS.map(item => (
                <div key={item.label} className="cases-map-legend__item">
                  {item.type === 'dot' ? (
                    <div className={`cases-map-legend__dot cases-map-legend__dot--${item.shape || 'circle'}`} style={{ background: item.color }} />
                  ) : (
                    <div className="cases-map-legend__line" style={{ '--line-c': item.color } as React.CSSProperties} />
                  )}
                  {item.label}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 地图主体 */}
        <div className="cases-map-container">
          {isLoading ? (
            <div className="cases-map-loading">
              <Spin size="large" />
              <span>加载地图数据…</span>
            </div>
          ) : (
            <LeafletMap
              markers={markers}
              serialGroups={serialGroups}
              chainLinks={chainLinks}
              height="100%"
              onMarkerClick={(m) => {
                const found = (cases || []).find((c) => c.id === m.id)
                if (found) setSelectedCase(found)
              }}
            />
          )}
        </div>

        {/* 右侧面板 */}
        <div className="cases-map-panel">

          {/* 选中案件详情 */}
          {selectedCase && (
            <div className="cases-map-card">
              <div className="cases-map-card__hdr">
                <EnvironmentOutlined style={{ color: 'var(--c-cyan)', fontSize: 11 }} />
                <span className="cases-map-card__title">选中案件</span>
              </div>
              <div className="cases-map-card__body">
                <div className="cases-map-selected__num">{selectedCase.case_number}</div>
                <div className="cases-map-selected__type">{selectedCase.case_type || '未分类'}</div>
                <div className="cases-map-selected__date">
                  {selectedCase.occurred_time?.slice(0, 10)}
                </div>
                <div className="cases-map-selected__divider" />
                <Button
                  type="link"
                  size="small"
                  className="cases-map-selected__link"
                  onClick={() => navigate('/cases')}
                >
                  查看详情 →
                </Button>
              </div>
            </div>
          )}

          {/* AI 巡逻建议 */}
          <div className="cases-map-card">
            <div className="cases-map-card__hdr">
              <FireOutlined style={{ color: 'var(--c-warning)', fontSize: 11 }} />
              <span className="cases-map-card__title">AI 巡逻建议</span>
            </div>
            <div className="cases-map-card__body">
              <span className="cases-map-empty">请前往「区域研判」生成防控参考</span>
            </div>
          </div>

          {/* 链条关联 */}
          <div className="cases-map-card">
            <div className="cases-map-card__hdr">
              <LinkOutlined style={{ color: '#a78bfa', fontSize: 11 }} />
              <span className="cases-map-card__title">链条推断</span>
            </div>
            <div className="cases-map-card__body">
              {chainLinks.length === 0 ? (
                <span className="cases-map-serial__empty">未发现链条推断</span>
              ) : (
                <>
                  <div className="cases-map-serial__count">
                    显示 {chainLinks.length} 条链条
                  </div>
                  <List
                    size="small"
                    dataSource={chainLinks.slice(0, 4)}
                    renderItem={(link: ChainLinkLine) => (
                      <List.Item
                        key={link.id}
                        style={{ padding: '4px 0', borderBottom: '1px solid var(--bd-0)' }}
                      >
                        <span className="cases-map-serial__item">
                          {link.from.caseNumber} → {link.to.caseNumber}
                          <small>{link.status === 'confirmed' ? '已确认' : `${Math.round(link.confidence * 100)}%`}</small>
                        </span>
                      </List.Item>
                    )}
                  />
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CasesMap
