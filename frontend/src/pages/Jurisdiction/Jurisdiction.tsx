import { useMemo, useState } from 'react'
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
  Spin,
  Statistic,
  Table,
  Tag,
  Upload,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  AimOutlined,
  ClusterOutlined,
  EnvironmentOutlined,
  RadarChartOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  jurisdictionApi,
  type CaseRiskContext,
  type JurisdictionAsset,
  type JurisdictionAssetCreate,
  type JurisdictionDistance,
  type PatrolPlan,
} from '../../services'
import JurisdictionAssetMap from './JurisdictionAssetMap'
import './Jurisdiction.css'

const ASSET_TYPE_LABELS: Record<string, string> = {
  well: '井口',
  station: '站点',
  valve: '阀室',
  storage: '储油点',
  road: '道路/便道',
  village: '村屯',
  camera: '监控',
  lighting: '照明',
  checkpoint: '卡口',
  patrol_point: '关注点',
  production_target: '生产目标',
  tech: '技防设施',
}

const SOURCE_LABELS: Record<string, string> = {
  manual: '人工标注',
  map: '地图获取',
  import: '批量导入',
}

type AssetFormValues = JurisdictionAssetCreate

function typeLabel(type?: string | null): string {
  if (!type) return '未知'
  return ASSET_TYPE_LABELS[type] ?? type
}

function sourceLabel(source?: string | null): string {
  if (!source) return '未知'
  return SOURCE_LABELS[source] ?? source
}

function nearestEntries(context?: CaseRiskContext): Array<[string, JurisdictionDistance]> {
  if (!context) return []
  return Object.entries(context.nearest).filter(
    (entry): entry is [string, JurisdictionDistance] => Boolean(entry[1])
  )
}

function renderStringList(items?: string[], empty = '暂无数据') {
  if (!items || items.length === 0) return <Empty description={empty} />
  return (
    <List
      size="small"
      dataSource={items}
      renderItem={item => <List.Item>{item}</List.Item>}
    />
  )
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
    title: '风险',
    dataIndex: 'risk_level',
    width: 90,
    render: (value?: number | null) => <Tag>{value ?? 1} 级</Tag>,
  },
]

