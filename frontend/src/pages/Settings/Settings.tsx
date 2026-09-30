import { useState, useEffect } from 'react'
import {
  Form,
  Input,
  Select,
  message,
  Tabs,
  Table,
  Modal,
  InputNumber,
  Popconfirm,
} from 'antd'
import {
  SaveOutlined,
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { configApi } from '../../services/config'
import { useRuntimeFeatures } from '../../config/useRuntimeFeatures'
import type { AIModel, ModelCreate, SystemConfig } from '../../types'
import './Settings.css'

const { Option } = Select
const { TextArea } = Input

const Settings: React.FC = () => {
  const [mapForm] = Form.useForm()
  const [meetingForm] = Form.useForm()
  const [modelForm] = Form.useForm()
  const [isModelModalVisible, setIsModelModalVisible] = useState(false)
  const [editingModel, setEditingModel] = useState<AIModel | null>(null)
  const queryClient = useQueryClient()
  const { query: runtimeQuery } = useRuntimeFeatures()

  // 获取配置
  const { data: mapConfigs } = useQuery({
    queryKey: ['configs', 'map'],
    queryFn: () => configApi.system.list('map'),
  })

  const { data: meetingConfigs } = useQuery({
    queryKey: ['configs', 'meeting'],
    queryFn: () => configApi.system.list('meeting'),
  })

  // AI模型相关查询
  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models'],
    queryFn: () => configApi.models.list(),
  })

  // 更新配置
  const updateMutation = useMutation({
    mutationFn: ({ configKey, data }: { configKey: string; data: any }) =>
      configApi.system.update(configKey, data),
    onSuccess: () => {
      message.success('保存成功')
      queryClient.invalidateQueries({ queryKey: ['configs'] })
    },
    onError: (error: any) => {
      message.error(`保存失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // 初始化默认配置
  const initMutation = useMutation({
    mutationFn: configApi.system.initDefaults,
    onSuccess: () => {
      message.success('默认配置初始化成功')
      queryClient.invalidateQueries({ queryKey: ['configs'] })
    },
    onError: (error: any) => {
      message.error(`初始化失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // AI模型相关mutations
  const createModelMutation = useMutation({
    mutationFn: configApi.models.create,
    onSuccess: () => {
      message.success('创建成功')
      setIsModelModalVisible(false)
      modelForm.resetFields()
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`创建失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const updateModelMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) =>
      configApi.models.update(id, data),
    onSuccess: () => {
      message.success('更新成功')
      setIsModelModalVisible(false)
      setEditingModel(null)
      modelForm.resetFields()
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`更新失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const deleteModelMutation = useMutation({
    mutationFn: configApi.models.delete,
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`删除失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const setDefaultModelMutation = useMutation({
    mutationFn: configApi.models.setDefaultModerator,
    onSuccess: () => {
      message.success('设置成功')
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`设置失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testModelMutation = useMutation({
    mutationFn: configApi.models.test,
    onSuccess: (data) => {
      if (data.success) {
        message.success('连接测试成功')
      } else {
        message.error(`连接测试失败: ${data.message}`)
      }
    },
    onError: (error: any) => {
      message.error(`测试失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  // 当配置加载完成后，填充表单
  useEffect(() => {
    if (mapConfigs) {
      const formData: any = {}
      mapConfigs.forEach((config) => {
        formData[config.config_key] = config.config_value
      })
      mapForm.setFieldsValue(formData)
    }
  }, [mapConfigs, mapForm])

  useEffect(() => {
    if (meetingConfigs) {
      const formData: any = {}
      meetingConfigs.forEach((config) => {
        formData[config.config_key] = config.config_value
      })
      meetingForm.setFieldsValue(formData)
    }
  }, [meetingConfigs, meetingForm])

  const handleMapSubmit = async () => {
    try {
      const values = await mapForm.validateFields()
      const updates = [
        { key: 'map_api_provider', value: values.map_api_provider },
        { key: 'map_api_key', value: values.map_api_key || '' },
        { key: 'map_api_base_url', value: values.map_api_base_url || '' },
      ]
      await Promise.all(
        updates.map(({ key, value }) =>
          updateMutation.mutateAsync({ configKey: key, data: { config_value: value } })
        )
      )
    } catch (error) {
      console.error('Validation failed:', error)
    }
  }

  const handleMeetingSubmit = async () => {
    try {
      const values = await meetingForm.validateFields()
      const updates = [
        { key: 'meeting_api_provider', value: values.meeting_api_provider },
        { key: 'meeting_api_key', value: values.meeting_api_key || '' },
        { key: 'meeting_api_base_url', value: values.meeting_api_base_url || '' },
      ]
      await Promise.all(
        updates.map(({ key, value }) =>
          updateMutation.mutateAsync({ configKey: key, data: { config_value: value } })
        )
      )
    } catch (error) {
      console.error('Validation failed:', error)
    }
  }

  const getConfigDescription = (configKey: string, configs: SystemConfig[] = []) => {
    const config = configs.find((c) => c.config_key === configKey)
    return config?.description || ''
  }

  const getProviderBadgeClass = (provider: string) => {
    if (provider === 'openai') return 'settings-badge settings-badge--openai'
    if (provider === 'anthropic') return 'settings-badge settings-badge--anthropic'
    if (provider === 'azure-openai') return 'settings-badge settings-badge--azure'
    return 'settings-badge settings-badge--compatible'
  }

  const handleCreateModel = () => {
    setEditingModel(null)
    modelForm.resetFields()
    modelForm.setFieldsValue({
      provider: 'openai',
      role: 'analyst',
      config: { temperature: 0.7, max_tokens: 8192 },
    })
    setIsModelModalVisible(true)
  }

  const handleEditModel = (model: AIModel) => {
    setEditingModel(model)
    modelForm.setFieldsValue({ ...model, api_key: '' })
    setIsModelModalVisible(true)
  }

  const handleModelSubmit = async () => {
    try {
      const values = await modelForm.validateFields()
      if (editingModel) {
        updateModelMutation.mutate({ id: editingModel.id, data: values })
      } else {
        createModelMutation.mutate(values as ModelCreate)
      }
    } catch (error) {
      console.error('Validation failed:', error)
    }
  }

  const modelColumns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <span style={{ color: 'var(--ink-0)', fontSize: 13 }}>{name}</span>
      ),
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      render: (provider: string) => (
        <span className={getProviderBadgeClass(provider)}>{provider.toUpperCase()}</span>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
      render: (name: string) => (
        <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-2)' }}>{name}</span>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <span className={role === 'moderator' ? 'settings-badge settings-badge--moderator' : 'settings-badge settings-badge--analyst'}>
          {role === 'moderator' ? '主持人' : '分析员'}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (isActive: boolean) => (
        <span className={isActive ? 'settings-badge settings-badge--active' : 'settings-badge settings-badge--inactive'}>
          {isActive ? '启用' : '禁用'}
        </span>
      ),
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (isDefault: boolean) =>
        isDefault && <CheckCircleOutlined style={{ color: 'var(--ok)' }} />,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: AIModel) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button className="settings-action-btn" onClick={() => handleEditModel(record)}>
            <EditOutlined /> 编辑
          </button>
          <Popconfirm
            title="确认删除"
            description="确定要删除这个模型配置吗？"
            onConfirm={() => deleteModelMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <button className="settings-action-btn settings-action-btn--danger">
              <DeleteOutlined /> 删除
            </button>
          </Popconfirm>
          <button className="settings-action-btn" onClick={() => testModelMutation.mutate(record.id)}>
            测试
          </button>
          {record.role === 'moderator' && !record.is_default && (
            <button className="settings-action-btn" onClick={() => setDefaultModelMutation.mutate(record.id)}>
              设为默认
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="page-scrollable">

      {/* 页面标题 */}
      <div className="page-title">
        <h1>系统配置</h1>
        <span className="sub">SYSTEM SETTINGS</span>
        <span className="spacer" style={{ flex: 1 }} />
        <button
          className="btn-ghost"
          onClick={() => initMutation.mutate()}
          disabled={initMutation.isPending}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <ReloadOutlined />
          初始化默认配置
        </button>
      </div>

      <section className="settings-runtime" aria-label="系统运行状态"><h2>系统运行状态</h2>
        {runtimeQuery.isError ? <p role="alert">运行状态读取失败</p> : runtimeQuery.data ? <dl>
          <div><dt>数据库</dt><dd>{runtimeQuery.data.database}</dd></div>
          <div><dt>缓存</dt><dd>{runtimeQuery.data.redis === 'ok' ? 'Redis 在线' : 'Redis 未就绪'}</dd></div>
          <div><dt>可用模型</dt><dd>{runtimeQuery.data.active_model_count} 个</dd></div>
          <div><dt>地图服务</dt><dd>{runtimeQuery.data.map_configured ? runtimeQuery.data.map_provider : '未配置'}</dd></div>
        </dl> : <p role="status">正在读取运行状态</p>}
      </section>
      <Tabs
        className="settings-tabs"
        defaultActiveKey="models"
        items={[
          /* ── AI 模型配置 ── */
          {
            key: 'models',
            label: (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <SettingOutlined />AI 模型
              </span>
            ),
            children: (
              <div style={{ paddingTop: 'var(--gap)' }}>
                {/* 说明块 */}
                <div className="settings-info-block">
                  <InfoCircleOutlined style={{ color: 'var(--info)', marginRight: 8 }} />
                  <div style={{ display: 'inline' }}>
                    <div className="settings-info-block__title">AI MODEL CONFIGURATION</div>
                    <p className="settings-info-block__text">
                      配置用于案件分析和圆桌会议的 AI 模型，每个模型可设置为「主持人」或「分析员」角色。
                    </p>
                    <ul className="settings-info-block__list">
                      <li><strong>主持人</strong>：负责组织圆桌会议并生成最终报告，建议使用能力较强的模型。</li>
                      <li><strong>分析员</strong>：参与讨论，从不同角度分析案件，可配置多个不同专业方向。</li>
                      <li>支持 OpenAI、Anthropic（Claude）以及兼容 OpenAI 协议的第三方服务。</li>
                    </ul>
                  </div>
                </div>

                {/* 表格操作 */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <span style={{ fontFamily: 'var(--mono)', fontSize: 12, letterSpacing: '0.14em', color: 'var(--ink-3)', textTransform: 'uppercase' }}>
                    模型列表
                  </span>
                  <button className="btn-primary" onClick={handleCreateModel} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <PlusOutlined /> 添加模型
                  </button>
                </div>

                <Table
                  columns={modelColumns}
                  dataSource={models}
                  loading={modelsLoading}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                />

                {/* 编辑/添加模型 Modal */}
                <Modal
                  title={
                    <span style={{ fontFamily: 'var(--sans)', color: 'var(--ink-0)', fontSize: 14 }}>
                      {editingModel ? '编辑模型配置' : '添加模型配置'}
                    </span>
                  }
                  open={isModelModalVisible}
                  onOk={handleModelSubmit}
                  onCancel={() => {
                    setIsModelModalVisible(false)
                    setEditingModel(null)
                    modelForm.resetFields()
                  }}
                  width={600}
                  className="settings-modal"
                  confirmLoading={createModelMutation.isPending || updateModelMutation.isPending}
                  okButtonProps={{ className: 'btn-primary' }}
                  cancelButtonProps={{ className: 'btn-ghost' }}
                >
                  <Form
                    form={modelForm}
                    name="model-config"
                    layout="vertical"
                    className="settings-form"
                    initialValues={{ provider: 'openai', role: 'analyst', config: { temperature: 0.7, max_tokens: 8192 } }}
                  >
                    <Form.Item name="name" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
                      <Input placeholder="例如：GPT-4分析员" />
                    </Form.Item>
                    <Form.Item name="provider" label="提供商" rules={[{ required: true, message: '请选择提供商' }]}>
                      <Select showSearch placeholder="选择或输入提供商标识" allowClear>
                        <Option value="openai">OpenAI（api.openai.com）</Option>
                        <Option value="openai-compatible">OpenAI 兼容接口（自建/第三方）</Option>
                        <Option value="azure-openai">Azure OpenAI</Option>
                        <Option value="anthropic">Anthropic (Claude)</Option>
                      </Select>
                    </Form.Item>
                    <Form.Item name="model_name" label="模型名称/部署名" rules={[{ required: true, message: '请输入模型名称' }]}>
                      <Input placeholder="如：gpt-4o, claude-3-opus" />
                    </Form.Item>
                    <Form.Item name="api_key" label="API 密钥" rules={[{ required: !editingModel, message: '请输入API密钥' }]}>
                      <Input.Password placeholder={editingModel ? '留空则不更新' : '输入API密钥或访问令牌'} />
                    </Form.Item>
                    <Form.Item name="role" label="角色" rules={[{ required: true }]}>
                      <Select>
                        <Option value="moderator">主持人</Option>
                        <Option value="analyst">分析员</Option>
                      </Select>
                    </Form.Item>
                    <Form.Item label="模型参数（可选）">
                      <Form.Item name={['config', 'temperature']} label="温度" style={{ marginBottom: 8 }}>
                        <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
                      </Form.Item>
                      <Form.Item name={['config', 'max_tokens']} label="最大 Token 数" style={{ marginBottom: 8 }}>
                        <InputNumber min={100} max={131072} step={1000} style={{ width: '100%' }} placeholder="如：8192、32768、131072" />
                      </Form.Item>
                      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--line)', padding: '7px 11px', marginBottom: 8, fontSize: 12, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
                        GPT-4：8k/32k · Claude：100k · DeepSeek：128k
                      </div>
                      <Form.Item name={['config', 'api_base']} label="API Base URL（可选）">
                        <Input placeholder="如：https://api.openai.com/v1" />
                      </Form.Item>
                    </Form.Item>
                    <Form.Item name="description" label="描述">
                      <TextArea rows={3} placeholder="模型描述（可选）" />
                    </Form.Item>
                  </Form>
                </Modal>
              </div>
            ),
          },

          /* ── 地图 API 配置 ── */
          {
            key: 'map',
            label: '地图 API',
            children: (
              <div style={{ paddingTop: 'var(--gap)' }}>
                <div className="settings-info-block">
                  <div className="settings-info-block__title">MAP API CONFIGURATION</div>
                  <p className="settings-info-block__text">地图 API 用于「案件地图」页面展示案件位置及地理线索分析。</p>
                  <ul className="settings-info-block__list">
                    <li><strong>OpenStreetMap（推荐）</strong>：免费，无需 API key，功能基础</li>
                    <li><strong>Mapbox</strong>：需要 API key，功能强大，支持多种地图样式</li>
                    <li><strong>高德地图</strong>：需要 API key，国内服务稳定</li>
                    <li><strong>百度地图</strong>：需要 API key，国内服务稳定</li>
                  </ul>
                </div>

                <div className="card">
                  <div className="card-body pad">
                    <Form form={mapForm} layout="vertical" className="settings-form" onFinish={handleMapSubmit}>
                      <Form.Item
                        name="map_api_provider"
                        label="地图服务提供商"
                        rules={[{ required: true, message: '请选择地图服务提供商' }]}
                        tooltip={getConfigDescription('map_api_provider', mapConfigs)}
                      >
                        <Select placeholder="选择地图服务提供商">
                          <Option value="openstreetmap">OpenStreetMap（免费，无需 API key）</Option>
                          <Option value="mapbox">Mapbox（需要 API key）</Option>
                          <Option value="amap">高德地图（需要 API key）</Option>
                          <Option value="baidu">百度地图（需要 API key）</Option>
                        </Select>
                      </Form.Item>
                      <Form.Item name="map_api_key" label="地图 API 密钥" tooltip={getConfigDescription('map_api_key', mapConfigs)}>
                        <Input.Password
                          placeholder={mapConfigs?.find(item => item.config_key === 'map_api_key')?.is_configured ? '已安全保存，留空保持不变' : '输入地图 API 密钥（OpenStreetMap 不需要）'}
                          autoComplete="new-password"
                        />
                      </Form.Item>
                      <Form.Item name="map_api_base_url" label="地图 API 服务地址（可选）" tooltip={getConfigDescription('map_api_base_url', mapConfigs)}>
                        <Input placeholder="如：https://api.mapbox.com" />
                      </Form.Item>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 10, borderTop: '1px solid var(--line-soft)' }}>
                        <button
                          className="btn-primary"
                          type="submit"
                          disabled={updateMutation.isPending}
                          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                        >
                          <SaveOutlined /> 保存地图配置
                        </button>
                      </div>
                    </Form>
                  </div>
                </div>
              </div>
            ),
          },

          /* ── 圆桌会议 API 配置 ── */
          {
            key: 'meeting',
            label: '圆桌会议 API',
            children: (
              <div style={{ paddingTop: 'var(--gap)' }}>
                <div className="settings-info-block">
                  <div className="settings-info-block__title">ROUNDTABLE API CONFIGURATION</div>
                  <p className="settings-info-block__text">圆桌会议 API 用于多 LLM 模型协作分析案件的会议功能。</p>
                  <ul className="settings-info-block__list">
                    <li><strong>Direct 模式（推荐）</strong>：直接使用「AI 模型配置」中的模型，无需额外 API key。</li>
                    <li><strong>OpenRouter 模式</strong>：通过 OpenRouter 统一接口访问多个 LLM 模型，需要 API key。</li>
                  </ul>
                </div>

                <div className="card">
                  <div className="card-body pad">
                    <Form form={meetingForm} layout="vertical" className="settings-form" onFinish={handleMeetingSubmit}>
                      <Form.Item
                        name="meeting_api_provider"
                        label="圆桌会议 API 提供商"
                        rules={[{ required: true, message: '请选择 API 提供商' }]}
                        tooltip={getConfigDescription('meeting_api_provider', meetingConfigs)}
                      >
                        <Select placeholder="选择 API 提供商">
                          <Option value="direct">Direct（直接使用 AI 模型配置，无需额外 API key）</Option>
                          <Option value="openrouter">OpenRouter（需要 API key）</Option>
                        </Select>
                      </Form.Item>
                      <Form.Item name="meeting_api_key" label="圆桌会议 API 密钥" tooltip={getConfigDescription('meeting_api_key', meetingConfigs)}>
                        <Input.Password
                          placeholder={meetingConfigs?.find(item => item.config_key === 'meeting_api_key')?.is_configured ? '已安全保存，留空保持不变' : '输入 OpenRouter API 密钥（Direct 模式不需要）'}
                          autoComplete="new-password"
                        />
                      </Form.Item>
                      <Form.Item name="meeting_api_base_url" label="圆桌会议 API 服务地址" tooltip={getConfigDescription('meeting_api_base_url', meetingConfigs)}>
                        <Input placeholder="默认：https://openrouter.ai/api/v1" />
                      </Form.Item>
                      <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 10, borderTop: '1px solid var(--line-soft)' }}>
                        <button
                          className="btn-primary"
                          type="submit"
                          disabled={updateMutation.isPending}
                          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                        >
                          <SaveOutlined /> 保存会议配置
                        </button>
                      </div>
                    </Form>
                  </div>
                </div>
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}

export default Settings
