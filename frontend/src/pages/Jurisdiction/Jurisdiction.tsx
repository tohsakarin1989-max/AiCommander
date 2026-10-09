import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  AimOutlined,
  ClusterOutlined,
  EnvironmentOutlined,
  RadarChartOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  jurisdictionApi,
  mapFoundationApi,
  snapshotLayersToAssets,
  type JurisdictionAsset,
  type JurisdictionAssetCreate,
} from '../../services'
import JurisdictionAssetMap from './JurisdictionAssetMap'
import MapDataGovernance from './MapDataGovernance'
import FacilityLookup from '../../components/Facility/FacilityLookup'
import { useAuth } from '../../auth/AuthContext'
import { useRegionalContext } from '../../services/useRegionalContext'
import RegionalControls from '../../components/Facility/RegionalControls'
import { openFacilityDossier } from '../../services/regionalContext'
import { canMaintainArea } from './maintenanceAccess'
import './Jurisdiction.css'

const ASSET_TYPE_LABELS: Record<string, string> = {
  well: '井口',
  station: '站点',
  valve: '阀室',
  storage: '储油点',
  oil_depot: '站库/油库',
  pipeline_node: '管线节点',
  key_location: '重点部位',
  road: '道路/便道',
  path: '小路',
  access_road: '通达道路',
  village: '村屯',
  residential: '居民区',
  settlement: '聚落',
  river: '河流',
  bridge: '桥梁',
  intersection: '路口',
  camera: '监控',
  lighting: '照明',
  alarm: '报警器',
  fence: '围栏',
  checkpoint: '卡口',
  patrol_point: '关注点',
  production_target: '生产目标',
  tech: '技防设施',
  internal_route: '内部便道/临时通道',
  temporary_route: '临时通道',
  abandoned_road: '废弃路',
  risk_route: '盗采高发路线',
  blind_spot: '盲区',
  high_risk_area: '历史高风险点',
}

const SOURCE_LABELS: Record<string, string> = {
  manual: '人工标注',
  map: '地图获取',
  import: '批量导入',
  ledger: '内部台账',
}

type AssetFormValues = JurisdictionAssetCreate

const PUBLIC_MAP_TYPES = new Set([
  'road',
  'path',
  'access_road',
  'village',
  'residential',
  'settlement',
  'river',
  'bridge',
  'intersection',
])

const BUSINESS_ASSET_TYPES = [
  ['well', '井口'],
  ['pipeline_node', '管线节点'],
  ['valve', '阀室'],
  ['station', '站点'],
  ['storage', '储油点'],
  ['oil_depot', '站库/油库'],
  ['key_location', '重点部位'],
  ['production_target', '生产目标'],
]

const DEFENSE_ASSET_TYPES = [
  ['camera', '监控'],
  ['checkpoint', '卡口'],
  ['lighting', '照明'],
  ['alarm', '报警器'],
  ['fence', '围栏'],
  ['tech', '技防设施'],
  ['patrol_point', '巡逻关注点'],
]

const SPECIAL_ROUTE_TYPES = [
  ['internal_route', '内部便道/临时通道'],
  ['temporary_route', '临时通道'],
  ['abandoned_road', '废弃路'],
  ['risk_route', '盗采高发路线'],
  ['blind_spot', '监控/照明盲区'],
  ['high_risk_area', '历史高风险点'],
]

const PUBLIC_REFERENCE_OPTIONS = [
  ['road', '道路/便道'],
  ['village', '村屯'],
  ['bridge', '桥梁'],
  ['intersection', '路口'],
]

function assetLayer(asset: Pick<JurisdictionAsset, 'asset_type' | 'source'>): 'public' | 'business' | 'derived' {
  if (asset.asset_type?.startsWith('derived_')) return 'derived'
  if (PUBLIC_MAP_TYPES.has(asset.asset_type)) return 'public'
  return 'business'
}

