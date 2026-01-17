import React, { useState, useEffect } from 'react'
import { Table, Card, Empty, Tabs, Alert, Space, Button } from 'antd'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { message } from 'antd'
import {
  TrophyOutlined,
  FireOutlined,
  LinkOutlined,
  InfoCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons'

import { caseApi } from '../../services/cases'
import { systemConfigApi } from '../../services/systemConfig'
import { mapMCPApi } from '../../services/mapMCP'
import type { Case, MapConfig } from '../../types'

import {
  HotspotsPanel,
  SerialCasesPanel,
  GeoCluesPanel,
  LocationInfoModal,
  AIAnalysisModal,
} from './components'
import { useMapUrl, needsApiKey, getProviderDisplayName } from './hooks/useMapUrl'

/**
 * 案件地图视图
 * - 支持同时展示所有案件（多个marker）
 * - 展示地理线索分析（热点、串案等）
 * - 根据地理位置研判案件线索
 */
const CasesMap: React.FC = () => {
  // 数据查询
  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: geoAnalysis } = useQuery({
    queryKey: ['geoAnalysis'],
    queryFn: () => caseApi.getGeographicAnalysis(),
  })

  const { data: hotspots } = useQuery({
    queryKey: ['hotspots'],
    queryFn: () => caseApi.getHotspots(),
  })

  const { data: serialCases } = useQuery({
    queryKey: ['serialCases'],
    queryFn: () => caseApi.getSerialCases(),
  })

  const { data: mapConfig } = useQuery({
    queryKey: ['mapConfig'],
    queryFn: () => systemConfigApi.getMapConfig(),
  })

  // URL 参数和状态
  const [searchParams] = useSearchParams()
  const caseIdFromUrl = searchParams.get('caseId')

  const [selected, setSelected] = useState<Case | null>(null)
  const [mapMode, setMapMode] = useState<'single' | 'all'>('all')
  const [locationInfoModalVisible, setLocationInfoModalVisible] = useState(false)
  const [aiAnalysisModalVisible, setAiAnalysisModalVisible] = useState(false)

  // 地图 URL 生成
  const { generateMapUrl } = useMapUrl(mapConfig as MapConfig | undefined)

  // URL 参数处理：自动定位到指定案件
  useEffect(() => {
    if (caseIdFromUrl && cases) {
      const targetCase = cases.find((c) => c.id === parseInt(caseIdFromUrl))
      if (targetCase && targetCase.latitude != null && targetCase.longitude != null) {
        setSelected(targetCase)
        setMapMode('single')
      }
    }
  }, [caseIdFromUrl, cases])

  // MCP 数据查询
  const { data: locationInfo, isLoading: locationLoading } = useQuery({
    queryKey: ['locationInfo', selected?.id],
    queryFn: () =>
      mapMCPApi.getLocationInfo(selected!.latitude!, selected!.longitude!),
    enabled: !!selected && selected.latitude != null && selected.longitude != null,
  })

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

  // AI 分析
  const aiAnalysisMutation = useMutation({
    mutationFn: (caseId: number) => mapMCPApi.analyzeCaseLocation(caseId),
    onSuccess: () => {
      setAiAnalysisModalVisible(true)
    },
    onError: (error: Error & { response?: { data?: { detail?: string } } }) => {
      message.error(`AI分析失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // 筛选有地理坐标的案件
  const casesWithGeo = (cases || []).filter(
    (c) => c.latitude != null && c.longitude != null
  )

  // 渲染地图
  const renderMap = () => {
    if (casesWithGeo.length === 0) {
      return <Empty description="暂无带经纬度的案件" />
    }

    const provider = (mapConfig as MapConfig)?.provider || 'openstreetmap'
    const apiKey = (mapConfig as MapConfig)?.api_key || ''

    if (needsApiKey(provider) && !apiKey) {
      return (
        <Alert
          message="地图API配置缺失"
          description={
            <div>
              <p>当前选择的地图服务提供商（{provider}）需要API密钥。</p>
              <p>
                请前往 <a href="/settings">系统设置</a> 配置地图API密钥。
              </p>
            </div>
          }
          type="warning"
          showIcon
        />
      )
    }

    const providerName = getProviderDisplayName(provider)

    if (mapMode === 'single') {
      if (!selected || selected.latitude == null || selected.longitude == null) {
        return <Empty description="请选择左侧列表中的案件" />
      }

      const mapUrl = generateMapUrl({ lat: selected.latitude, lng: selected.longitude })

      return (
        <div>
          <Alert message={`当前使用：${providerName}`} type="info" style={{ marginBottom: 8 }} />
          <iframe
            title="案件地图"
            src={mapUrl}
            style={{ width: '100%', height: 600, border: 0 }}
          />
        </div>
      )
    }

    // 全部模式
    const firstCase = casesWithGeo[0]
    if (!firstCase) return <Empty description="无法生成地图" />

    const mapUrl = generateMapUrl({
      lat: firstCase.latitude!,
      lng: firstCase.longitude!,
      allCases: casesWithGeo,
    })

    return (
      <div>
        <Alert
          message={`当前显示 ${casesWithGeo.length} 个案件位置 | 使用：${providerName}`}
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
            description="OpenStreetMap仅显示中心位置和范围。如需查看所有案件标记点，请切换到Mapbox或高德地图。"
            type="info"
            style={{ marginTop: 8 }}
            showIcon
          />
        )}
        <div style={{ marginTop: 8, fontSize: '12px', color: '#666' }}>
          <p>
            共 {casesWithGeo.length} 个案件位置
            {provider !== 'openstreetmap' && '（已在地图上标记）'}
          </p>
        </div>
      </div>
    )
  }

  // 表格列定义
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
      render: (_: unknown, record: Case) =>
        record.latitude != null && record.longitude != null
          ? `${record.latitude.toFixed(6)}, ${record.longitude.toFixed(6)}`
          : '-',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: Case) => (
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
            children: <HotspotsPanel hotspots={(hotspots as { hotspots?: unknown[] })?.hotspots as any} />,
          },
          {
            key: 'serial',
            label: (
              <span>
                <LinkOutlined /> 串案分析
              </span>
            ),
            children: (
              <SerialCasesPanel
                serialCases={(serialCases as { serial_cases?: unknown[] })?.serial_cases as any}
              />
            ),
          },
          {
            key: 'clues',
            label: (
              <span>
                <TrophyOutlined /> 地理线索
              </span>
            ),
            children: <GeoCluesPanel geoAnalysis={geoAnalysis as any} />,
          },
        ]}
      />

      {/* 位置信息模态框 */}
      <LocationInfoModal
        visible={locationInfoModalVisible}
        onClose={() => setLocationInfoModalVisible(false)}
        selectedCase={selected}
        locationInfo={locationInfo as any}
        locationLoading={locationLoading}
        nearbyPOIs={nearbyPOIs as any}
        poisLoading={poisLoading}
      />

      {/* AI分析模态框 */}
      <AIAnalysisModal
        visible={aiAnalysisModalVisible}
        onClose={() => setAiAnalysisModalVisible(false)}
        data={aiAnalysisMutation.data as any}
        loading={aiAnalysisMutation.isPending}
      />
    </div>
  )
}

export default CasesMap
