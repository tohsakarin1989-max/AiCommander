import React from 'react'
import { List, Card, Empty, Tag, Space, Descriptions, Typography } from 'antd'

const { Text } = Typography

export interface HotspotData {
  center_latitude: number
  center_longitude: number
  case_count: number
  radius_km: number
  cases: Array<{
    id: number
    case_number: string
  }>
}

interface HotspotsPanelProps {
  hotspots?: HotspotData[]
}

/**
 * 热点区域面板
 * 展示案件高发区域的聚类分析结果
 */
const HotspotsPanel: React.FC<HotspotsPanelProps> = ({ hotspots }) => {
  if (!hotspots || hotspots.length === 0) {
    return <Empty description="暂无热点区域" />
  }

  return (
    <List
      dataSource={hotspots}
      renderItem={(hotspot) => (
        <List.Item>
          <Card style={{ width: '100%' }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="中心位置">
                {hotspot.center_latitude.toFixed(6)},{' '}
                {hotspot.center_longitude.toFixed(6)}
              </Descriptions.Item>
              <Descriptions.Item label="案件数量">
                <Tag color="red">{hotspot.case_count} 起</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="影响半径">
                {hotspot.radius_km} 公里
              </Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 8 }}>
              <Text strong>涉及案件：</Text>
              <Space wrap style={{ marginTop: 4 }}>
                {hotspot.cases.slice(0, 5).map((c) => (
                  <Tag key={c.id}>{c.case_number}</Tag>
                ))}
                {hotspot.cases.length > 5 && (
                  <Tag>+{hotspot.cases.length - 5} 个</Tag>
                )}
              </Space>
            </div>
          </Card>
        </List.Item>
      )}
    />
  )
}

export default HotspotsPanel