export default function Jurisdiction() {
  const [form] = Form.useForm<AssetFormValues>()
  const [editForm] = Form.useForm<AssetFormValues>()
  const queryClient = useQueryClient()
  const [caseIdInput, setCaseIdInput] = useState<number | null>(null)
  const [activeCaseId, setActiveCaseId] = useState<number | null>(null)
  const [selectedAssetId, setSelectedAssetId] = useState<number | null>(null)
  const [editingAsset, setEditingAsset] = useState<JurisdictionAsset | null>(null)
  const [geoJsonInput, setGeoJsonInput] = useState('')
  const [hiddenAssetTypes, setHiddenAssetTypes] = useState<string[]>([])
  const [selectedTableFile, setSelectedTableFile] = useState<File | null>(null)
  const [tableImportPreview, setTableImportPreview] = useState<{
    total: number
    valid: number
    created: number
    updated: number
    errors: Array<{ row: number; error: string }>
  } | null>(null)
  const [feedbackForm] = Form.useForm<{
    adopted: boolean
    result?: string
    effectiveness_score?: number
    notes?: string
  }>()

  const summaryQuery = useQuery({
    queryKey: ['jurisdiction-summary'],
    queryFn: jurisdictionApi.getSummary,
  })

  const assetsQuery = useQuery({
    queryKey: ['jurisdiction-assets'],
    queryFn: () => jurisdictionApi.listAssets({ limit: 200 }),
  })

  const contextQuery = useQuery({
    queryKey: ['jurisdiction-risk-context', activeCaseId],
    queryFn: () => jurisdictionApi.getCaseRiskContext(activeCaseId as number),
    enabled: activeCaseId != null,
  })

  const similarQuery = useQuery({
    queryKey: ['jurisdiction-similar-targets', activeCaseId],
    queryFn: () => jurisdictionApi.getSimilarTargets(activeCaseId as number, 8),
    enabled: activeCaseId != null,
  })

  const experienceQuery = useQuery({
    queryKey: ['jurisdiction-experience-card', activeCaseId],
    queryFn: () => jurisdictionApi.getCaseExperienceCard(activeCaseId as number),
    enabled: activeCaseId != null,
  })

  const assetProfileQuery = useQuery({
    queryKey: ['jurisdiction-asset-risk-profile', selectedAssetId],
    queryFn: () => jurisdictionApi.getAssetRiskProfile(selectedAssetId as number),
    enabled: selectedAssetId != null,
  })

  const patrolPlanQuery = useQuery<PatrolPlan>({
    queryKey: ['jurisdiction-patrol-plan', activeCaseId],
    queryFn: () => jurisdictionApi.createPatrolPlan({ case_id: activeCaseId as number, limit: 6 }),
    enabled: activeCaseId != null,
  })

  const briefingQuery = useQuery({
    queryKey: ['jurisdiction-roundtable-briefing', activeCaseId],
    queryFn: () => jurisdictionApi.getRoundtableBriefing(activeCaseId as number),
    enabled: activeCaseId != null,
  })

  const effectivenessQuery = useQuery({
    queryKey: ['jurisdiction-effectiveness'],
    queryFn: jurisdictionApi.getEffectiveness,
  })

  const dataQualityQuery = useQuery({
    queryKey: ['jurisdiction-data-quality'],
    queryFn: jurisdictionApi.getDataQuality,
  })

  const workbenchQuery = useQuery({
    queryKey: ['jurisdiction-prevention-workbench', activeCaseId],
    queryFn: () => jurisdictionApi.getPreventionWorkbench(activeCaseId ?? undefined),
  })

  const invalidateJurisdiction = () => {
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-summary'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-assets'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-data-quality'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-prevention-workbench'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-patrol-plan'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-similar-targets'] })
    queryClient.invalidateQueries({ queryKey: ['jurisdiction-asset-risk-profile'] })
  }

  const createAssetMutation = useMutation({
    mutationFn: (values: AssetFormValues) => jurisdictionApi.createAsset({
      ...values,
      geometry_type: values.geometry_type ?? 'point',
      source: values.source ?? 'manual',
      status: values.status ?? 'active',
      risk_level: values.risk_level ?? 1,
    }),
    onSuccess: () => {
      message.success('辖区要素已录入')
      form.resetFields()
      invalidateJurisdiction()
    },
  })

  const updateAssetMutation = useMutation({
    mutationFn: (values: AssetFormValues) => {
      if (!editingAsset) throw new Error('未选择要素')
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
      return jurisdictionApi.importGeoJson(parsed, 'map')
    },
    onSuccess: result => {
      message.success(`GeoJSON 导入完成：新增 ${result.created}，更新 ${result.updated}`)
      invalidateJurisdiction()
    },
    onError: () => {
      message.error('GeoJSON 解析或导入失败，请检查格式')
    },
  })

  const tablePreviewMutation = useMutation({
    mutationFn: (file: File) => jurisdictionApi.importAssetTable(file, true),
    onSuccess: result => {
      setTableImportPreview(result)
      message.success(`台账预览完成：有效 ${result.valid} / ${result.total}`)
    },
    onError: () => {
      setTableImportPreview(null)
      message.error('台账文件解析失败，请检查表头和文件格式')
    },
  })

  const tableImportMutation = useMutation({
    mutationFn: (file: File) => jurisdictionApi.importAssetTable(file, false),
    onSuccess: result => {
      message.success(`台账导入完成：新增 ${result.created}，更新 ${result.updated}`)
      setSelectedTableFile(null)
      setTableImportPreview(null)
      invalidateJurisdiction()
    },
  })

  const context = contextQuery.data
  const assets = assetsQuery.data ?? []
  const summary = summaryQuery.data
  const byType = summary?.by_type ?? {}
  const mapCount = summary?.by_source?.map ?? 0
  const manualCount = summary?.by_source?.manual ?? 0
  const dataQuality = dataQualityQuery.data
  const workbench = workbenchQuery.data
  const availableAssetTypes = useMemo(
    () => Array.from(new Set(assets.map(asset => asset.asset_type))).sort(),
    [assets]
  )
  const visibleAssetTypes = availableAssetTypes.filter(type => !hiddenAssetTypes.includes(type))
  const mapAssets = assets.filter(asset => visibleAssetTypes.includes(asset.asset_type))

  const openEditAsset = (asset: JurisdictionAsset) => {
    setSelectedAssetId(asset.id)
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
      risk_level: asset.risk_level ?? 1,
      confidence_score: asset.confidence_score ?? 1,
      verified: Boolean(asset.verified),
      tags: asset.tags ?? [],
    })
  }

  const runCaseAnalysis = () => {
    if (!caseIdInput) {
      message.warning('请输入案件 ID')
      return
    }
    setActiveCaseId(caseIdInput)
  }

  return (
    <div className="jurisdiction-page">
      <section className="jurisdiction-hero">
        <div>
          <div className="eyebrow">Jurisdiction Risk Foundation</div>
          <h1>辖区风险底座</h1>
          <p>
            把地图获取的道路、村屯和人工补充的井口、技防、重点区域统一沉淀为辖区环境要素，
            让已破案件可以反推出“相似条件”和“现场薄弱点”。
          </p>
        </div>
        <div className="hero-metric">
          <span>底座完整度</span>
          <strong>{summary?.total ?? 0}</strong>
          <small>个已登记要素</small>
        </div>
      </section>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="辖区要素" value={summary?.total ?? 0} prefix={<ClusterOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="地图来源" value={mapCount} prefix={<EnvironmentOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="人工标注" value={manualCount} prefix={<AimOutlined />} />
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card className="jurisdiction-card">
            <Statistic title="生产目标" value={(byType.well ?? 0) + (byType.station ?? 0) + (byType.storage ?? 0)} prefix={<RadarChartOutlined />} />
          </Card>
        </Col>
      </Row>

      <Card
        title="地图图层管理 · 可视化维护辖区底座"
        className="jurisdiction-card jurisdiction-map-card"
        extra={<Tag>{mapAssets.length} / {assets.length} 个可见</Tag>}
      >
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
          assets={mapAssets}
          selectedAssetId={selectedAssetId}
          onAssetClick={openEditAsset}
        />
        <div className="jurisdiction-muted jurisdiction-map-hint">
          点击地图上的点、线、面要素可打开编辑；无坐标要素仍可在下方表格双击维护。
        </div>
      </Card>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} lg={10}>
          <Card title="生产化导入 · GeoJSON / 地图底座" className="jurisdiction-card">
            <Alert
              type="warning"
              showIcon
              message="完整功能要求先把底座数据导进来"
              description="支持 FeatureCollection；Point/LineString/Polygon 会自动计算中心点，按 properties.id/external_id 去重更新。"
              style={{ marginBottom: 12 }}
            />
            <Input.TextArea
              rows={7}
              value={geoJsonInput}
              onChange={event => setGeoJsonInput(event.target.value)}
              placeholder='{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"id":"road-001","name":"东侧便道","asset_type":"road"},"geometry":{"type":"LineString","coordinates":[[116.4,39.9],[116.404,39.904]]}}]}'
            />
            <Button
              type="primary"
              style={{ marginTop: 12 }}
              loading={geoJsonImportMutation.isPending}
              disabled={!geoJsonInput.trim()}
              onClick={() => geoJsonImportMutation.mutate()}
            >
              导入并去重更新
            </Button>

            <div className="jurisdiction-import-divider" />
            <div className="jurisdiction-subtitle">CSV / Excel 台账导入</div>
            <Upload.Dragger
              multiple={false}
              showUploadList={false}
              disabled={tablePreviewMutation.isPending || tableImportMutation.isPending}
              beforeUpload={file => {
                setSelectedTableFile(file)
                setTableImportPreview(null)
                tablePreviewMutation.mutate(file)
                return false
              }}
            >
              <p className="ant-upload-drag-icon"><UploadOutlined /></p>
              <p className="ant-upload-text">
                {selectedTableFile ? selectedTableFile.name : '支持 CSV / Excel，表头可用 name、asset_type、latitude、longitude'}
              </p>
            </Upload.Dragger>
            {tableImportPreview && (
              <div className="jurisdiction-import-preview">
                <span>总行数 <b>{tableImportPreview.total}</b></span>
                <span>有效 <b>{tableImportPreview.valid}</b></span>
                <span>错误 <b>{tableImportPreview.errors.length}</b></span>
                <Button
                  size="small"
                  type="primary"
                  disabled={!selectedTableFile || tableImportPreview.valid === 0}
                  loading={tableImportMutation.isPending}
                  onClick={() => selectedTableFile && tableImportMutation.mutate(selectedTableFile)}
                >
                  确认写入
                </Button>
              </div>
            )}
            {tableImportPreview?.errors.length ? (
              <List
                size="small"
                dataSource={tableImportPreview.errors.slice(0, 3)}
                renderItem={item => <List.Item>第 {item.row} 行：{item.error}</List.Item>}
              />
            ) : null}
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
          <Card title="预防工作台总览" className="jurisdiction-card">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Statistic title="相似风险点" value={workbench?.similar_targets?.items.length ?? 0} />
              <Statistic title="关注点位" value={workbench?.patrol_plan?.control_points.length ?? 0} />
              <Statistic title="复盘事项" value={workbench?.roundtable_briefing?.tasks.length ?? 0} />
              <div className="jurisdiction-muted">
                {activeCaseId ? `当前案件：${activeCaseId}` : '未选择案件时展示基础巡防建议'}
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} xl={10}>
          <Card title="录入辖区要素" className="jurisdiction-card">
            <Alert
              type="info"
              showIcon
              message="地图数据是底座，业务标注是价值"
              description="道路、村屯可来自地图；井口、技防盲区、临时便道、隐蔽区域等需要人工或内部台账持续补充。"
              style={{ marginBottom: 16 }}
            />
            <Form
              form={form}
              layout="vertical"
              onFinish={(values) => createAssetMutation.mutate(values)}
              initialValues={{ source: 'manual', geometry_type: 'point', status: 'active', risk_level: 1 }}
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
                      {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                        <Select.Option key={value} value={value}>{label}</Select.Option>
                      ))}
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
                      <Select.Option value="map">地图获取</Select.Option>
                      <Select.Option value="import">批量导入</Select.Option>
                    </Select>
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="risk_level" label="人工风险等级">
                    <InputNumber style={{ width: '100%' }} min={1} max={5} />
                  </Form.Item>
                </Col>
                <Col span={24}>
                  <Form.Item name="description" label="说明">
                    <Input.TextArea rows={3} placeholder="记录夜间通行、监控盲区、可停车点等业务事实" />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" htmlType="submit" loading={createAssetMutation.isPending}>
                录入到底座
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
        <Col xs={24} lg={9}>
          <Card title="案件空间上下文" className="jurisdiction-card">
            <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
              <InputNumber
                min={1}
                style={{ width: '100%' }}
                placeholder="输入案件 ID"
                value={caseIdInput}
                onChange={value => setCaseIdInput(value)}
              />
              <Button type="primary" onClick={runCaseAnalysis}>分析</Button>
            </Space.Compact>

            {contextQuery.isFetching && <Spin />}
            {!context && !contextQuery.isFetching && (
              <Empty description="输入案件 ID 后生成道路、村屯、技防覆盖和现场条件画像" />
            )}
            {context && (
              <div className="risk-context">
                <Progress percent={context.risk_score} status={context.risk_score >= 70 ? 'exception' : 'active'} />
                <div className="context-title">{context.case_number}</div>
                <List
                  size="small"
                  dataSource={nearestEntries(context)}
                  renderItem={([key, item]) => (
                    <List.Item>
                      <span>{typeLabel(key)}</span>
                      <strong>{item.asset.name} · {item.distance_km.toFixed(2)} km</strong>
                    </List.Item>
                  )}
                />
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={7}>
          <Card title="风险条件" className="jurisdiction-card">
            {context ? (
              <List
                size="small"
                dataSource={context.risk_conditions}
                renderItem={item => <List.Item>{item}</List.Item>}
              />
            ) : <Empty description="暂无案件画像" />}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="相似风险点" className="jurisdiction-card">
            {similarQuery.isFetching && <Spin />}
            {similarQuery.data && similarQuery.data.items.length > 0 ? (
              <List
                dataSource={similarQuery.data.items}
                renderItem={item => (
                  <List.Item className="similar-item">
                    <div>
                      <div className="similar-title">
                        {item.asset.name}
                        <Tag color={item.similarity_score >= 70 ? 'red' : 'orange'}>
                          {item.similarity_score}%
                        </Tag>
                      </div>
                      <div className="jurisdiction-muted">{item.reasons.slice(0, 2).join('；')}</div>
                    </div>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="暂无相似目标，需先录入案件周边道路/村屯/生产目标" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} lg={8}>
          <Card title="阶段2 · 案件经验卡" className="jurisdiction-card">
            {experienceQuery.isFetching && <Spin />}
            {experienceQuery.data ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div className="context-title">{experienceQuery.data.case_number}</div>
                <Space wrap>
                  <Tag color="blue">{experienceQuery.data.time_pattern.period}</Tag>
                  {experienceQuery.data.modus_tags.map(tag => (
                    <Tag key={tag}>{tag}</Tag>
                  ))}
                </Space>
                <div>
                  <div className="jurisdiction-subtitle">可复用经验</div>
                  {renderStringList(experienceQuery.data.reusable_lessons)}
                </div>
              </Space>
            ) : (
              <Empty description="先输入案件 ID 生成经验卡" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="阶段3 · 点位风险画像" className="jurisdiction-card">
            {assetProfileQuery.isFetching && <Spin />}
            {assetProfileQuery.data ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div className="context-title">{assetProfileQuery.data.asset.name}</div>
                <Progress
                  percent={Math.round(assetProfileQuery.data.risk_score)}
                  status={assetProfileQuery.data.risk_score >= 70 ? 'exception' : 'active'}
                />
                <Space wrap>
                  <Tag color="orange">风险等级 {assetProfileQuery.data.risk_level}</Tag>
                  <Tag>关联案件 {assetProfileQuery.data.related_cases.length} 起</Tag>
                </Space>
                {renderStringList(assetProfileQuery.data.risk_reasons)}
              </Space>
            ) : (
              <Empty description="点击上方辖区要素表中的点位查看画像" />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="阶段4 · 防控参考草案" className="jurisdiction-card">
            {patrolPlanQuery.isFetching && <Spin />}
            {patrolPlanQuery.data ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div className="jurisdiction-subtitle">控点</div>
                <List
                  size="small"
                  dataSource={patrolPlanQuery.data.control_points}
                  renderItem={item => (
                    <List.Item>
                      <span>{item.asset.name}</span>
                      <Tag>优先级 {item.priority}</Tag>
                    </List.Item>
                  )}
                />
                <div className="jurisdiction-subtitle">控时</div>
                <Space wrap>
                  {patrolPlanQuery.data.time_windows.map(item => (
                    <Tag color="red" key={item.period}>{item.period}</Tag>
                  ))}
                </Space>
                {renderStringList(patrolPlanQuery.data.tactics)}
                <Alert
                  type="info"
                  showIcon
                  message="当前仅输出防控参考，不在本项目内生成处置闭环。"
                />
              </Space>
            ) : (
              <Empty description="输入案件 ID 后生成防控参考" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="jurisdiction-section">
        <Col xs={24} lg={12}>
          <Card title="阶段5 · 研判复盘简报" className="jurisdiction-card">
            {briefingQuery.isFetching && <Spin />}
            {briefingQuery.data ? (
              <Row gutter={[16, 16]}>
                <Col xs={24} md={12}>
                  <div className="jurisdiction-subtitle">复盘议题</div>
                  {renderStringList(briefingQuery.data.agenda)}
                </Col>
                <Col xs={24} md={12}>
                  <div className="jurisdiction-subtitle">建议清单</div>
                  <List
                    size="small"
                    dataSource={briefingQuery.data.tasks}
                    renderItem={item => (
                      <List.Item>
                        <span>{String(item.title ?? '建议事项')}</span>
                        <Tag>{String(item.owner ?? '待分配')}</Tag>
                      </List.Item>
                    )}
                  />
                </Col>
              </Row>
            ) : (
              <Empty description="输入案件 ID 后生成研判复盘简报" />
            )}
          </Card>
        </Col>

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
                    disabled={!activeCaseId}
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
                <Select>
                  {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                    <Select.Option key={value} value={value}>{label}</Select.Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="latitude" label="纬度">
                <InputNumber style={{ width: '100%' }} precision={6} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="longitude" label="经度">
                <InputNumber style={{ width: '100%' }} precision={6} />
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
            <Button type="primary" htmlType="submit" loading={updateAssetMutation.isPending}>
              保存
            </Button>
            <Button onClick={() => setEditingAsset(null)}>取消</Button>
            <Button
              danger
              loading={deactivateAssetMutation.isPending}
              disabled={!editingAsset}
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
