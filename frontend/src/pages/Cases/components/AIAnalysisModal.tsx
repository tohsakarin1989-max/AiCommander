import React from 'react'
import { Modal, Spin, Alert, Collapse, Descriptions, List, Card, Space, Tag, Typography } from 'antd'
import { RobotOutlined } from '@ant-design/icons'

const { Text, Paragraph } = Typography
const { Panel } = Collapse

// AI 分析结果的类型定义
export interface AIAnalysisData {
  location_info?: {
    location?: {
      address?: string
      province?: string
      city?: string
      district?: string
      street?: string
    }
  }
  comprehensive_data?: {
    villages?: {
      count: number
      pois?: POIItem[]
    }
    gas_stations?: {
      count: number
      pois?: POIItem[]
    }
    refineries?: {
      count: number
      pois?: POIItem[]
    }
    search_stats?: {
      villages_radius?: number
      gas_stations_radius?: number
      refineries_radius?: number
      is_remote_area?: boolean
    }
  }
  approach_analysis?: {
    search_radius?: number
    approach_analysis?: {
      possible_approaches?: ApproachRoute[]
    }
  }
  ai_analysis?: AIAnalysisContent | string
}

interface POIItem {
  name: string
  type: string
  distance: number
  address: string
  tel?: string
}

interface ApproachRoute {
  name: string
  type: string
  distance: number
  address: string
}

interface AIAnalysisContent {
  geographic_features?: string
  villages_analysis?: string
  gas_stations_analysis?: string
  refineries_analysis?: string
  approach_routes?: string[]
  risk_assessment?: string
  prevention_suggestions?: string[]
}

interface AIAnalysisModalProps {
  visible: boolean
  onClose: () => void
  data?: AIAnalysisData
  loading: boolean
}

/**
 * AI 智能分析模态框
 * 展示结合 MCP 数据的 AI 综合分析结果
 */
