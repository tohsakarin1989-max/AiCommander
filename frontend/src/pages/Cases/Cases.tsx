import { useEffect, useState, useMemo } from 'react'
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  DatePicker,
  InputNumber,
  message,
  Space,
  Tag,
  Popconfirm,
  Upload,
  Alert,
  Card,
  Select,
  Row,
  Col,
  Switch,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ApiOutlined, EnvironmentOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { caseApi } from '../../services/cases'
import type { Case, CaseCreate } from '../../types'
import { useNavigate, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import MapPicker from '../../components/Map/MapPicker'

const { TextArea } = Input
const { RangePicker } = DatePicker
const { Option } = Select

// 搜索筛选参数接口
interface SearchFilters {
  keyword?: string
  status?: string
  case_type?: string
  oil_type?: string
  start_date?: string
  end_date?: string
  has_geo?: boolean
}

const Cases: React.FC = () => {
  const [form] = Form.useForm()
  const [searchForm] = Form.useForm()
  const [isModalVisible, setIsModalVisible] = useState(false)
  const [editingCase, setEditingCase] = useState<Case | null>(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [importModalVisible, setImportModalVisible] = useState(false)
  const [showAdvancedSearch, setShowAdvancedSearch] = useState(false)
  const [filters, setFilters] = useState<SearchFilters>({})
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 构建查询参数
  const queryParams = useMemo(() => {
    const params: Record<string, string | boolean> = {}
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.status) params.status = filters.status
    if (filters.case_type) params.case_type = filters.case_type
    if (filters.oil_type) params.oil_type = filters.oil_type
    if (filters.start_date) params.start_date = filters.start_date
    if (filters.end_date) params.end_date = filters.end_date
    if (filters.has_geo !== undefined) params.has_geo = filters.has_geo
    return params
  }, [filters])

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases', queryParams],
    queryFn: () => caseApi.getCases(queryParams),
  })

  // 获取所有案件类型和油品类型（用于筛选下拉）
  const caseTypes = useMemo(() => {
    const types = new Set<string>()
    cases?.forEach(c => c.case_type && types.add(c.case_type))
    return Array.from(types)
  }, [cases])

  const oilTypes = useMemo(() => {
    const types = new Set<string>()
    cases?.forEach(c => c.oil_type && types.add(c.oil_type))
    return Array.from(types)
  }, [cases])

  useEffect(() => {
    const caseIdFromUrl = searchParams.get('caseId')
    if (!caseIdFromUrl || !cases) return
    const targetId = parseInt(caseIdFromUrl, 10)
    if (!Number.isNaN(targetId)) {
      setSelectedRowKeys([targetId])
    }
  }, [searchParams, cases])

  const { data: preprocessStatus } = useQuery({
    queryKey: ['preprocess-status'],
    queryFn: () => caseApi.getPreprocessStatus(),
    refetchInterval: 5000,
  })

  const createMutation = useMutation({
    mutationFn: caseApi.createCase,
    onSuccess: () => {
      message.success('创建成功')
      setIsModalVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Case> }) =>
      caseApi.updateCase(id, data),
    onSuccess: () => {
      message.success('更新成功')
      setIsModalVisible(false)
      setEditingCase(null)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: caseApi.deleteCase,
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  const preprocessMutation = useMutation({
    mutationFn: caseApi.preprocessCase,
    onSuccess: (data) => {
      message.success(data.message || '预处理任务已提交')
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: any) => {
      message.error(`预处理失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const importMutation = useMutation({
    mutationFn: (file: File) => caseApi.importCases(file),
    onSuccess: async (data) => {
      message.success(`导入成功：共 ${data.total} 条，成功 ${data.created} 条`)
      if (data.errors && data.errors.length) {
        message.warning('部分记录导入失败，详情请查看控制台')
        // eslint-disable-next-line no-console
        console.warn('导入错误详情：', data.errors)
      }
      setImportModalVisible(false)
      await queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: (error: Error) => {
      message.error(`导入失败：${error.message}`)
    },
  })

  const handleCreate = () => {
    setEditingCase(null)
    form.resetFields()
    setIsModalVisible(true)
  }

  const handleEdit = (caseItem: Case) => {
    setEditingCase(caseItem)
    form.setFieldsValue({
      ...caseItem,
      occurred_time: dayjs(caseItem.occurred_time),
    })
    setIsModalVisible(true)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      if (editingCase) {
        updateMutation.mutate({
          id: editingCase.id,
          data: {
            ...values,
            occurred_time: values.occurred_time?.toISOString(),
          },
        })
      } else {
        createMutation.mutate({
          ...values,
          occurred_time: values.occurred_time?.toISOString(),
        } as CaseCreate)
      }
      setSelectedRowKeys([])
    } catch (error) {
      console.error('Validation failed:', error)
    }
  }

  const columns = [
    {
      title: '案件编号',
      dataIndex: 'case_number',
      key: 'case_number',
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_time',
      key: 'occurred_time',
      render: (time: string) => dayjs(time).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '地点',
      dataIndex: 'location',
      key: 'location',
    },
    {
      title: '纬度',
      dataIndex: 'latitude',
      key: 'latitude',
      render: (lat: number | undefined) => (lat != null ? lat.toFixed(6) : ''),
    },
    {
      title: '经度',
      dataIndex: 'longitude',
      key: 'longitude',
      render: (lng: number | undefined) => (lng != null ? lng.toFixed(6) : ''),
    },
    {
      title: '类型',
      dataIndex: 'case_type',
      key: 'case_type',
    },
    {
      title: '油品类型',
      dataIndex: 'oil_type',
      key: 'oil_type',
    },
    {
      title: '涉油数量',
      dataIndex: 'oil_volume',
      key: 'oil_volume',
      render: (v: number | undefined) => (v != null ? v : ''),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <Tag>{status}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Case) => (
        <Space>
          <Button type="link" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            onConfirm={() => deleteMutation.mutate(record.id)}
          >
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
          <Button
            type="link"
            icon={<ApiOutlined />}
            loading={preprocessMutation.isPending}
            onClick={() => preprocessMutation.mutate(record.id)}
          >
            预处理
          </Button>
          {record.latitude != null && record.longitude != null && (
            <Button
              type="link"
              icon={<EnvironmentOutlined />}
              onClick={() => {
                // 跳转到地图页面，并传递案件ID作为查询参数
                navigate(`/cases/map?caseId=${record.id}`)
              }}
            >
              查看地图
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  const handleBatchPreprocess = async () => {
    if (!selectedRowKeys.length) {
      message.warning('请先选择需要预处理的案件')
      return
    }
    try {
      await Promise.all(
        selectedRowKeys.map((id) => caseApi.preprocessCase(id as number)),
      )
      message.success(`已提交 ${selectedRowKeys.length} 条预处理任务`)
      setSelectedRowKeys([])
    } catch (e: any) {
      message.error(`批量预处理失败：${e.message || e}`)
    }
  }

  // 搜索处理
  const handleSearch = () => {
    const values = searchForm.getFieldsValue()
    const newFilters: SearchFilters = {}

    if (values.keyword) newFilters.keyword = values.keyword
    if (values.status) newFilters.status = values.status
    if (values.case_type) newFilters.case_type = values.case_type
    if (values.oil_type) newFilters.oil_type = values.oil_type
    if (values.dateRange?.[0]) {
      newFilters.start_date = values.dateRange[0].format('YYYY-MM-DD')
    }
    if (values.dateRange?.[1]) {
      newFilters.end_date = values.dateRange[1].format('YYYY-MM-DD')
    }
    if (values.has_geo !== undefined) newFilters.has_geo = values.has_geo

    setFilters(newFilters)
  }

  const handleResetSearch = () => {
    searchForm.resetFields()
    setFilters({})
  }

  // 检查是否有筛选条件
  const hasFilters = Object.keys(filters).length > 0

  return (
    <div>
      {preprocessStatus && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={`预处理队列：排队 ${preprocessStatus.pending}，处理中 ${
            preprocessStatus.processing
          }，平均耗时 ${
            preprocessStatus.avg_duration_seconds != null
              ? `${Math.round(preprocessStatus.avg_duration_seconds)} 秒`
              : '暂无数据'
          }`}
        />
      )}

      {/* 搜索筛选区域 */}
      <Card style={{ marginBottom: 16 }}>
        <Form form={searchForm} layout="inline" style={{ marginBottom: 16 }}>
          <Form.Item name="keyword" style={{ marginBottom: 8 }}>
            <Input
              placeholder="搜索案件编号/地点/描述"
              prefix={<SearchOutlined />}
              allowClear
              style={{ width: 240 }}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item name="status" style={{ marginBottom: 8 }}>
            <Select placeholder="状态" allowClear style={{ width: 120 }}>
              <Option value="pending">待处理</Option>
              <Option value="processing">处理中</Option>
              <Option value="completed">已完成</Option>
              <Option value="resolved">已结案</Option>
            </Select>
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Space>
              <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
                搜索
              </Button>
              <Button icon={<ClearOutlined />} onClick={handleResetSearch}>
                重置
              </Button>
              <Button type="link" onClick={() => setShowAdvancedSearch(!showAdvancedSearch)}>
                {showAdvancedSearch ? '收起高级' : '高级搜索'}
              </Button>
            </Space>
          </Form.Item>
        </Form>

        {/* 高级搜索选项 */}
        {showAdvancedSearch && (
          <Form form={searchForm} layout="vertical">
            <Row gutter={16}>
              <Col span={6}>
                <Form.Item name="case_type" label="案件类型">
                  <Select placeholder="选择案件类型" allowClear>
                    {caseTypes.map(type => (
                      <Option key={type} value={type}>{type}</Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={6}>
                <Form.Item name="oil_type" label="油品类型">
                  <Select placeholder="选择油品类型" allowClear>
                    {oilTypes.map(type => (
                      <Option key={type} value={type}>{type}</Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="dateRange" label="发生时间">
                  <RangePicker style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={4}>
                <Form.Item name="has_geo" label="有坐标" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        )}

        {/* 当前筛选条件显示 */}
        {hasFilters && (
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              <span style={{ color: '#666' }}>当前筛选：</span>
              {filters.keyword && <Tag closable onClose={() => setFilters(f => ({ ...f, keyword: undefined }))}>关键词: {filters.keyword}</Tag>}
              {filters.status && <Tag closable onClose={() => setFilters(f => ({ ...f, status: undefined }))}>状态: {filters.status}</Tag>}
              {filters.case_type && <Tag closable onClose={() => setFilters(f => ({ ...f, case_type: undefined }))}>类型: {filters.case_type}</Tag>}
              {filters.oil_type && <Tag closable onClose={() => setFilters(f => ({ ...f, oil_type: undefined }))}>油品: {filters.oil_type}</Tag>}
              {filters.start_date && <Tag closable onClose={() => setFilters(f => ({ ...f, start_date: undefined }))}>开始: {filters.start_date}</Tag>}
              {filters.end_date && <Tag closable onClose={() => setFilters(f => ({ ...f, end_date: undefined }))}>结束: {filters.end_date}</Tag>}
              {filters.has_geo !== undefined && <Tag closable onClose={() => setFilters(f => ({ ...f, has_geo: undefined }))}>有坐标</Tag>}
            </Space>
          </div>
        )}
      </Card>

      <div
        style={{
          marginBottom: '16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <h2>
          案件管理
          {hasFilters && <Tag color="blue" style={{ marginLeft: 8 }}>已筛选: {cases?.length || 0} 条</Tag>}
        </h2>
        <Space>
          <Button onClick={() => setImportModalVisible(true)}>导入 CSV/Excel</Button>
          <Button
            onClick={handleBatchPreprocess}
            disabled={!selectedRowKeys.length}
          >
            批量预处理
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
            添加案件
          </Button>
        </Space>
      </div>

      <Table
        rowSelection={rowSelection}
        columns={columns}
        dataSource={cases}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={editingCase ? '编辑案件' : '添加案件'}
        open={isModalVisible}
        onOk={handleSubmit}
        onCancel={() => {
          setIsModalVisible(false)
          setEditingCase(null)
          form.resetFields()
        }}
        width={600}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="occurred_time"
            label="发生时间"
            rules={[{ required: true, message: '请选择发生时间' }]}
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>

          <Form.Item name="location" label="地点">
            <Input placeholder="如：××路××小区南门" />
          </Form.Item>

          <Form.Item label="经纬度（可选，用于地图与空间分析）" style={{ marginBottom: 0 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <Form.Item name="latitude" style={{ flex: 1, marginBottom: 0 }}>
                <InputNumber
                  style={{ width: '100%' }}
                  placeholder="纬度，例如 31.2304"
                  min={-90}
                  max={90}
                  step={0.000001}
                />
              </Form.Item>
              <Form.Item name="longitude" style={{ flex: 1, marginBottom: 0 }}>
                <InputNumber
                  style={{ width: '100%' }}
                  placeholder="经度，例如 121.4737"
                  min={-180}
                  max={180}
                  step={0.000001}
                />
              </Form.Item>
            </div>
          </Form.Item>

          <Form.Item label="地图选点（可选）">
            <MapPicker
              lat={form.getFieldValue('latitude')}
              lng={form.getFieldValue('longitude')}
              onChange={(lat, lng) => {
                form.setFieldsValue({ latitude: lat, longitude: lng })
              }}
            />
          </Form.Item>

          <Form.Item name="case_type" label="类型（可选）">
            <Input placeholder="如：盗窃、破坏生产经营等，如不清楚可留空" />
          </Form.Item>

          <Form.Item
            name="description"
            label="案情描述"
            rules={[{ required: true, message: '请输入案情描述' }]}
          >
            <TextArea rows={4} placeholder="请尽可能详细描述案情，其余结构化分析将由系统自动完成" />
          </Form.Item>

          <Form.Item name="loss_amount" label="损失金额（元，可选）">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>

          {/* 高级涉油特征折叠区域：仅在需要人工纠正模型判断时使用 */}
          <details style={{ marginTop: 16 }}>
            <summary style={{ cursor: 'pointer', fontWeight: 500 }}>
              涉油案件特征（高级，可选，用于人工修正）
            </summary>
            <div style={{ marginTop: 8 }}>
              <Form.Item name="oil_type" label="油品类型">
                <Input placeholder="如：汽油、柴油、原油、润滑油" />
              </Form.Item>

              <Form.Item name="oil_volume" label="涉油数量（吨或升，按约定单位）">
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name="oil_value" label="估算价值（元）">
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item name="facility_type" label="目标设施类型">
                <Input placeholder="如：输油管线、加油站、油库、油罐车" />
              </Form.Item>

              <Form.Item name="facility_owner" label="设施所属单位">
                <Input placeholder="如：某石油公司、某物流企业" />
              </Form.Item>

              <Form.Item name="security_level" label="安防情况">
                <Input placeholder="如：监控盲区、周界薄弱、安防良好" />
              </Form.Item>

              <Form.Item name="modus_operandi" label="主要作案手法">
                <Input placeholder="如：打孔盗油、私接管线、计量作弊" />
              </Form.Item>

              <Form.Item name="upstream_source" label="上游油品来源">
                <Input placeholder="如：某段管线某号桩、某站某枪" />
              </Form.Item>

              <Form.Item name="downstream_destination" label="疑似销赃去向">
                <Input placeholder="如：黑加油点、工地、车队等" />
              </Form.Item>
            </div>
          </details>
        </Form>
      </Modal>

      <Modal
        title="导入历史案件（CSV/Excel）"
        open={importModalVisible}
        onCancel={() => setImportModalVisible(false)}
        footer={null}
      >
        <p>
          请选择包含以下列的文件：<b>occurred_time</b>（发生时间）、<b>description</b>（案件描述）。
        </p>
        <p>
          可选列：<b>location</b>、<b>latitude</b>、<b>longitude</b>。
        </p>
        <Upload.Dragger
          name="file"
          multiple={false}
          showUploadList={false}
          beforeUpload={(file) => {
            importMutation.mutate(file)
            return false
          }}
        >
          <p className="ant-upload-drag-icon">将文件拖到此处，或点击选择文件</p>
          <p className="ant-upload-text">支持 CSV / Excel（.xlsx）文件</p>
        </Upload.Dragger>
      </Modal>
    </div>
  )
}

export default Cases
