import React, { useState, useMemo, useEffect } from 'react'
import {
  Table,
  Card,
  Empty,
  Tabs,
  Tag,
  Alert,
  List,
  Descriptions,
  Space,
  Button,
  Typography,
  Modal,
  Spin,
  Collapse,
  message,
} from 'antd'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useSearchParams, Link } from 'react-router-dom'
import { caseApi, Case } from '../../services/cases'
import { systemConfigApi } from '../../services/systemConfig'
import { mapMCPApi } from '../../services/mapMCP'
import {
  TrophyOutlined,
  FireOutlined,
  LinkOutlined,
  EnvironmentOutlined,
  RobotOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography
const { Panel } = Collapse

/**
 * 增强的案件地图视图：
 * - 支持同时展示所有案件（多个marker）
 * - 展示地理线索分析（热点、串案等）
 * - 根据地理位置研判案件线索
 */
const CasesMap: React.FC = () => {
  const {
    data: cases,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: geoAnalysis, isLoading: geoLoading } = useQuery({
    queryKey: ['geoAnalysis'],
    queryFn: () => caseApi.getGeographicAnalysis(),
  })

  const { data: hotspots, isLoading: hotspotsLoading } = useQuery({
    queryKey: ['hotspots'],
    queryFn: () => caseApi.getHotspots(),
  })

  const { data: serialCases, isLoading: serialLoading } = useQuery({
    queryKey: ['serialCases'],
    queryFn: () => caseApi.getSerialCases(),
  })

  // 获取地图配置
  const {
    data: mapConfig,
    isLoading: mapConfigLoading,
    isError: mapConfigError,
  } = useQuery({
    queryKey: ['mapConfig'],
    queryFn: () => systemConfigApi.getMapConfig(),
  })

  const [searchParams] = useSearchParams()
  const caseIdFromUrl = searchParams.get('caseId')
  
  const [selected, setSelected] = useState<Case | null>(null)
  const [mapMode, setMapMode] = useState<'single' | 'all'>('all')
  const [locationInfoModalVisible, setLocationInfoModalVisible] = useState(false)
  const [aiAnalysisModalVisible, setAiAnalysisModalVisible] = useState(false)

  // 如果URL中有caseId参数，自动定位到该案件
  useEffect(() => {
    if (caseIdFromUrl && cases) {
      const targetCase = cases.find((c) => c.id === parseInt(caseIdFromUrl))
      if (targetCase && targetCase.latitude != null && targetCase.longitude != null) {
        setSelected(targetCase)
        setMapMode('single')
      }
    }
  }, [caseIdFromUrl, cases])

  // 获取选中案件的位置信息
  const { data: locationInfo, isLoading: locationLoading } = useQuery({
    queryKey: ['locationInfo', selected?.id],
    queryFn: () =>
      mapMCPApi.getLocationInfo(selected!.latitude!, selected!.longitude!),
    enabled: !!selected && selected.latitude != null && selected.longitude != null,
  })

  // 获取选中案件周边的POI
  const { data: nearbyPOIs, isLoading: poisLoading } = useQuery({
    queryKey: ['nearbyPOIs', selected?.id],
    queryFn: () =>
      mapMCPApi.searchNearbyPOIs(
        selected!.latitude!,
        selected!.longitude!,
        '加油站|油库|输油管线|储油设施|化工厂|工厂|企业',
        2000
      ),
    enabled: !!selected && selected.latitude != null && selected.longitude != null,
  })

  // AI分析案件位置
  const aiAnalysisMutation = useMutation({
    mutationFn: (caseId: number) => mapMCPApi.analyzeCaseLocation(caseId),
    onSuccess: () => {
      setAiAnalysisModalVisible(true)
    },
    onError: (error: any) => {
      message.error(`AI分析失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const casesWithGeo = (cases || []).filter(
    (c) => c.latitude != null && c.longitude != null,
  )
  const isMapLoading = isLoading || mapConfigLoading

  // 根据配置生成地图URL（支持多个标记点）
  const generateMapUrl = useMemo(() => {
    return (lat: number, lng: number, allCases?: Case[]) => {
      const provider = mapConfig?.provider || 'openstreetmap'
      const apiKey = mapConfig?.api_key || ''

      if (provider === 'openstreetmap') {
        // OpenStreetMap - 使用 Leaflet 在线地图生成器（支持多个标记）
        if (allCases && allCases.length > 0) {
          // 使用 Leaflet 在线地图生成器，支持多个标记点
          const markers = allCases
            .map((c, i) => `${c.latitude},${c.longitude}`)
            .join(';')
          const lats = allCases.map((c) => c.latitude!)
          const lngs = allCases.map((c) => c.longitude!)
          const minLat = Math.min(...lats)
          const maxLat = Math.max(...lats)
          const minLng = Math.min(...lngs)
          const maxLng = Math.max(...lngs)
          const centerLat = (minLat + maxLat) / 2
          const centerLng = (minLng + maxLng) / 2
          
          // 使用 OpenStreetMap 的 iframe 方式，虽然只能显示一个标记，但可以显示范围
          return `https://www.openstreetmap.org/export/embed.html?bbox=${minLng - 0.01}%2C${
            minLat - 0.01
          }%2C${maxLng + 0.01}%2C${maxLat + 0.01}&layer=mapnik&marker=${centerLat}%2C${centerLng}`
        } else {
          return `https://www.openstreetmap.org/export/embed.html?bbox=${lng - 0.01}%2C${
            lat - 0.01
          }%2C${lng + 0.01}%2C${lat + 0.01}&layer=mapnik&marker=${lat}%2C${lng}`
        }
      } else if (provider === 'mapbox' && apiKey) {
        // Mapbox - 支持多个标记点
        if (allCases && allCases.length > 0) {
          const lats = allCases.map((c) => c.latitude!)
          const lngs = allCases.map((c) => c.longitude!)
          const centerLat = lats.reduce((a, b) => a + b, 0) / lats.length
          const centerLng = lngs.reduce((a, b) => a + b, 0) / lngs.length
          // Mapbox静态地图API - 支持多个标记
          const markers = allCases
            .map((c) => `pin-s+ff0000(${c.longitude},${c.latitude})`)
            .join(',')
          return `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/${markers}/${centerLng},${centerLat},11/800x600?access_token=${apiKey}`
        } else {
          return `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/pin-s+ff0000(${lng},${lat})/${lng},${lat},14/800x600?access_token=${apiKey}`
        }
      } else if (provider === 'amap' && apiKey) {
        // 高德地图 - 支持多个标记点
        if (allCases && allCases.length > 0) {
          const centerLat = allCases.reduce((sum, c) => sum + (c.latitude || 0), 0) / allCases.length
          const centerLng = allCases.reduce((sum, c) => sum + (c.longitude || 0), 0) / allCases.length
          // 高德地图支持多个标记，格式：lng,lat;lng,lat
          const markers = allCases
            .map((c) => `${c.longitude},${c.latitude}`)
            .join(';')
          return `https://webapi.amap.com/maps?v=1.4.15&key=${apiKey}&center=${centerLng},${centerLat}&markers=${markers}&zoom=12`
        } else {
          return `https://webapi.amap.com/maps?v=1.4.15&key=${apiKey}&center=${lng},${lat}&markers=${lng},${lat}&zoom=14`
        }
      } else if (provider === 'baidu' && apiKey) {
        // 百度地图 - 支持多个标记点
        if (allCases && allCases.length > 0) {
          const centerLat = allCases.reduce((sum, c) => sum + (c.latitude || 0), 0) / allCases.length
          const centerLng = allCases.reduce((sum, c) => sum + (c.longitude || 0), 0) / allCases.length
          // 百度地图多个标记格式：lng,lat|label;lng,lat|label
          const markers = allCases
            .map((c, i) => `${c.longitude},${c.latitude}|${i + 1}`)
            .join(';')
          return `https://api.map.baidu.com/staticimage/v2?ak=${apiKey}&center=${centerLng},${centerLat}&width=800&height=600&zoom=12&markers=${markers}`
        } else {
          return `https://api.map.baidu.com/staticimage/v2?ak=${apiKey}&center=${lng},${lat}&width=800&height=600&zoom=14&markers=${lng},${lat}`
        }
      } else {
        // 默认使用OpenStreetMap
        return `https://www.openstreetmap.org/export/embed.html?bbox=${lng - 0.01}%2C${
          lat - 0.01
        }%2C${lng + 0.01}%2C${lat + 0.01}&layer=mapnik&marker=${lat}%2C${lng}`
      }
    }
  }, [mapConfig])

  const renderMap = () => {
    if (isMapLoading) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <Spin tip="加载地图数据中..." />
        </div>
      )
    }

    if (mapConfigError) {
      return (
        <Alert
          message="地图配置加载失败"
          description="请检查系统设置中的地图配置或稍后重试。"
          type="warning"
          showIcon
        />
      )
    }

    if (casesWithGeo.length === 0) {
      return <Empty description="暂无带经纬度的案件" />
    }

    // 检查地图配置
    const provider = mapConfig?.provider || 'openstreetmap'
    const apiKey = mapConfig?.api_key || ''
    const needsApiKey = ['mapbox', 'amap', 'baidu'].includes(provider)

    if (needsApiKey && !apiKey) {
      return (
        <Alert
          message="地图API配置缺失"
          description={
            <div>
              <p>当前选择的地图服务提供商（{provider}）需要API密钥。</p>
              <p>
                请前往 <Link to="/settings">系统设置</Link> 配置地图API密钥。
              </p>
            </div>
          }
          type="warning"
          showIcon
        />
      )
    }

    if (mapMode === 'single') {
      if (!selected || selected.latitude == null || selected.longitude == null) {
        return <Empty description="请选择左侧列表中的案件" />
      }

      const mapUrl = generateMapUrl(selected.latitude, selected.longitude)

      return (
        <div>
          <Alert
            message={`当前使用：${provider === 'openstreetmap' ? 'OpenStreetMap' : provider.toUpperCase()}`}
            type="info"
            style={{ marginBottom: 8 }}
          />
          <iframe
            title="案件地图"
            src={mapUrl}
            style={{ width: '100%', height: 600, border: 0 }}
          />
        </div>
      )
    } else {
      // 显示所有案件
      const firstCase = casesWithGeo[0]
      if (!firstCase) return <Empty description="无法生成地图" />

      const mapUrl = generateMapUrl(
        firstCase.latitude!,
        firstCase.longitude!,
        casesWithGeo
      )

      return (
        <div>
          <Alert
            message={`当前显示 ${casesWithGeo.length} 个案件位置 | 使用：${provider === 'openstreetmap' ? 'OpenStreetMap' : provider.toUpperCase()}`}
            type="info"
            style={{ marginBottom: 8 }}
          />
          {provider === 'amap' || provider === 'baidu' ? (
            <img
              src={mapUrl}
              alt="案件地图"
              style={{ width: '100%', height: 600, objectFit: 'contain' }}
            />
          ) : (
            <iframe
              title="案件地图（全部）"
              src={mapUrl}
              style={{ width: '100%', height: 600, border: 0 }}
            />
          )}
          {provider === 'openstreetmap' && casesWithGeo.length > 1 && (
            <Alert
              message="提示"
              description="OpenStreetMap仅显示中心位置和范围。如需查看所有案件标记点，请切换到Mapbox或高德地图（需要在系统设置中配置API密钥）。"
              type="info"
              style={{ marginTop: 8 }}
              showIcon
            />
          )}
          {casesWithGeo.length > 0 && (
            <div style={{ marginTop: 8, fontSize: '12px', color: '#666' }}>
              <p>
                共 {casesWithGeo.length} 个案件位置
                {provider !== 'openstreetmap' && '（已在地图上标记）'}
              </p>
            </div>
          )}
        </div>
      )
    }
  }

  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
    },
    {
      title: '时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      render: (time: string) => new Date(time).toLocaleDateString(),
    },
    {
      title: '坐标',
      key: 'coordinates',
      render: (_: any, record: Case) =>
        record.latitude != null && record.longitude != null
          ? `${record.latitude.toFixed(6)}, ${record.longitude.toFixed(6)}`
          : '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Case) => (
        <Space>
          {record.latitude != null && record.longitude != null && (
            <>
              <Button
                type="link"
                size="small"
                icon={<InfoCircleOutlined />}
                onClick={() => {
                  setSelected(record)
                  setLocationInfoModalVisible(true)
                }}
              >
                位置信息
              </Button>
              <Button
                type="link"
                size="small"
                icon={<RobotOutlined />}
                onClick={() => aiAnalysisMutation.mutate(record.id)}
                loading={aiAnalysisMutation.isPending}
              >
                AI分析
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <h2>案件地图与地理线索研判</h2>
      <p style={{ marginBottom: 16 }}>
        根据经纬度定位案件位置，通过地图展示发案情况，并根据地理位置研判可能的案件线索。
      </p>
      {isError && (
        <Alert
          message="案件数据加载失败"
          description={error instanceof Error ? error.message : '请检查网络或稍后重试'}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      <Tabs
        defaultActiveKey="map"
        items={[
          {
            key: 'map',
            label: '地图视图',
            children: (
              <div style={{ display: 'flex', gap: 16 }}>
                <div style={{ flex: '0 0 400px' }}>
                  <Card
                    title="案件列表"
                    extra={
                      <Space>
                        <Button
                          size="small"
                          type={mapMode === 'single' ? 'primary' : 'default'}
                          onClick={() => setMapMode('single')}
                        >
                          单个
                        </Button>
                        <Button
                          size="small"
                          type={mapMode === 'all' ? 'primary' : 'default'}
                          onClick={() => setMapMode('all')}
                        >
                          全部
                        </Button>
                      </Space>
                    }
                  >
                    <Table
                      columns={columns}
                      dataSource={casesWithGeo}
                      loading={isLoading}
                      rowKey="id"
                      size="small"
                      pagination={{ pageSize: 10 }}
                      onRow={(record) => ({
                        onClick: () => {
                          setSelected(record)
                          setMapMode('single')
                        },
                      })}
                      rowClassName={(record) =>
                        selected && record.id === selected.id ? 'ant-table-row-selected' : ''
                      }
                    />
                  </Card>
                </div>
                <div style={{ flex: 1 }}>
                  <Card title="地图位置">{renderMap()}</Card>
                </div>
              </div>
            ),
          },
          {
            key: 'hotspots',
            label: (
              <span>
                <FireOutlined /> 热点区域
              </span>
            ),
            children: (
              <Spin spinning={hotspotsLoading} tip="加载热点数据中...">
                <div>
                  {hotspots?.hotspots && hotspots.hotspots.length > 0 ? (
                    <List
                      dataSource={hotspots.hotspots}
                      renderItem={(hotspot: any) => (
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
                                {hotspot.cases.slice(0, 5).map((c: any) => (
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
                  ) : (
                    <Empty description="暂无热点区域" />
                  )}
                </div>
              </Spin>
            ),
          },
          {
            key: 'serial',
            label: (
              <span>
                <LinkOutlined /> 串案分析
              </span>
            ),
            children: (
              <Spin spinning={serialLoading} tip="加载串案分析中...">
                <div>
                  {serialCases?.serial_cases && serialCases.serial_cases.length > 0 ? (
                    <List
                      dataSource={serialCases.serial_cases}
                      renderItem={(group: any) => (
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
                                  {group.cases.map((c: any) => (
                                    <Tag key={c.id}>{c.case_number}</Tag>
                                  ))}
                                </Space>
                              </div>
                              {group.analysis.suggestions.length > 0 && (
                                <Alert
                                  message="研判建议"
                                  description={
                                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                                      {group.analysis.suggestions.map((s: string, idx: number) => (
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
                  ) : (
                    <Empty description="暂无串案" />
                  )}
                </div>
              </Spin>
            ),
          },
          {
            key: 'clues',
            label: (
              <span>
                <TrophyOutlined /> 地理线索
              </span>
            ),
            children: (
              <Spin spinning={geoLoading} tip="加载地理线索中...">
                <div>
                  {geoAnalysis?.clues && geoAnalysis.clues.length > 0 ? (
                    <Space direction="vertical" style={{ width: '100%' }} size="large">
                      {geoAnalysis.clues.map((clue: any, idx: number) => (
                        <Card key={idx} title={clue.title}>
                          <Paragraph>{clue.description}</Paragraph>
                          {clue.suggestions && (
                            <Alert
                              message="研判建议"
                              description={
                                <ul style={{ margin: 0, paddingLeft: 20 }}>
                                  {clue.suggestions.map((s: string, i: number) => (
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
                            renderItem={(item: string) => <List.Item>{item}</List.Item>}
                          />
                        </Card>
                      )}
                    </Space>
                  ) : (
                    <Empty description="暂无地理线索" />
                  )}
                </div>
              </Spin>
            ),
          },
        ]}
      />

      {/* 位置信息模态框 */}
      <Modal
        title={
          <Space>
            <EnvironmentOutlined />
            <span>案件位置信息（MCP数据）</span>
          </Space>
        }
        open={locationInfoModalVisible}
        onCancel={() => setLocationInfoModalVisible(false)}
        footer={null}
        width={800}
      >
        {selected && (
          <div>
            <Card title="案件基本信息" size="small" style={{ marginBottom: 16 }}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="案件编号">
                  {selected.case_number}
                </Descriptions.Item>
                <Descriptions.Item label="发生时间">
                  {new Date(selected.occurred_time).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="地点">{selected.location}</Descriptions.Item>
                <Descriptions.Item label="坐标">
                  {selected.latitude?.toFixed(6)}, {selected.longitude?.toFixed(6)}
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
                      renderItem={(poi: any) => (
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

      {/* AI分析模态框 */}
      <Modal
        title={
          <Space>
            <RobotOutlined />
            <span>AI智能位置分析（结合MCP数据）</span>
          </Space>
        }
        open={aiAnalysisModalVisible}
        onCancel={() => setAiAnalysisModalVisible(false)}
        footer={null}
        width={900}
      >
        <Spin spinning={aiAnalysisMutation.isPending}>
          {aiAnalysisMutation.data && (
            <div>
              <Alert
                message="分析说明"
                description="以下分析结果结合了案件信息、地图MCP数据（位置、周边村屯、加油站、炼化点、路口、天气等）和AI智能分析。"
                type="info"
                style={{ marginBottom: 16 }}
              />

              <Collapse defaultActiveKey={['location', 'villages', 'gas', 'refineries', 'routes', 'ai']}>
                <Panel header="位置信息" key="location">
                  <Descriptions column={2} size="small" bordered>
                    <Descriptions.Item label="详细地址">
                      {aiAnalysisMutation.data.location_info?.location?.address || '未知'}
                    </Descriptions.Item>
                    <Descriptions.Item label="行政区划">
                      {aiAnalysisMutation.data.location_info?.location?.province || ''}{' '}
                      {aiAnalysisMutation.data.location_info?.location?.city || ''}{' '}
                      {aiAnalysisMutation.data.location_info?.location?.district || ''}
                    </Descriptions.Item>
                    <Descriptions.Item label="街道">
                      {aiAnalysisMutation.data.location_info?.location?.street || '未知'}
                    </Descriptions.Item>
                  </Descriptions>
                </Panel>

                <Panel
                  header={`周边村屯/社区（${aiAnalysisMutation.data.comprehensive_data?.villages?.count || 0} 个，搜索范围：${(aiAnalysisMutation.data.comprehensive_data?.search_stats?.villages_radius || 0) / 1000} 公里）`}
                  key="villages"
                >
                  {aiAnalysisMutation.data.comprehensive_data?.search_stats?.is_remote_area && (
                    <Alert
                      message="偏远地区"
                      description="该地区人烟稀少，已自动扩大搜索范围以查找更多村屯信息。"
                      type="warning"
                      style={{ marginBottom: 12 }}
                      showIcon
                    />
                  )}
                  {aiAnalysisMutation.data.comprehensive_data?.villages?.pois &&
                  aiAnalysisMutation.data.comprehensive_data.villages.pois.length > 0 ? (
                    <List
                      dataSource={aiAnalysisMutation.data.comprehensive_data.villages.pois}
                      renderItem={(poi: any) => (
                        <List.Item>
                          <Space>
                            <Text strong>{poi.name}</Text>
                            <Tag color="blue">{poi.type}</Tag>
                            <Text type="secondary">
                              距离 {(poi.distance / 1000).toFixed(1)} 公里 | {poi.address}
                            </Text>
                          </Space>
                        </List.Item>
                      )}
                      pagination={{ pageSize: 10 }}
                    />
                  ) : (
                    <Text type="secondary">未发现村屯/社区（已搜索 {(aiAnalysisMutation.data.comprehensive_data?.search_stats?.villages_radius || 0) / 1000} 公里范围）</Text>
                  )}
                </Panel>

                <Panel
                  header={`周边加油站（${aiAnalysisMutation.data.comprehensive_data?.gas_stations?.count || 0} 个，搜索范围：${(aiAnalysisMutation.data.comprehensive_data?.search_stats?.gas_stations_radius || 0) / 1000} 公里）`}
                  key="gas"
                >
                  {aiAnalysisMutation.data.comprehensive_data?.gas_stations?.pois &&
                  aiAnalysisMutation.data.comprehensive_data.gas_stations.pois.length > 0 ? (
                    <List
                      dataSource={aiAnalysisMutation.data.comprehensive_data.gas_stations.pois.slice(0, 10)}
                      renderItem={(poi: any) => (
                        <List.Item>
                          <Space direction="vertical" style={{ width: '100%' }}>
                            <div>
                              <Text strong>{poi.name}</Text>
                              <Tag color="orange" style={{ marginLeft: 8 }}>{poi.type}</Tag>
                            </div>
                            <Text type="secondary" style={{ fontSize: '12px' }}>
                              距离 {(poi.distance / 1000).toFixed(1)} 公里 | {poi.address}
                              {poi.tel && ` | 电话：${poi.tel}`}
                            </Text>
                          </Space>
                        </List.Item>
                      )}
                      pagination={{ pageSize: 5 }}
                    />
                  ) : (
                    <Text type="secondary">未发现加油站</Text>
                  )}
                </Panel>

                <Panel
                  header={`周边炼化点/储油设施（${aiAnalysisMutation.data.comprehensive_data?.refineries?.count || 0} 个，搜索范围：${(aiAnalysisMutation.data.comprehensive_data?.search_stats?.refineries_radius || 0) / 1000} 公里）`}
                  key="refineries"
                >
                  {aiAnalysisMutation.data.comprehensive_data?.refineries?.pois &&
                  aiAnalysisMutation.data.comprehensive_data.refineries.pois.length > 0 ? (
                    <List
                      dataSource={aiAnalysisMutation.data.comprehensive_data.refineries.pois.slice(0, 10)}
                      renderItem={(poi: any) => (
                        <List.Item>
                          <Space>
                            <Text strong>{poi.name}</Text>
                            <Tag color="red">{poi.type}</Tag>
                            <Text type="secondary">
                              距离 {(poi.distance / 1000).toFixed(1)} 公里 | {poi.address}
                            </Text>
                          </Space>
                        </List.Item>
                      )}
                      pagination={{ pageSize: 5 }}
                    />
                  ) : (
                    <Text type="secondary">未发现炼化点/储油设施</Text>
                  )}
                </Panel>

                <Panel
                  header={`可能的来路分析（${aiAnalysisMutation.data.approach_analysis?.approach_analysis?.possible_approaches?.length || 0} 条，搜索范围：${(aiAnalysisMutation.data.approach_analysis?.search_radius || 0) / 1000} 公里）`}
                  key="routes"
                >
                  {aiAnalysisMutation.data.approach_analysis?.approach_analysis?.possible_approaches &&
                  aiAnalysisMutation.data.approach_analysis.approach_analysis.possible_approaches.length > 0 ? (
                    <div>
                      <Alert
                        message="来路分析"
                        description={`基于周边路口和道路，在 ${(aiAnalysisMutation.data.approach_analysis.search_radius || 0) / 1000} 公里范围内分析可能的来路方向`}
                        type="info"
                        style={{ marginBottom: 12 }}
                      />
                      <List
                        dataSource={aiAnalysisMutation.data.approach_analysis.approach_analysis.possible_approaches}
                        renderItem={(route: any, index: number) => (
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
                                距离案发地点 {(route.distance / 1000).toFixed(1)} 公里 | {route.address}
                              </Text>
                            </Space>
                          </List.Item>
                        )}
                        pagination={{ pageSize: 10 }}
                      />
                    </div>
                  ) : (
                    <Text type="secondary">未发现明显的来路信息（已搜索 {(aiAnalysisMutation.data.approach_analysis?.search_radius || 0) / 1000} 公里范围）</Text>
                  )}
                </Panel>

                <Panel header="AI智能综合分析结果" key="ai">
                  {aiAnalysisMutation.data.ai_analysis ? (
                    <div>
                      {typeof aiAnalysisMutation.data.ai_analysis === 'string' ? (
                        <Paragraph>{aiAnalysisMutation.data.ai_analysis}</Paragraph>
                      ) : aiAnalysisMutation.data.ai_analysis.geographic_features ? (
                        <div>
                          <Card title="地理位置特征" size="small" style={{ marginBottom: 12 }}>
                            <Paragraph>{aiAnalysisMutation.data.ai_analysis.geographic_features}</Paragraph>
                          </Card>
                          <Card title="周边村屯分析" size="small" style={{ marginBottom: 12 }}>
                            <Paragraph>{aiAnalysisMutation.data.ai_analysis.villages_analysis}</Paragraph>
                          </Card>
                          <Card title="加油站分析" size="small" style={{ marginBottom: 12 }}>
                            <Paragraph>{aiAnalysisMutation.data.ai_analysis.gas_stations_analysis}</Paragraph>
                          </Card>
                          <Card title="炼化点分析" size="small" style={{ marginBottom: 12 }}>
                            <Paragraph>{aiAnalysisMutation.data.ai_analysis.refineries_analysis}</Paragraph>
                          </Card>
                          {aiAnalysisMutation.data.ai_analysis.approach_routes && (
                            <Card title="可能的来路" size="small" style={{ marginBottom: 12 }}>
                              <List
                                dataSource={aiAnalysisMutation.data.ai_analysis.approach_routes}
                                renderItem={(route: string) => (
                                  <List.Item>
                                    <Text>• {route}</Text>
                                  </List.Item>
                                )}
                              />
                            </Card>
                          )}
                          <Card title="风险评估" size="small" style={{ marginBottom: 12 }}>
                            <Paragraph>{aiAnalysisMutation.data.ai_analysis.risk_assessment}</Paragraph>
                          </Card>
                          {aiAnalysisMutation.data.ai_analysis.prevention_suggestions && (
                            <Card title="防控建议" size="small">
                              <List
                                dataSource={aiAnalysisMutation.data.ai_analysis.prevention_suggestions}
                                renderItem={(suggestion: string) => (
                                  <List.Item>
                                    <Text>• {suggestion}</Text>
                                  </List.Item>
                                )}
                              />
                            </Card>
                          )}
                        </div>
                      ) : (
                        <pre style={{ whiteSpace: 'pre-wrap', fontSize: '12px' }}>
                          {JSON.stringify(aiAnalysisMutation.data.ai_analysis, null, 2)}
                        </pre>
                      )}
                    </div>
                  ) : (
                    <Text type="secondary">分析结果解析中...</Text>
                  )}
                </Panel>
              </Collapse>
            </div>
          )}
        </Spin>
      </Modal>
    </div>
  )
}

export default CasesMap
