import React, { useState, useEffect } from 'react'
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  message,
  Tabs,
  Alert,
  Space,
  Typography,
  Divider,
  Table,
  Modal,
  InputNumber,
  Tag,
  Popconfirm,
} from 'antd'
import {
  SaveOutlined,
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { systemConfigApi, SystemConfig } from '../../services/systemConfig'
import { modelApi, AIModel, ModelCreate } from '../../services/models'

const { Option } = Select
const { TextArea } = Input
const { Title, Paragraph, Text } = Typography

const Settings: React.FC = () => {
  const [mapForm] = Form.useForm()
  const [meetingForm] = Form.useForm()
  const [modelForm] = Form.useForm()
  const [isModelModalVisible, setIsModelModalVisible] = useState(false)
  const [editingModel, setEditingModel] = useState<AIModel | null>(null)
  const queryClient = useQueryClient()

  // 获取配置
  const { data: mapConfigs, isLoading: mapLoading } = useQuery({
    queryKey: ['configs', 'map'],
    queryFn: () => systemConfigApi.getConfigs('map'),
  })

  const { data: meetingConfigs, isLoading: meetingLoading } = useQuery({
    queryKey: ['configs', 'meeting'],
    queryFn: () => systemConfigApi.getConfigs('meeting'),
  })

  // AI模型相关查询
  const { data: models, isLoading: modelsLoading } = useQuery({
    queryKey: ['models'],
    queryFn: () => modelApi.getModels(),
  })

  // 更新配置
  const updateMutation = useMutation({
    mutationFn: ({ configKey, data }: { configKey: string; data: any }) =>
      systemConfigApi.updateConfig(configKey, data),
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
    mutationFn: systemConfigApi.initDefaults,
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
    mutationFn: modelApi.createModel,
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
      modelApi.updateModel(id, data),
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
    mutationFn: modelApi.deleteModel,
    onSuccess: () => {
      message.success('删除成功')
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`删除失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const setDefaultModelMutation = useMutation({
    mutationFn: modelApi.setDefaultModerator,
    onSuccess: () => {
      message.success('设置成功')
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError: (error: any) => {
      message.error(`设置失败: ${error.response?.data?.detail || error.message}`)
    },
  })

  const testModelMutation = useMutation({
    mutationFn: modelApi.testModel,
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
          updateMutation.mutateAsync({
            configKey: key,
            data: { config_value: value },
          })
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
          updateMutation.mutateAsync({
            configKey: key,
            data: { config_value: value },
          })
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

  // AI模型相关处理函数
  const handleCreateModel = () => {
    setEditingModel(null)
    modelForm.resetFields()
    modelForm.setFieldsValue({
      provider: 'openai',
      role: 'analyst',
      config: {
        temperature: 0.7,
        max_tokens: 8192,
      },
    })
    setIsModelModalVisible(true)
  }

  const handleEditModel = (model: AIModel) => {
    setEditingModel(model)
    modelForm.setFieldsValue({
      ...model,
      api_key: '', // 不显示已保存的密钥
    })
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
    },
    {
      title: '提供商',
      dataIndex: 'provider',
      key: 'provider',
      render: (provider: string) => (
        <Tag color={provider === 'openai' ? 'blue' : 'purple'}>
          {provider.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'moderator' ? 'gold' : 'green'}>
          {role === 'moderator' ? '主持人' : '分析员'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (isActive: boolean) => (
        <Tag color={isActive ? 'success' : 'default'}>
          {isActive ? '启用' : '禁用'}
        </Tag>
      ),
    },
    {
      title: '默认',
      dataIndex: 'is_default',
      key: 'is_default',
      render: (isDefault: boolean) =>
        isDefault && <CheckCircleOutlined style={{ color: '#52c41a' }} />,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: AIModel) => (
        <Space>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEditModel(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除"
            description="确定要删除这个模型配置吗？"
            onConfirm={() => deleteModelMutation.mutate(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
          <Button
            type="link"
            onClick={() => testModelMutation.mutate(record.id)}
            loading={testModelMutation.isPending}
          >
            测试
          </Button>
          {record.role === 'moderator' && !record.is_default && (
            <Button
              type="link"
              onClick={() => setDefaultModelMutation.mutate(record.id)}
            >
              设为默认
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Title level={2}>系统设置</Title>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => initMutation.mutate()}
          loading={initMutation.isPending}
        >
          初始化默认配置
        </Button>
      </div>

      <Tabs
        defaultActiveKey="map"
        items={[
          {
            key: 'models',
            label: 'AI模型配置',
            children: (
              <Card>
                <Alert
                  message="AI模型配置说明"
                  description={
                    <div>
                      <Paragraph>
                        配置用于案件分析和圆桌会议的AI模型。每个模型可以设置为"主持人"或"分析员"角色。
                      </Paragraph>
                      <ul>
                        <li>
                          <Text strong>主持人</Text>：负责组织圆桌会议，生成最终报告。建议使用能力较强的模型（如GPT-4、Claude Opus等）。
                        </li>
                        <li>
                          <Text strong>分析员</Text>：参与圆桌会议讨论，从不同角度分析案件。可以配置多个不同专业方向的分析员。
                        </li>
                      </ul>
                      <Paragraph>
                        <Text type="secondary">
                          支持OpenAI、Anthropic（Claude）以及兼容OpenAI协议的第三方服务。
                        </Text>
                      </Paragraph>
                    </div>
                  }
                  type="info"
                  style={{ marginBottom: 24 }}
                />
                <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
                  <Title level={4}>模型列表</Title>
                  <Button type="primary" icon={<PlusOutlined />} onClick={handleCreateModel}>
                    添加模型
                  </Button>
                </div>
                <Table
                  columns={modelColumns}
                  dataSource={models}
                  loading={modelsLoading}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                />
                <Modal
                  title={editingModel ? '编辑模型' : '添加模型'}
                  open={isModelModalVisible}
                  onOk={handleModelSubmit}
                  onCancel={() => {
                    setIsModelModalVisible(false)
                    setEditingModel(null)
                    modelForm.resetFields()
                  }}
                  width={600}
                  confirmLoading={createModelMutation.isPending || updateModelMutation.isPending}
                >
                  <Form
                    form={modelForm}
                    layout="vertical"
                    initialValues={{
                      provider: 'openai',
                      role: 'analyst',
                      config: {
                        temperature: 0.7,
                        max_tokens: 8192,
                      },
                    }}
                  >
                    <Form.Item
                      name="name"
                      label="模型名称"
                      rules={[{ required: true, message: '请输入模型名称' }]}
                    >
                      <Input placeholder="例如：GPT-4分析员" />
                    </Form.Item>

                    <Form.Item
                      name="provider"
                      label="提供商（例如：openai / openai-compatible / anthropic）"
                      rules={[{ required: true, message: '请输入或选择提供商标识' }]}
                    >
                      <Select
                        showSearch
                        placeholder="选择或输入提供商标识"
                        optionFilterProp="children"
                        dropdownMatchSelectWidth={false}
                        allowClear
                      >
                        <Option value="openai">OpenAI（api.openai.com）</Option>
                        <Option value="openai-compatible">OpenAI兼容接口（自建/第三方）</Option>
                        <Option value="azure-openai">Azure OpenAI</Option>
                        <Option value="anthropic">Anthropic (Claude)</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item
                      name="model_name"
                      label="模型名称/部署名"
                      rules={[{ required: true, message: '请输入模型名称或部署名' }]}
                    >
                      <Input placeholder="例如：gpt-4o, gpt-4o-mini, claude-3-opus, gpt-4o (Azure部署名等)" />
                    </Form.Item>

                    <Form.Item
                      name="api_key"
                      label="API密钥"
                      rules={[{ required: !editingModel, message: '请输入API密钥（或令牌）' }]}
                    >
                      <Input.Password placeholder={editingModel ? '留空则不更新' : '输入API密钥或访问令牌'} />
                    </Form.Item>

                    <Form.Item name="role" label="角色" rules={[{ required: true }]}>
                      <Select>
                        <Option value="moderator">主持人</Option>
                        <Option value="analyst">分析员</Option>
                      </Select>
                    </Form.Item>

                    <Form.Item label="模型配置（可选）">
                      <Form.Item
                        name={['config', 'temperature']}
                        label="温度"
                        style={{ marginBottom: 8 }}
                      >
                        <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
                      </Form.Item>
                        <Form.Item name={['config', 'max_tokens']} label="最大Token数">
                          <InputNumber
                            min={100}
                            max={131072}
                            step={1000}
                            style={{ width: '100%' }}
                            placeholder="例如：8192（8k）、32768（32k）、131072（128k）"
                          />
                        </Form.Item>
                        <Alert
                          message="Token限制说明"
                          description="不同模型支持的上下文长度不同。例如：GPT-4支持8k/32k，Claude支持100k，DeepSeek支持128k。请根据您使用的模型设置合适的值。"
                          type="info"
                          showIcon
                          style={{ marginBottom: 16 }}
                        />
                      <Form.Item name={['config', 'api_base']} label="API Base URL（可选）">
                        <Input placeholder="如：https://api.openai.com/v1 或 自建网关地址" />
                      </Form.Item>
                    </Form.Item>

                    <Form.Item name="description" label="描述">
                      <TextArea rows={3} placeholder="模型描述（可选）" />
                    </Form.Item>
                  </Form>
                </Modal>
              </Card>
            ),
          },
          {
            key: 'map',
            label: '地图API配置',
            children: (
              <Card>
                <Alert
                  message="地图API配置说明"
                  description={
                    <div>
                      <Paragraph>
                        地图API用于在"案件地图"页面展示案件位置、进行地理线索分析等功能。
                      </Paragraph>
                      <ul>
                        <li>
                          <Text strong>OpenStreetMap（推荐）</Text>：免费，无需API key，功能基础
                        </li>
                        <li>
                          <Text strong>Mapbox</Text>：需要API key，功能强大，支持多种地图样式
                        </li>
                        <li>
                          <Text strong>高德地图</Text>：需要API key，国内服务稳定
                        </li>
                        <li>
                          <Text strong>百度地图</Text>：需要API key，国内服务稳定
                        </li>
                      </ul>
                    </div>
                  }
                  type="info"
                  style={{ marginBottom: 24 }}
                />

                <Form
                  form={mapForm}
                  layout="vertical"
                  onFinish={handleMapSubmit}
                >
                  <Form.Item
                    name="map_api_provider"
                    label="地图服务提供商"
                    rules={[{ required: true, message: '请选择地图服务提供商' }]}
                    tooltip={getConfigDescription('map_api_provider', mapConfigs)}
                  >
                    <Select placeholder="选择地图服务提供商">
                      <Option value="openstreetmap">OpenStreetMap（免费，无需API key）</Option>
                      <Option value="mapbox">Mapbox（需要API key）</Option>
                      <Option value="amap">高德地图（需要API key）</Option>
                      <Option value="baidu">百度地图（需要API key）</Option>
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="map_api_key"
                    label="地图API密钥"
                    tooltip={getConfigDescription('map_api_key', mapConfigs)}
                  >
                    <Input.Password
                      placeholder="输入地图API密钥（OpenStreetMap不需要）"
                      autoComplete="new-password"
                    />
                  </Form.Item>

                  <Form.Item
                    name="map_api_base_url"
                    label="地图API服务地址（可选）"
                    tooltip={getConfigDescription('map_api_base_url', mapConfigs)}
                  >
                    <Input placeholder="如：https://api.mapbox.com（某些自建服务需要）" />
                  </Form.Item>

                  <Form.Item>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      htmlType="submit"
                      loading={updateMutation.isPending}
                    >
                      保存地图配置
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            ),
          },
          {
            key: 'meeting',
            label: '圆桌会议API配置',
            children: (
              <Card>
                <Alert
                  message="圆桌会议API配置说明"
                  description={
                    <div>
                      <Paragraph>
                        圆桌会议API用于"圆桌会议"功能，让多个LLM模型协作分析案件。
                      </Paragraph>
                      <ul>
                        <li>
                          <Text strong>Direct模式（推荐）</Text>：直接使用"AI模型配置"中配置的模型，无需额外API
                          key。系统会使用你已配置的OpenAI、Claude等模型的API key。
                        </li>
                        <li>
                          <Text strong>OpenRouter模式</Text>：通过OpenRouter统一接口访问多个LLM模型。OpenRouter是一个统一的LLM
                          API网关，可以访问GPT、Claude、Gemini等多个模型，需要OpenRouter的API
                          key。适合需要快速切换多个模型的场景。
                        </li>
                      </ul>
                      <Paragraph>
                        <Text type="secondary">
                          注意：如果选择Direct模式，请确保在"AI模型配置"页面已正确配置各个模型的API
                          key。
                        </Text>
                      </Paragraph>
                    </div>
                  }
                  type="info"
                  style={{ marginBottom: 24 }}
                />

                <Form
                  form={meetingForm}
                  layout="vertical"
                  onFinish={handleMeetingSubmit}
                >
                  <Form.Item
                    name="meeting_api_provider"
                    label="圆桌会议API提供商"
                    rules={[{ required: true, message: '请选择API提供商' }]}
                    tooltip={getConfigDescription('meeting_api_provider', meetingConfigs)}
                  >
                    <Select placeholder="选择API提供商">
                      <Option value="direct">
                        Direct（直接使用AI模型配置，无需额外API key）
                      </Option>
                      <Option value="openrouter">OpenRouter（需要API key）</Option>
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="meeting_api_key"
                    label="圆桌会议API密钥"
                    tooltip={getConfigDescription('meeting_api_key', meetingConfigs)}
                  >
                    <Input.Password
                      placeholder="输入OpenRouter API密钥（Direct模式不需要）"
                      autoComplete="new-password"
                    />
                  </Form.Item>

                  <Form.Item
                    name="meeting_api_base_url"
                    label="圆桌会议API服务地址"
                    tooltip={getConfigDescription('meeting_api_base_url', meetingConfigs)}
                  >
                    <Input placeholder="默认：https://openrouter.ai/api/v1" />
                  </Form.Item>

                  <Form.Item>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      htmlType="submit"
                      loading={updateMutation.isPending}
                    >
                      保存会议配置
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            ),
          },
        ]}
      />
    </div>
  )
}

export default Settings