function assetLayerLabel(asset: Pick<JurisdictionAsset, 'asset_type' | 'source'>): string {
  const layer = assetLayer(asset)
  if (layer === 'public') return '地图参考'
  if (layer === 'derived') return '研判派生'
  return '业务资产'
}

function assetLayerColor(asset: Pick<JurisdictionAsset, 'asset_type' | 'source'>): string {
  const layer = assetLayer(asset)
  if (layer === 'public') return 'blue'
  if (layer === 'derived') return 'purple'
  return 'gold'
}

function renderAssetTypeOptions(allowPublicManual = false) {
  return (
    <>
      <Select.OptGroup label="油区业务资产">
        {BUSINESS_ASSET_TYPES.map(([value, label]) => (
          <Select.Option key={value} value={value}>{label}</Select.Option>
        ))}
      </Select.OptGroup>
      <Select.OptGroup label="防控设施">
        {DEFENSE_ASSET_TYPES.map(([value, label]) => (
          <Select.Option key={value} value={value}>{label}</Select.Option>
        ))}
      </Select.OptGroup>
      <Select.OptGroup label="内部路线 / 盲区">
        {SPECIAL_ROUTE_TYPES.map(([value, label]) => (
          <Select.Option key={value} value={value}>{label}</Select.Option>
        ))}
      </Select.OptGroup>
      <Select.OptGroup label="公共地图参考">
        {PUBLIC_REFERENCE_OPTIONS.map(([value, label]) => (
          <Select.Option key={value} value={value} disabled={!allowPublicManual}>
            {allowPublicManual ? label : `${label}（从地图导入）`}
          </Select.Option>
        ))}
      </Select.OptGroup>
    </>
  )
}

function typeLabel(type?: string | null): string {
  if (!type) return '未知'
  return ASSET_TYPE_LABELS[type] ?? type
}

function sourceLabel(source?: string | null): string {
  if (!source) return '未知'
  return SOURCE_LABELS[source] ?? source
}

function renderStringList(items?: string[], empty = '暂无数据') {
  if (!items || items.length === 0) return <Empty description={empty} />
  return <List size="small" dataSource={items} renderItem={item => <List.Item>{item}</List.Item>} />
}

const assetColumns: ColumnsType<JurisdictionAsset> = [
  {
    title: '名称',
    dataIndex: 'name',
    render: (value: string, record) => (
      <Space direction="vertical" size={1}>
        <span className="jurisdiction-asset-name">{value}</span>
        <span className="jurisdiction-muted">{record.address || record.description || '暂无说明'}</span>
      </Space>
    ),
  },
  {
    title: '类型',
    dataIndex: 'asset_type',
    width: 120,
    render: (value: string) => <Tag color="gold">{typeLabel(value)}</Tag>,
  },
  {
    title: '数据层',
    width: 110,
    render: (_, record) => <Tag color={assetLayerColor(record)}>{assetLayerLabel(record)}</Tag>,
  },
  {
    title: '来源',
    dataIndex: 'source',
    width: 120,
    render: (value: string) => sourceLabel(value),
  },
  {
    title: '坐标',
    width: 180,
    render: (_, record) => (
      record.latitude != null && record.longitude != null
        ? `${record.latitude.toFixed(5)}, ${record.longitude.toFixed(5)}`
        : '未标注'
    ),
  },
  {
    title: '人工登记等级',
    dataIndex: 'risk_level',
    width: 90,
    render: (value?: number | null) => <Tag>{value == null ? '未登记' : `${value} 级`}</Tag>,
  },
]

