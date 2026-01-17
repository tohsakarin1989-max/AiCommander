import React from 'react'
import { Card, Empty, Space, Alert, List, Typography } from 'antd'

const { Paragraph } = Typography

export interface GeoClue {
  title: string
  description: string
  suggestions?: string[]
}

export interface GeoAnalysisData {
  clues?: GeoClue[]
  recommendations?: string[]
}

interface GeoCluesPanelProps {
  geoAnalysis?: GeoAnalysisData
}

/**
 * 地理线索面板
 * 展示基于地理分析得出的案件线索和建议
 */
const GeoCluesPanel: React.FC<GeoCluesPanelProps> = ({ geoAnalysis }) => {
  if (!geoAnalysis?.clues || geoAnalysis.clues.length === 0) {
    return <Empty description="暂无地理线索" />
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      {geoAnalysis.clues.map((clue, idx) => (
        <Card key={idx} title={clue.title}>
          <Paragraph>{clue.description}</Paragraph>
          {clue.suggestions && (
            <Alert
              message="研判建议"
              description={
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {clue.suggestions.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              }
              type="info"
              style={{ marginTop: 8 }}
            />
          )}
        </Card>
      ))}
      {geoAnalysis.recommendations && (
        <Card title="综合建议">
          <List
            dataSource={geoAnalysis.recommendations}
            renderItem={(item) => <List.Item>{item}</List.Item>}
          />
        </Card>
      )}
    </Space>
  )
}

export default GeoCluesPanel
