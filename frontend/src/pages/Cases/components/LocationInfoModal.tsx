import React from 'react'
import { Modal, Card, Descriptions, Spin, Alert, List, Space, Tag, Typography } from 'antd'
import { EnvironmentOutlined } from '@ant-design/icons'
import type { Case } from '../../../types'

const { Text } = Typography

export interface LocationInfo {
  success: boolean
  location?: {
    address?: string
    province?: string
    city?: string
    district?: string
    street?: string
  }
}

export interface NearbyPOI {
  name: string
  type: string
  address: string
  distance: number
  tel?: string
}

export interface NearbyPOIsData {
  success: boolean
  pois?: NearbyPOI[]
}

interface LocationInfoModalProps {
  visible: boolean
  onClose: () => void
  selectedCase: Case | null
  locationInfo?: LocationInfo
  locationLoading: boolean
  nearbyPOIs?: NearbyPOIsData
  poisLoading: boolean
}

/**
 * 位置信息模态框
 * 展示案件的详细位置信息和周边 POI
 */
const LocationInfoModal: React.FC<LocationInfoModalProps> = ({
  visible,
  onClose,
  selectedCase,
  locationInfo,
  locationLoading,
  nearbyPOIs,
  poisLoading,
}) => {
  return (
    <Modal
      title={
        <Space>
          <EnvironmentOutlined />
          <span>案件位置信息（MCP数据）</span>
        </Space>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
    >
      {selectedCase && (
        <div>
          <Card title="案件基本信息" size="small" style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="案件编号">
                {selectedCase.case_number}
              </Descriptions.Item>
              <Descriptions.Item label="发生时间">
                {new Date(selectedCase.occurred_time).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="地点">{selectedCase.location}</Descriptions.Item>
              <Descriptions.Item label="坐标">
                {selectedCase.latitude?.toFixed(6)}, {selectedCase.longitude?.toFixed(6)}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Spin spinning={locationLoading}>
            <Card title="位置详细信息（逆地理编码）" size="small" style={{ marginBottom: 16 }}>
              {locationInfo?.success ? (
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="详细地址">
                    {locationInfo.location?.address || '未知'}
                  </Descriptions.Item>
                  <Descriptions.Item label="省">
                    {locationInfo.location?.province || '未知'}
                  </Descriptions.Item>
                  <Descriptions.Item label="市">
                    {locationInfo.location?.city || '未知'}
                  </Descriptions.Item>
                  <Descriptions.Item label="区/县">
                    {locationInfo.location?.district || '未知'}
                  </Descriptions.Item>
                  <Descriptions.Item label="街道">
                    {locationInfo.location?.street || '未知'}
                  </Descriptions.Item>
                </Descriptions>
              ) : (
                <Alert
                  message="MCP功能未配置"
                  description="位置信息功能需要配置高德地图MCP服务器。当前仅显示基础坐标信息。"
                  type="warning"
                />
              )}
            </Card>
          </Spin>

          <Spin spinning={poisLoading}>
            <Card title="周边关键设施（POI搜索）" size="small" style={{ marginBottom: 16 }}>
              {nearbyPOIs?.success ? (
                nearbyPOIs.pois && nearbyPOIs.pois.length > 0 ? (
                  <List
                    dataSource={nearbyPOIs.pois}
                    renderItem={(poi) => (
                      <List.Item>
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <div>
                            <Text strong>{poi.name}</Text>
                            <Tag style={{ marginLeft: 8 }}>{poi.type}</Tag>
                          </div>
                          <Text type="secondary" style={{ fontSize: '12px' }}>
                            地址：{poi.address} | 距离：{poi.distance} 米
                            {poi.tel && ` | 电话：${poi.tel}`}
                          </Text>
                        </Space>
                      </List.Item>
                    )}
                    pagination={{ pageSize: 5 }}
                  />
                ) : (
                  <Alert message="未发现相关设施" type="info" />
                )
              ) : (
                <Alert
                  message="MCP功能未配置"
                  description="周边设施搜索功能需要配置高德地图MCP服务器。"
                  type="warning"
                />
              )}
            </Card>
          </Spin>

          <Alert
            message="提示"
            description="点击上方的「AI分析」按钮，可以获取更详细的分析，包括：周边村屯、加油站、炼化点、可能的来路等。"
            type="info"
            showIcon
          />
        </div>
      )}
    </Modal>
  )
}

export default LocationInfoModal