export default function Jurisdiction() {
  const { user } = useAuth()
  const regional = useRegionalContext()
  const canManageAssets = regional.ready && canMaintainArea(user?.role, regional.scopes, regional.areaId)
  const canWrite = user?.role === 'admin' || user?.role === 'analyst'
  const [form] = Form.useForm<AssetFormValues>()
  const [editForm] = Form.useForm<AssetFormValues>()
  const queryClient = useQueryClient()
  const activeCaseId = regional.caseId
  const selectedAssetId = regional.assetId
  const setSelectedAssetId = (id: number | null) => regional.update({ assetId: id })
  const [editingAsset, setEditingAsset] = useState<JurisdictionAsset | null>(null)
  const [geoJsonInput, setGeoJsonInput] = useState('')
  const [hiddenAssetTypes, setHiddenAssetTypes] = useState<string[]>([])
  const activeAreaId = regional.ready ? regional.areaId : null
  const setActiveAreaId = (id: number) => regional.update({ operational_area_id: id })
  const [feedbackForm] = Form.useForm<{
    adopted: boolean
    result?: string
    effectiveness_score?: number
    notes?: string
  }>()

  const areaScopesQuery = { data: regional.scopes }

  useEffect(() => {
    setHiddenAssetTypes([])
    setEditingAsset(null)
  }, [activeAreaId])
  useEffect(() => { if (!canManageAssets) setEditingAsset(null) }, [canManageAssets])

  const summaryQuery = useQuery({
    queryKey: ['jurisdiction-summary', activeAreaId],
    queryFn: () => jurisdictionApi.getSummary(activeAreaId as number),
    enabled: activeAreaId != null,
  })

  const assetsQuery = useQuery({
    queryKey: ['jurisdiction-assets', activeAreaId, ...regional.identity],
    queryFn: () => jurisdictionApi.listAssets({
      limit: 200,
      operational_area_id: activeAreaId as number,
    }),
    enabled: activeAreaId != null,
  })

  const snapshotLayersQuery = useQuery({
    queryKey: ['current-map-snapshot-layers', activeAreaId],
    queryFn: () => mapFoundationApi.getCurrentLayers(activeAreaId as number),
    enabled: activeAreaId != null,
    retry: false,
    staleTime: 60_000,
  })

  const effectivenessQuery = useQuery({
    queryKey: ['jurisdiction-effectiveness'],
    queryFn: jurisdictionApi.getEffectiveness,
  })

  const dataQualityQuery = useQuery({
    queryKey: ['jurisdiction-data-quality', activeAreaId],
    queryFn: () => jurisdictionApi.getDataQuality(activeAreaId as number),
    enabled: activeAreaId != null,
  })

  const invalidateJurisdiction = () => {
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-summary'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-assets'] })
    queryClient.invalidateQueries({ queryKey: ['current-map-snapshot-layers'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-data-quality'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-prevention-workbench'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-patrol-plan'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-similar-targets'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-asset-risk-profile'] })
  }

  const createAssetMutation = useMutation({
    mutationFn: (values: AssetFormValues) => {
      if (!canManageAssets || activeAreaId == null) throw new Error('当前厂区没有地图维护权限')
      return jurisdictionApi.createAsset({
      ...values,
      operational_area_id: activeAreaId ?? undefined,
      geometry_type: values.geometry_type ?? 'point',
      source: values.source ?? 'manual',
      status: values.status ?? 'active',
    })},
    onSuccess: () => {
      message.success('辖区要素已录入')
      form.resetFields()
      invalidateJurisdiction()
    },
  })

  const updateAssetMutation = useMutation({
    mutationFn: (values: AssetFormValues) => {
      if (!editingAsset || editingAsset.operational_area_id !== activeAreaId || !canManageAssets) throw new Error('当前要素没有地图维护权限')
      return jurisdictionApi.updateAsset(editingAsset.id, values)
    },
    onSuccess: asset => {
      message.success('辖区要素已更新')
      setEditingAsset(null)
      setSelectedAssetId(asset.id)
      invalidateJurisdiction()
    },
  })

  const deactivateAssetMutation = useMutation({
    mutationFn: (assetId: number) => jurisdictionApi.deactivateAsset(assetId),
    onSuccess: () => {
      message.success('辖区要素已停用')
      setEditingAsset(null)
      setSelectedAssetId(null)
      invalidateJurisdiction()
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: (values: {
      adopted: boolean
      result?: string
      effectiveness_score?: number
      notes?: string
    }) => jurisdictionApi.createFeedback({
      case_id: activeCaseId ?? undefined,
      feedback_type: 'prevention_reference',
      ...values,
    }),
    onSuccess: () => {
      message.success('反馈已回流')
      feedbackForm.resetFields()
      queryClient.invalidateQueries({ queryKey: ['jurisdiction-effectiveness'] })
    },
  })

  const geoJsonImportMutation = useMutation({
    mutationFn: () => {
      const parsed = JSON.parse(geoJsonInput) as Record<string, unknown>
      return jurisdictionApi.importGeoJson(parsed, 'map', activeAreaId ?? undefined)
    },
    onSuccess: result => {
      message.success(`GeoJSON 导入完成：新增 ${result.created}，更新 ${result.updated}`)
      invalidateJurisdiction()
    },
    onError: () => {
      message.error('GeoJSON 解析或导入失败，请检查格式')
    },
  })

  const assets = regional.ready && !assetsQuery.isError ? assetsQuery.data ?? [] : []
  const snapshotAssets = useMemo(
    () => regional.ready && !snapshotLayersQuery.isError && snapshotLayersQuery.data
      ? snapshotLayersToAssets(snapshotLayersQuery.data)
      : [],
    [snapshotLayersQuery.data, snapshotLayersQuery.isError, regional.ready],
  )
  const publishedMapAvailable = regional.ready && !snapshotLayersQuery.isError && Boolean(snapshotLayersQuery.data)
  const displayedAssets = publishedMapAvailable ? snapshotAssets : assets
  const summary = regional.ready && !summaryQuery.isError ? summaryQuery.data : undefined
  const layerCounts = summary?.by_layer ?? {}
  const publicReferenceCount = layerCounts.public_map_reference ?? assets.filter(asset => assetLayer(asset) === 'public').length
  const businessAssetCount = layerCounts.oil_business_asset ?? assets.filter(asset => assetLayer(asset) === 'business').length
  const dataQuality = dataQualityQuery.data
  const availableAssetTypes = useMemo(
    () => Array.from(new Set(displayedAssets.map(asset => asset.asset_type))).sort(),
    [displayedAssets]
  )
  const visibleAssetTypes = availableAssetTypes.filter(type => !hiddenAssetTypes.includes(type))
  const mapAssets = displayedAssets.filter(asset => visibleAssetTypes.includes(asset.asset_type))

  const openEditAsset = (asset: JurisdictionAsset) => {
    setSelectedAssetId(asset.id)
    if (!canManageAssets || asset.operational_area_id !== activeAreaId) return
    setEditingAsset(asset)
    editForm.setFieldsValue({
      external_id: asset.external_id ?? undefined,
      name: asset.name,
      asset_type: asset.asset_type,
      geometry_type: asset.geometry_type ?? 'point',
      latitude: asset.latitude ?? undefined,
      longitude: asset.longitude ?? undefined,
      address: asset.address ?? undefined,
      description: asset.description ?? undefined,
      source: asset.source ?? 'manual',
      status: asset.status ?? 'active',
      risk_level: asset.risk_level ?? undefined,
      confidence_score: asset.confidence_score ?? undefined,
      verified: Boolean(asset.verified),
      tags: asset.tags ?? [],
    })
  }

  return (
    <div className="jurisdiction-page">
      <RegionalControls context={regional} />
      <section className="jurisdiction-hero">
        <div>
          <div className="eyebrow">Jurisdiction Risk Foundation</div>
          <h1>辖区风险底座</h1>
          <p>
            公共地图参考、油区业务资产和研判派生条件分层沉淀，
            用已破案件反推“作案条件”“相似风险点”和“现场薄弱点”。
          </p>
        </div>
        <div className="hero-metric">
          <span>底座完整度</span>
          <strong>{summary?.total ?? 0}</strong>
          <small>个已登记要素</small>
        </div>
      </section>

      <FacilityLookup key={activeAreaId ?? 'none'} areaId={activeAreaId} />
      <MapDataGovernance initialAreaId={activeAreaId ?? undefined} />
      {!canManageAssets && <Alert type="info" message="本厂区地图资料仅由具备维护权限的人员处理；当前仍可查看授权资料与研判" />}

      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="辖区要素" value={summary?.total ?? 0} prefix={<ClusterOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="地图参考" value={publicReferenceCount} prefix={<EnvironmentOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="业务资产" value={businessAssetCount} prefix={<AimOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="当前显示要素" value={displayedAssets.length} prefix={<RadarChartOutlined />} />
          </Card>
        </Col>
      </Row>

      <Card
        title="地图参考与业务资产图层"
        className="jurisdiction-card jurisdiction-map-card"
        extra={(
          <Space>
            {(areaScopesQuery.data?.length ?? 0) > 1 && (
              <Select
                aria-label="当前厂区"
                value={activeAreaId ?? undefined}
                style={{ minWidth: 160 }}
                options={areaScopesQuery.data?.map(scope => ({
                  value: scope.operational_area_id,
                  label: scope.area_name,
                }))}
                onChange={setActiveAreaId}
              />
            )}
            <Tag color={publishedMapAvailable ? 'green' : 'orange'}>
              {publishedMapAvailable
                ? `离线地图 ${snapshotLayersQuery.data?.snapshot_version}`
                : '尚未发布离线地图，临时显示实时数据'}
            </Tag>
            <Tag>{mapAssets.length} / {displayedAssets.length} 个可见</Tag>
          </Space>
        )}
      >
        {snapshotLayersQuery.data?.truncated && (
          <Alert
            type="warning"
            showIcon
            message="当前快照要素较多，页面仅展示前 5000 个"
            description="已发布地图快照本身保持完整；请按图层类型查看或由地图管理员拆分数据范围，避免浏览器一次加载过多要素。"
            style={{ marginBottom: 12 }}
          />
        )}
        <div className="jurisdiction-layer-toolbar">
          <span className="jurisdiction-subtitle">图层</span>
          <Checkbox.Group
            value={visibleAssetTypes}
            options={availableAssetTypes.map(type => ({ label: typeLabel(type), value: type }))}
            onChange={checkedValues => {
              const checked = checkedValues.map(value => String(value))
              setHiddenAssetTypes(availableAssetTypes.filter(type => !checked.includes(type)))
            }}
          />
        </div>
        <JurisdictionAssetMap
          key={activeAreaId ?? 'default-area'}
          assets={mapAssets}
          selectedAssetId={selectedAssetId}
          onAssetClick={asset => openFacilityDossier(asset.id, snapshotLayersQuery.data?.snapshot_id)}
          readOnly={publishedMapAvailable}
          operationalAreaId={activeAreaId ?? undefined}
          snapshotId={snapshotLayersQuery.data?.snapshot_id}
        />
        <div className="jurisdiction-muted jurisdiction-map-hint">
          已发布后，地图固定读取同一离线快照；资产编辑仍在下方台账进行，并在下一次地图发布后生效。
        </div>
      </Card>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} lg={10}>
          <Card title="批准的内部 GIS 参考导入" className="jurisdiction-card">
            <Alert
              type="info"
              showIcon
              message="内网不直接访问公网地图"
              description="公共道路、村屯和水系通过上方受控地图包更新；此处只导入已经批准的内部 GeoJSON 补充数据。"
              style={{ marginBottom: 12 }}
            />
            <div className="jurisdiction-subtitle">内部 GeoJSON 导入</div>
            <Input.TextArea
              rows={7}
              value={geoJsonInput}
              onChange={event => setGeoJsonInput(event.target.value)}
              placeholder='{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"id":"road-001","name":"东侧道路","asset_type":"road"},"geometry":{"type":"LineString","coordinates":[[116.4,39.9],[116.404,39.904]]}}]}'
            />
            <Button
              type="primary"
              style={{ marginTop: 12 }}
              loading={geoJsonImportMutation.isPending}
              disabled={!canManageAssets || !geoJsonInput.trim() || activeAreaId == null}
              onClick={() => geoJsonImportMutation.mutate()}
            >
              导入并去重更新
            </Button>

          </Card>
        </Col>

        <Col xs={24} lg={7}>
          <Card title="底座质量审计" className="jurisdiction-card">
            <Progress
              percent={dataQuality?.coverage_score ?? 0}
              status={(dataQuality?.coverage_score ?? 0) < 60 ? 'exception' : 'active'}
            />
            <Space direction="vertical" size={6} style={{ width: '100%', marginTop: 12 }}>
              <Tag>缺坐标 {dataQuality?.missing_coordinates ?? 0}</Tag>
              <Tag>未校验 {dataQuality?.unverified_count ?? 0}</Tag>
              <Tag>疑似重复 {dataQuality?.duplicate_candidates ?? 0}</Tag>
            </Space>
            <div className="jurisdiction-subtitle" style={{ marginTop: 14 }}>治理建议</div>
            {renderStringList(dataQuality?.recommendations)}
          </Card>
        </Col>

        <Col xs={24} lg={7}>
          <Card title="案件与设施研判" className="jurisdiction-card">
            <p>地图只维护来源与位置。案件依据请在案件工作界面查看；点击设施可打开综合档案。</p>
            <p>旧风险评分与自动经验卡已停用，缺资料不等于没有技防，空间接近不等于涉案。</p>
            <a href={activeCaseId ? `/cases?caseId=${activeCaseId}` : '/cases'}>打开案件工作界面</a>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} xl={10}>
          <Card title="录入油区业务资产" className="jurisdiction-card">
            <Alert
              type="info"
              showIcon
              message="只维护公共地图没有或业务含义特殊的数据"
              description="井点、管线节点、阀室、站库、监控、卡口、盲区、内部便道和盗采高发路线可人工录入；普通道路、村屯建议走地图参考导入。"
              style={{ marginBottom: 16 }}
            />
            <Form
              form={form}
              layout="vertical"
              onFinish={(values) => createAssetMutation.mutate(values)}
              initialValues={{ source: 'manual', geometry_type: 'point', status: 'active' }}
            >
              <Row gutter={12}>
                <Col xs={24} md={12}>
                  <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                    <Input placeholder="例如：南区12号井" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="asset_type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
                    <Select placeholder="选择要素类型">
                      {renderAssetTypeOptions(false)}
                    </Select>
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="latitude" label="纬度">
                    <InputNumber style={{ width: '100%' }} precision={6} placeholder="39.900000" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="longitude" label="经度">
                    <InputNumber style={{ width: '100%' }} precision={6} placeholder="116.400000" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="source" label="来源">
                    <Select>
                      <Select.Option value="manual">人工标注</Select.Option>
                      <Select.Option value="import">批量导入</Select.Option>
                      <Select.Option value="ledger">内部台账</Select.Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="risk_level" label="人工登记等级（可不填）">
                    <InputNumber style={{ width: '100%' }} min={1} max={5} placeholder="未知时留空" />
                  </Form.Item>
                </Col>
                <Col span={24}>
                  <Form.Item name="description" label="说明">
                    <Input.TextArea rows={3} placeholder="记录夜间通行、监控盲区、可停车点等业务事实" />
                  </Form.Item>
                </Col>
              </Row>
              <Button
                type="primary"
                htmlType="submit"
                loading={createAssetMutation.isPending}
                disabled={!canManageAssets || activeAreaId == null}
              >
                录入业务资产
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} xl={14}>
          <Card title="已登记要素" className="jurisdiction-card">
            <Table
              rowKey="id"
              columns={assetColumns}
              dataSource={assets}
              loading={assetsQuery.isLoading}
              pagination={{ pageSize: 8 }}
              rowClassName={record => record.id === selectedAssetId ? 'selected-row' : ''}
              onRow={record => ({
                onClick: () => setSelectedAssetId(record.id),
                onDoubleClick: () => openEditAsset(record),
              })}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} lg={12}>
          <Card title="阶段6 · 建议采纳反馈" className="jurisdiction-card">
            <Row gutter={[16, 16]}>
              <Col xs={24} md={10}>
                <Space direction="vertical" size={8}>
                  <Statistic title="反馈总数" value={effectivenessQuery.data?.total_feedback ?? 0} />
                  <Statistic
                    title="采纳率"
                    value={Math.round((effectivenessQuery.data?.adoption_rate ?? 0) * 100)}
                    suffix="%"
                  />
                  <Statistic
                    title="平均有效性"
                    value={effectivenessQuery.data?.average_effectiveness ?? 0}
                    suffix="/100"
                  />
                </Space>
              </Col>
              <Col xs={24} md={14}>
                <Form
                  form={feedbackForm}
                  layout="vertical"
                  initialValues={{ adopted: true, effectiveness_score: 80 }}
                  onFinish={values => feedbackMutation.mutate(values)}
                >
                  <Form.Item name="adopted" label="是否采纳">
                    <Select>
                      <Select.Option value={true}>已采纳</Select.Option>
                      <Select.Option value={false}>未采纳</Select.Option>
                    </Select>
                  </Form.Item>
                  <Form.Item name="effectiveness_score" label="有效性评分">
                    <InputNumber style={{ width: '100%' }} min={0} max={100} />
                  </Form.Item>
                  <Form.Item name="result" label="采纳情况">
                    <Input.TextArea rows={2} placeholder="例如：纳入关注清单、补充现场核验、补装照明等" />
                  </Form.Item>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={feedbackMutation.isPending}
                    disabled={!canWrite || !activeCaseId}
                  >
                    回流反馈
                  </Button>
                </Form>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      <Modal
        title="编辑辖区要素"
        open={Boolean(editingAsset)}
        onCancel={() => setEditingAsset(null)}
        footer={null}
        destroyOnClose
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={values => updateAssetMutation.mutate(values)}
        >
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="asset_type" label="类型" rules={[{ required: true, message: '请选择类型' }]}>
                <Select disabled>
                  {renderAssetTypeOptions(true)}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="latitude" label="纬度">
                <InputNumber style={{ width: '100%' }} precision={6} disabled={editingAsset?.geometry_type !== 'point'} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="longitude" label="经度">
                <InputNumber style={{ width: '100%' }} precision={6} disabled={editingAsset?.geometry_type !== 'point'} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="source" label="来源">
                <Select>
                  <Select.Option value="manual">人工标注</Select.Option>
                  <Select.Option value="map">地图获取</Select.Option>
                  <Select.Option value="import">批量导入</Select.Option>
                  <Select.Option value="ledger">台账导入</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="risk_level" label="风险等级">
                <InputNumber style={{ width: '100%' }} min={1} max={5} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="verified" label="是否校验">
                <Select>
                  <Select.Option value={true}>已校验</Select.Option>
                  <Select.Option value={false}>未校验</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="tags" label="标签">
                <Select mode="tags" placeholder="例如：重点、夜巡、盲区" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="description" label="说明">
                <Input.TextArea rows={3} />
              </Form.Item>
            </Col>
          </Row>
          <Space>
            <Button type="primary" htmlType="submit" disabled={!canManageAssets} loading={updateAssetMutation.isPending}>
              保存
            </Button>
            <Button onClick={() => setEditingAsset(null)}>取消</Button>
            <Button
              danger
              loading={deactivateAssetMutation.isPending}
              disabled={!canManageAssets || !editingAsset}
              onClick={() => editingAsset && deactivateAssetMutation.mutate(editingAsset.id)}
            >
              停用要素
            </Button>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
