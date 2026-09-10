import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Form,
  Input,
  InputNumber,
  List,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Tag,
  Upload,
  message,
} from 'antd'
import { DatabaseOutlined, SafetyCertificateOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '../../auth/AuthContext'
import {
  mapFoundationApi,
  type MapPreview,
} from '../../services'
import OfflineMapManager from './OfflineMapManager'


const COORDINATE_OPTIONS = [
  { value: 'wgs84', label: 'WGS84 经纬度' },
  { value: 'cgcs2000_geographic', label: 'CGCS2000 经纬度' },
  { value: 'gcj02', label: 'GCJ-02' },
  { value: 'bd09', label: 'BD-09' },
]

interface TemplateFormValues {
  name: string
  sheet_name?: string
  header_row: number
  coordinate_system: string
  axis_order: 'lon_lat' | 'lat_lon'
  external_id: string
  name_column: string
  asset_type: string
  longitude: string
  latitude: string
  address?: string
}

function previewStatus(preview?: MapPreview | null) {
  if (!preview) return 0
  if (!preview.publishable) return 1
  return 2
}

export default function MapDataGovernance() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [sourceForm] = Form.useForm()
  const [templateForm] = Form.useForm<TemplateFormValues>()
  const [selectedSourceId, setSelectedSourceId] = useState<number>()
  const [selectedTemplateId, setSelectedTemplateId] = useState<number>()
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [sourceRevision, setSourceRevision] = useState('')
  const [preview, setPreview] = useState<MapPreview | null>(null)

  const sourcesQuery = useQuery({
    queryKey: ['map-foundation-sources'],
    queryFn: mapFoundationApi.listSources,
    enabled: user?.role === 'admin',
  })
  const areasQuery = useQuery({
    queryKey: ['operational-areas'],
    queryFn: mapFoundationApi.listAreas,
    enabled: user?.role === 'admin',
  })
  useEffect(() => {
    if (!sourceForm.getFieldValue('operational_area_id') && areasQuery.data?.length) {
      const area = areasQuery.data.find(item => item.is_default) ?? areasQuery.data[0]
      sourceForm.setFieldValue('operational_area_id', area.id)
    }
  }, [areasQuery.data, sourceForm])
  const templatesQuery = useQuery({
    queryKey: ['map-foundation-templates', selectedSourceId],
    queryFn: () => mapFoundationApi.listTemplates(selectedSourceId),
    enabled: user?.role === 'admin' && selectedSourceId != null,
  })
  const conflictsQuery = useQuery({
    queryKey: ['map-foundation-conflicts'],
    queryFn: mapFoundationApi.listConflicts,
    enabled: user?.role === 'admin',
  })

  const sources = sourcesQuery.data ?? []
  const templates = templatesQuery.data ?? []
  const selectedSource = sources.find(item => item.id === selectedSourceId)
  const selectedTemplate = templates.find(item => item.id === selectedTemplateId)

  const sourceOptions = useMemo(
    () => sources.map(item => ({ value: item.id, label: `${item.name} · ${item.source_key}` })),
    [sources],
  )
  const templateOptions = useMemo(
    () => templates.map(item => ({ value: item.id, label: `${item.name} · v${item.version}` })),
    [templates],
  )

  const createSourceMutation = useMutation({
    mutationFn: mapFoundationApi.createSource,
    onSuccess: source => {
      void queryClient.invalidateQueries({ queryKey: ['map-foundation-sources'] })
      setSelectedSourceId(source.id)
      sourceForm.resetFields()
      message.success('地图来源已登记，下一步确认字段和坐标系')
    },
    onError: () => message.error('地图来源创建失败，请检查来源标识是否重复'),
  })

  const createTemplateMutation = useMutation({
    mutationFn: (values: TemplateFormValues) => {
      if (!selectedSourceId) throw new Error('未选择地图来源')
      return mapFoundationApi.createTemplate({
        source_id: selectedSourceId,
        name: values.name,
        sheet_name: values.sheet_name,
        header_row: values.header_row,
        coordinate_system: values.coordinate_system,
        axis_order: values.axis_order,
        coordinate_unit: 'degree',
        field_mapping: {
          external_id: values.external_id,
          name: values.name_column,
          asset_type: values.asset_type,
          longitude: values.longitude,
          latitude: values.latitude,
          ...(values.address ? { address: values.address } : {}),
        },
      })
    },
    onSuccess: template => {
      void queryClient.invalidateQueries({ queryKey: ['map-foundation-templates', selectedSourceId] })
      setSelectedTemplateId(template.id)
      setPreview(null)
      templateForm.resetFields()
      message.success('导入模板已保存；相同来源以后可直接复用')
    },
    onError: () => message.error('模板保存失败，请检查字段和坐标系配置'),
  })

  const previewMutation = useMutation({
    mutationFn: (file: File) => {
      if (!selectedSourceId) throw new Error('未选择地图来源')
      return mapFoundationApi.preview(selectedSourceId, file, selectedTemplateId)
    },
    onSuccess: result => {
      setPreview(result)
      if (!result.publishable) {
        message.warning('当前数据不能发布，异常记录已在预览中标出')
      } else {
        message.success(`预检完成：可发布 ${result.valid_rows} 条，隔离 ${result.quarantined_rows} 条`)
      }
    },
    onError: () => {
      setPreview(null)
      message.error('文件预检失败，请检查格式和模板')
    },
  })

  const ingestMutation = useMutation({
    mutationFn: () => {
      if (!selectedSourceId || !selectedTemplateId || !selectedFile) {
        throw new Error('导入信息不完整')
      }
      return mapFoundationApi.ingest(
        selectedSourceId,
        selectedTemplateId,
        selectedFile,
        sourceRevision,
      )
    },
    onSuccess: run => {
      void queryClient.invalidateQueries({ queryKey: ['map-foundation-conflicts'] })
      void queryClient.invalidateQueries({ queryKey: ['jurisdiction-assets'] })
      void queryClient.invalidateQueries({ queryKey: ['jurisdiction-summary'] })
      message.success(
        run.idempotent_replay
          ? '该版本文件已经处理过，未重复写入'
          : `导入完成：新增 ${run.created_assets}，更新 ${run.updated_assets}，隔离 ${run.quarantined_rows}`,
      )
      setSelectedFile(null)
      setPreview(null)
    },
    onError: () => message.error('文件导入失败，正式地图数据未被修改'),
  })

  const resolveMutation = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: 'reject' | 'retry' }) =>
      mapFoundationApi.resolveConflict(id, decision),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['map-foundation-conflicts'] })
      message.success('异常记录状态已更新')
    },
  })

  if (user?.role !== 'admin') return null

  return (
    <>
    <OfflineMapManager />
    <Card className="jurisdiction-card map-governance-card" title="生产地图数据治理" extra={<Tag color="green">管理员</Tag>}>
      <Alert
        showIcon
        type="info"
        message="生产台账先预检、再发布；坐标系不明确的数据不会进入地图"
        description="首次登记来源并确认模板，以后只需上传同类台账。系统保留每行来源、文件摘要、异常原因和地图要素历史版本。"
        style={{ marginBottom: 16 }}
      />

      <Steps
        size="small"
        current={selectedSourceId ? (selectedTemplateId ? previewStatus(preview) : 1) : 0}
        items={[{ title: '登记来源' }, { title: '确认模板' }, { title: '预检发布' }]}
        style={{ marginBottom: 20 }}
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={8}>
          <div className="jurisdiction-subtitle">1. 数据来源</div>
          <Select
            allowClear
            style={{ width: '100%', marginBottom: 12 }}
            options={sourceOptions}
            value={selectedSourceId}
            placeholder="选择已登记来源"
            loading={sourcesQuery.isLoading}
            onChange={value => {
              setSelectedSourceId(value)
              setSelectedTemplateId(undefined)
              setSelectedFile(null)
              setPreview(null)
            }}
          />
          <Collapse
            ghost
            items={[{
              key: 'source',
              label: '登记新的台账来源',
              children: (
                <Form
                  form={sourceForm}
                  layout="vertical"
                  initialValues={{ source_type: 'ledger', trust_rank: 100 }}
                  onFinish={values => createSourceMutation.mutate(values)}
                >
                  <Form.Item name="name" label="来源名称" rules={[{ required: true }]}>
                    <Input placeholder="例如：采油厂生产井主台账" />
                  </Form.Item>
                  <Form.Item name="source_key" label="稳定来源标识" rules={[{ required: true }]}>
                    <Input placeholder="例如：production-well-ledger" />
                  </Form.Item>
                  <Form.Item name="operational_area_id" label="所属厂区" rules={[{ required: true }]}>
                    <Select
                      placeholder="选择该台账对应的厂区"
                      options={(areasQuery.data ?? []).map(item => ({ value: item.id, label: item.name }))}
                    />
                  </Form.Item>
                  <Row gutter={8}>
                    <Col span={14}>
                      <Form.Item name="source_type" label="类型">
                        <Select options={[
                          { value: 'ledger', label: '内部生产台账' },
                          { value: 'manual', label: '人工核验数据' },
                          { value: 'internal_gis', label: '内部 GIS' },
                          { value: 'public_map', label: '公共地图参考' },
                        ]} />
                      </Form.Item>
                    </Col>
                    <Col span={10}>
                      <Form.Item name="trust_rank" label="来源优先级">
                        <InputNumber min={0} max={100} style={{ width: '100%' }} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Button htmlType="submit" loading={createSourceMutation.isPending}>保存来源</Button>
                </Form>
              ),
            }]}
          />
        </Col>

        <Col xs={24} xl={8}>
          <div className="jurisdiction-subtitle">2. 字段与坐标模板</div>
          <Select
            allowClear
            disabled={!selectedSourceId}
            style={{ width: '100%', marginBottom: 12 }}
            options={templateOptions}
            value={selectedTemplateId}
            placeholder="选择已确认模板"
            onChange={value => {
              setSelectedTemplateId(value)
              setSelectedFile(null)
              setPreview(null)
            }}
          />
          <Collapse
            ghost
            items={[{
              key: 'template',
              label: '为该来源保存新模板',
              children: (
                <Form
                  form={templateForm}
                  layout="vertical"
                  disabled={!selectedSourceId}
                  initialValues={{
                    header_row: 1,
                    coordinate_system: 'wgs84',
                    axis_order: 'lon_lat',
                    external_id: '井号',
                    name_column: '井名',
                    asset_type: '类型',
                    longitude: '经度',
                    latitude: '纬度',
                  }}
                  onFinish={values => createTemplateMutation.mutate(values)}
                >
                  <Form.Item name="name" label="模板名称" rules={[{ required: true }]}>
                    <Input placeholder="例如：生产井月度台账" />
                  </Form.Item>
                  <Row gutter={8}>
                    <Col span={12}>
                      <Form.Item name="coordinate_system" label="坐标系" rules={[{ required: true }]}>
                        <Select options={COORDINATE_OPTIONS} />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item name="axis_order" label="坐标列顺序">
                        <Select options={[
                          { value: 'lon_lat', label: '经度、纬度' },
                          { value: 'lat_lon', label: '纬度、经度' },
                        ]} />
                      </Form.Item>
                    </Col>
                  </Row>
                  <div className="map-governance-fields">
                    <Form.Item name="external_id" label="编号列"><Input /></Form.Item>
                    <Form.Item name="name_column" label="名称列" rules={[{ required: true }]}><Input /></Form.Item>
                    <Form.Item name="asset_type" label="类型列" rules={[{ required: true }]}><Input /></Form.Item>
                    <Form.Item name="longitude" label="经度列" rules={[{ required: true }]}><Input /></Form.Item>
                    <Form.Item name="latitude" label="纬度列" rules={[{ required: true }]}><Input /></Form.Item>
                    <Form.Item name="address" label="地址列"><Input /></Form.Item>
                  </div>
                  <Button htmlType="submit" loading={createTemplateMutation.isPending}>保存模板</Button>
                </Form>
              ),
            }]}
          />
        </Col>

        <Col xs={24} xl={8}>
          <div className="jurisdiction-subtitle">3. 文件预检与发布</div>
          <Input
            value={sourceRevision}
            onChange={event => setSourceRevision(event.target.value)}
            placeholder="数据版本，例如：2026-09-08"
            style={{ marginBottom: 12 }}
          />
          <Upload.Dragger
            accept=".csv,.xlsx,.xlsm,.xltx,.xltm"
            multiple={false}
            showUploadList={false}
            disabled={!selectedSourceId || previewMutation.isPending || ingestMutation.isPending}
            beforeUpload={file => {
              setSelectedFile(file)
              setPreview(null)
              previewMutation.mutate(file)
              return false
            }}
          >
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p className="ant-upload-text">{selectedFile?.name ?? '上传 CSV / Excel 后自动预检'}</p>
          </Upload.Dragger>
          {preview && (
            <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 12 }}>
              <Space wrap>
                <Tag color="green">可发布 {preview.valid_rows}</Tag>
                <Tag color={preview.quarantined_rows ? 'orange' : 'default'}>隔离 {preview.quarantined_rows}</Tag>
              </Space>
              {preview.errors.slice(0, 3).map(item => (
                <div className="jurisdiction-muted" key={`${item.row}-${item.code}`}>
                  第 {item.row} 行：{item.message}
                </div>
              ))}
              <Button
                type="primary"
                icon={<SafetyCertificateOutlined />}
                disabled={!selectedTemplate || !preview.publishable || !selectedFile}
                loading={ingestMutation.isPending}
                onClick={() => ingestMutation.mutate()}
              >
                发布合格记录
              </Button>
            </Space>
          )}
          {!selectedTemplate && selectedSource && (
            <Alert
              type="warning"
              showIcon
              message="未确认坐标模板时只能预览，不能发布"
              style={{ marginTop: 12 }}
            />
          )}
        </Col>
      </Row>

      <div className="map-governance-summary">
        <Statistic title="已登记来源" value={sources.length} prefix={<DatabaseOutlined />} />
        <Statistic title="当前来源模板" value={templates.length} />
        <Statistic title="待处理异常" value={conflictsQuery.data?.length ?? 0} />
      </div>

      {(conflictsQuery.data?.length ?? 0) > 0 && (
        <Collapse
          ghost
          items={[{
            key: 'conflicts',
            label: `异常隔离区（${conflictsQuery.data?.length ?? 0}）`,
            children: (
              <List
                size="small"
                dataSource={conflictsQuery.data}
                renderItem={item => (
                  <List.Item
                    actions={[
                      <Button key="retry" size="small" onClick={() => resolveMutation.mutate({ id: item.id, decision: 'retry' })}>标记待重导</Button>,
                      <Button key="reject" size="small" danger onClick={() => resolveMutation.mutate({ id: item.id, decision: 'reject' })}>驳回</Button>,
                    ]}
                  >
                    第 {item.row_number} 行 · {item.source_record_id || '无来源编号'} · {item.error_message}
                  </List.Item>
                )}
              />
            ),
          }]}
        />
      )}
    </Card>
    </>
  )
}
