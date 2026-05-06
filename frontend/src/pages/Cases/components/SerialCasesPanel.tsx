import React from 'react'
import { List, Card, Empty, Tag, Space, Descriptions, Alert, Typography } from 'antd'

const { Text } = Typography

export interface SerialCaseGroup {
  case_count: number
  time_span_days: number
  center_latitude: number
  center_longitude: number
  common_case_type?: string
  cases: Array<{
    id: number
    case_number: string
  }>
  analysis: {
    likely_serial: boolean
    suggestions: string[]
  }
}

interface SerialCasesPanelProps {
  serialCases?: SerialCaseGroup[]
}

/**
 * 串案分析面板
 * 展示可能的系列案件分组和分析结果
 */
const SerialCasesPanel: React.FC<SerialCasesPanelProps> = ({ serialCases }) => {
  if (!serialCases || serialCases.length === 0) {
    return <Empty description="暂无串案" />
  }

  return (
    <List
      dataSource={serialCases}
      renderItem={(group) => (
        <List.Item>
          <Card style={{ width: '100%' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Descriptions column={3} size="small">
                <Descriptions.Item label="串案组">
                  <Tag color={group.analysis.likely_serial ? 'red' : 'orange'}>
                    {group.analysis.likely_serial ? '高度疑似' : '可能串案'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="案件数量">
                  {group.case_count} 起
                </Descriptions.Item>
                <Descriptions.Item label="时间跨度">
                  {group.time_span_days} 天
                </Descriptions.Item>
                <Descriptions.Item label="中心位置">
                  {group.center_latitude.toFixed(6)},{' '}
                  {group.center_longitude.toFixed(6)}
                </Descriptions.Item>
                <Descriptions.Item label="共同类型">
                  {group.common_case_type || '未知'}
                </Descriptions.Item>
              </Descriptions>
              <div>
                <Text strong>涉及案件：</Text>
                <Space wrap style={{ marginTop: 4 }}>
                  {group.cases.map((c) => (
                    <Tag key={c.id}>{c.case_number}</Tag>
                  ))}
                </Space>
              </div>
              {group.analysis.suggestions.length > 0 && (
                <Alert
                  message="研判建议"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {group.analysis.suggestions.map((s, idx) => (
                        <li key={idx}>{s}</li>
                      ))}
                    </ul>
                  }
                  type="info"
                />
              )}
            </Space>
          </Card>
        </List.Item>
      )}
    />
  )
}

export default SerialCasesPanel
