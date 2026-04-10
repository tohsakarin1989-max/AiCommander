import React, { useState } from 'react'
import { Card, List, Button, Spin, Space, Typography, Switch, Divider } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FireOutlined, LinkOutlined, FieldTimeOutlined } from '@ant-design/icons'
import { caseApi } from '../../services/cases'
import LeafletMap from '../../components/Map/LeafletMap'
import type { CaseMarker, SerialGroup, Hotspot, SerialCaseGroup } from '../../types'
import type { Case } from '../../types'

const { Text } = Typography

const RISK_COLOR: Record<string, string> = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
}

const cardStyle = {
  background: '#0d1117',
  border: '1px solid #1e293b',
  borderRadius: 6,
}

const CasesMap: React.FC = () => {
  const navigate = useNavigate()
  const [showSerial, setShowSerial] = useState(true)
  const [selectedCase, setSelectedCase] = useState<Case | null>(null)

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
    queryFn: () => caseApi.getSerialCases(),
  })

  // 有坐标的案件 → LeafletMap markers
  const markers: CaseMarker[] = (cases || [])
    .filter((c) => c.latitude != null && c.longitude != null)
    .map((c) => ({
      id: c.id,
      lat: c.latitude!,
      lng: c.longitude!,
      title: c.case_number,
      caseNumber: c.case_number,
      caseType: c.case_type,
      riskLevel: 'medium' as const,
      occurredTime: c.occurred_time,
      modus: c.modus_operandi,
    }))

  // 串案组
  const serialGroups: SerialGroup[] = showSerial
    ? (serialCases || []).map((group: SerialCaseGroup, i: number) => ({
        caseIds: group.case_ids,
        color: ['#a78bfa', '#f472b6', '#34d399', '#fb923c'][i % 4],
      }))
    : []

  // 热点列表（取前5）
  const topHotspots = (hotspots || []).slice(0, 5)

  return (
    <div style={{ height: 'calc(100vh - 80px)', display: 'flex', gap: 12 }}>
      {/* 左侧控制面板 */}
      <div style={{ width: 200, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>图层控制</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <Text style={{ color: '#cbd5e1', fontSize: 12 }}>串案连线</Text>
              <Switch
                size="small"
                checked={showSerial}
                onChange={setShowSerial}
                style={{ '--ant-color-primary': '#7dd3fc' } as React.CSSProperties}
              />
            </div>
          </div>
        </Card>

        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>热点区域</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {topHotspots.length === 0 ? (
              <Text style={{ color: '#475569', fontSize: 11 }}>暂无热点数据</Text>
            ) : (
              topHotspots.map(
                (h: Hotspot, i: number) => {
                  // risk_score > 0.6 = 高风险，> 0.3 = 中风险，否则低风险
                  const riskLevel = h.risk_score > 0.6 ? 'high' : h.risk_score > 0.3 ? 'medium' : 'low'
                  return (
                    <div
                      key={i}
                      style={{
                        background: '#1e293b',
                        borderRadius: 4,
                        padding: '5px 8px',
                        borderLeft: `2px solid ${RISK_COLOR[riskLevel]}`,
                      }}
                    >
                      <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 600 }}>
                        {`${h.center.latitude.toFixed(4)}, ${h.center.longitude.toFixed(4)}`}
                      </div>
                      <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 2 }}>
                        {h.case_count}起 · 半径{h.radius_km.toFixed(1)}km
                      </div>
                    </div>
                  )
                }
              )
            )}
          </div>
        </Card>

        <Button
          icon={<FieldTimeOutlined />}
          style={{
            background: 'rgba(125,211,252,0.1)',
            border: '1px solid #7dd3fc',
            color: '#7dd3fc',
            width: '100%',
          }}
          onClick={() => navigate('/cases/spacetime')}
        >
          时空研判
        </Button>
      </div>

      {/* 地图主体 */}
      <div style={{ flex: 1 }}>
        {isLoading ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spin tip="加载地图数据..." />
          </div>
        ) : (
          <LeafletMap
            markers={markers}
            serialGroups={serialGroups}
            height="100%"
            onMarkerClick={(m) => {
              const found = (cases || []).find((c) => c.id === m.id)
              if (found) setSelectedCase(found)
            }}
          />
        )}
      </div>

      {/* 右侧 AI 分析面板 */}
      <div style={{ width: 200, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        {/* 选中案件详情 */}
        {selectedCase && (
          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#7dd3fc', fontSize: 11, fontWeight: 600 }}>选中案件</Text>
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 600 }}>{selectedCase.case_number}</div>
              <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 2 }}>{selectedCase.case_type || '未分类'}</div>
              <div style={{ color: '#64748b', fontSize: 10 }}>
                {selectedCase.occurred_time?.slice(0, 10)}
              </div>
            </div>
            <Divider style={{ borderColor: '#1e293b', margin: '8px 0' }} />
            <Button
              size="small"
              type="link"
              style={{ color: '#7dd3fc', padding: 0, fontSize: 11 }}
              onClick={() => navigate(`/cases`)}
            >
              查看详情 →
            </Button>
          </Card>
        )}

        {/* AI 巡逻建议 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Space style={{ marginBottom: 8 }}>
            <FireOutlined style={{ color: '#f59e0b' }} />
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>AI巡逻建议</Text>
          </Space>
          <Text style={{ color: '#475569', fontSize: 11 }}>请前往「区域研判」生成巡逻建议</Text>
        </Card>

        {/* 串案分析 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Space style={{ marginBottom: 8 }}>
            <LinkOutlined style={{ color: '#a78bfa' }} />
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>串案关联</Text>
          </Space>
          {(serialCases || []).length === 0 ? (
            <Text style={{ color: '#475569', fontSize: 11 }}>未发现串案</Text>
          ) : (
            <div style={{ color: '#7dd3fc', fontSize: 11 }}>
              发现 {(serialCases || []).length} 组串案
              <List
                size="small"
                dataSource={(serialCases || []).slice(0, 2)}
                renderItem={(group: SerialCaseGroup, i: number) => (
                  <List.Item key={group.group_id} style={{ padding: '4px 0', borderBottom: '1px solid #1e293b' }}>
                    <Text style={{ color: '#94a3b8', fontSize: 10 }}>
                      组 {i + 1}：{group.case_ids.length} 起案件
                    </Text>
                  </List.Item>
                )}
              />
            </div>
          )}
        </Card>

        {/* 图例 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>图例</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
            {Object.entries({ '高风险': '#ef4444', '中风险': '#f59e0b', '低风险': '#22c55e', '案件点': '#7dd3fc' }).map(([label, color]) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                <Text style={{ color: '#94a3b8', fontSize: 11 }}>{label}</Text>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 16, height: 2, background: 'repeating-linear-gradient(90deg,#a78bfa,#a78bfa 4px,transparent 4px,transparent 7px)' }} />
              <Text style={{ color: '#94a3b8', fontSize: 11 }}>串案连线</Text>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

export default CasesMap