const AIAnalysisModal: React.FC<AIAnalysisModalProps> = ({
  visible,
  onClose,
  data,
  loading,
}) => {
  const renderPOIList = (pois: POIItem[] | undefined, pageSize = 5) => {
    if (!pois || pois.length === 0) {
      return <Text type="secondary">未发现相关设施</Text>
    }

    return (
      <List
        dataSource={pois.slice(0, 10)}
        renderItem={(poi) => (
          <List.Item>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                <Text strong>{poi.name}</Text>
                <Tag style={{ marginLeft: 8 }}>{poi.type}</Tag>
              </div>
              <Text type="secondary" style={{ fontSize: '12px' }}>
                距离 {(poi.distance / 1000).toFixed(1)} 公里 | {poi.address}
                {poi.tel && ` | 电话：${poi.tel}`}
              </Text>
            </Space>
          </List.Item>
        )}
        pagination={{ pageSize }}
      />
    )
  }

  const renderAIAnalysisContent = () => {
    if (!data?.ai_analysis) {
      return <Text type="secondary">分析结果解析中...</Text>
    }

    if (typeof data.ai_analysis === 'string') {
      return <Paragraph>{data.ai_analysis}</Paragraph>
    }

    const analysis = data.ai_analysis as AIAnalysisContent

    if (!analysis.geographic_features) {
      return (
        <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
          {JSON.stringify(data.ai_analysis, null, 2)}
        </pre>
      )
    }

    return (
      <div>
        <Card title="地理位置特征" size="small" style={{ marginBottom: 12 }}>
          <Paragraph>{analysis.geographic_features}</Paragraph>
        </Card>
        <Card title="周边村屯分析" size="small" style={{ marginBottom: 12 }}>
          <Paragraph>{analysis.villages_analysis}</Paragraph>
        </Card>
        <Card title="加油站分析" size="small" style={{ marginBottom: 12 }}>
          <Paragraph>{analysis.gas_stations_analysis}</Paragraph>
        </Card>
        <Card title="炼化点分析" size="small" style={{ marginBottom: 12 }}>
          <Paragraph>{analysis.refineries_analysis}</Paragraph>
        </Card>
        {analysis.approach_routes && (
          <Card title="可能的来路" size="small" style={{ marginBottom: 12 }}>
            <List
              dataSource={analysis.approach_routes}
              renderItem={(route) => (
                <List.Item>
                  <Text>• {route}</Text>
                </List.Item>
              )}
            />
          </Card>
        )}
        <Card title="风险评估" size="small" style={{ marginBottom: 12 }}>
          <Paragraph>{analysis.risk_assessment}</Paragraph>
        </Card>
        {analysis.prevention_suggestions && (
          <Card title="防控建议" size="small">
            <List
              dataSource={analysis.prevention_suggestions}
              renderItem={(suggestion) => (
                <List.Item>
                  <Text>• {suggestion}</Text>
                </List.Item>
              )}
            />
          </Card>
        )}
      </div>
    )
  }

  const searchStats = data?.comprehensive_data?.search_stats
  const villages = data?.comprehensive_data?.villages
  const gasStations = data?.comprehensive_data?.gas_stations
  const refineries = data?.comprehensive_data?.refineries
  const approachAnalysis = data?.approach_analysis

  return (
    <Modal
      title={
        <Space>
          <RobotOutlined />
          <span>AI智能位置分析（结合MCP数据）</span>
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={900}
    >
      <Spin spinning={loading}>
        {data && (
          <div>
            <Alert
              message="分析说明"
              description="以下分析结果结合了案件信息、地图MCP数据（位置、周边村屯、加油站、炼化点、路口、天气等）和AI智能分析。"
              type="info"
              style={{ marginBottom: 16 }}
            />

            <Collapse
              defaultActiveKey={['location', 'villages', 'gas', 'refineries', 'routes', 'ai']}
            >
              <Panel header="位置信息" key="location">
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="详细地址">
                    {data.location_info?.location?.address || '未知'}
                  </Descriptions.Item>
                  <Descriptions.Item label="行政区划">
                    {data.location_info?.location?.province || ''}{' '}
                    {data.location_info?.location?.city || ''}{' '}
                    {data.location_info?.location?.district || ''}
                  </Descriptions.Item>
                  <Descriptions.Item label="街道">
                    {data.location_info?.location?.street || '未知'}
                  </Descriptions.Item>
                </Descriptions>
              </Panel>

              <Panel
                header={`周边村屯/社区（${villages?.count || 0} 个，搜索范围：${(searchStats?.villages_radius || 0) / 1000} 公里）`}
                key="villages"
              >
                {searchStats?.is_remote_area && (
                  <Alert
                    message="偏远地区"
                    description="该地区人烟稀少，已自动扩大搜索范围以查找更多村屯信息。"
                    type="warning"
                    style={{ marginBottom: 12 }}
                    showIcon
                  />
                )}
                {renderPOIList(villages?.pois, 10)}
              </Panel>

              <Panel
                header={`周边加油站（${gasStations?.count || 0} 个，搜索范围：${(searchStats?.gas_stations_radius || 0) / 1000} 公里）`}
                key="gas"
              >
                {renderPOIList(gasStations?.pois)}
              </Panel>

              <Panel
                header={`周边炼化点/储油设施（${refineries?.count || 0} 个，搜索范围：${(searchStats?.refineries_radius || 0) / 1000} 公里）`}
                key="refineries"
              >
                {renderPOIList(refineries?.pois)}
              </Panel>

              <Panel
                header={`可能的来路分析（${approachAnalysis?.approach_analysis?.possible_approaches?.length || 0} 条，搜索范围：${(approachAnalysis?.search_radius || 0) / 1000} 公里）`}
                key="routes"
              >
                {approachAnalysis?.approach_analysis?.possible_approaches &&
                approachAnalysis.approach_analysis.possible_approaches.length > 0 ? (
                  <div>
                    <Alert
                      message="来路分析"
                      description={`基于周边路口和道路，在 ${(approachAnalysis.search_radius || 0) / 1000} 公里范围内分析可能的来路方向`}
                      type="info"
                      style={{ marginBottom: 12 }}
                    />
                    <List
                      dataSource={approachAnalysis.approach_analysis.possible_approaches}
                      renderItem={(route, index) => (
                        <List.Item>
                          <Space direction="vertical" style={{ width: '100%' }}>
                            <div>
                              <Text strong>路线 {index + 1}：</Text>
                              <Text>{route.name}</Text>
                              <Tag color="green" style={{ marginLeft: 8 }}>
                                {route.type}
                              </Tag>
                            </div>
                            <Text type="secondary" style={{ fontSize: '12px' }}>
                              距离案发地点 {(route.distance / 1000).toFixed(1)} 公里 |{' '}
                              {route.address}
                            </Text>
                          </Space>
                        </List.Item>
                      )}
                      pagination={{ pageSize: 10 }}
                    />
                  </div>
                ) : (
                  <Text type="secondary">
                    未发现明显的来路信息（已搜索{' '}
                    {(approachAnalysis?.search_radius || 0) / 1000} 公里范围）
                  </Text>
                )}
              </Panel>

              <Panel header="AI智能综合分析结果" key="ai">
                {renderAIAnalysisContent()}
              </Panel>
            </Collapse>
          </div>
        )}
      </Spin>
    </Modal>
  )
}

export default AIAnalysisModal
