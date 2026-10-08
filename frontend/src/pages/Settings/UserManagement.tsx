import { useState } from 'react'
import { Alert, Button, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from 'antd'
import { KeyOutlined, PlusOutlined, UserSwitchOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, type AuthUser, type UserCreatePayload, type UserRole } from '../../services/auth'
import { useAuth } from '../../auth/AuthContext'
import { mapFoundationApi } from '../../services/mapFoundation'
import UserAreaScopeEditor, { AreaScopeFields } from './UserAreaScopeEditor'

const ROLE_LABELS: Record<UserRole, string> = {
  admin: '系统管理员',
  analyst: '研判人员',
  viewer: '只读查看',
}

export default function UserManagement() {
  const { user, sessionEpoch } = useAuth()
  const [form] = Form.useForm<UserCreatePayload>()
  const [editing, setEditing] = useState<AuthUser | null>(null)
  const [visible, setVisible] = useState(false)
  const [scopeAccount, setScopeAccount] = useState<AuthUser | null>(null)
  const selectedRole = Form.useWatch('role', form)
  const queryClient = useQueryClient()

  const usersQuery = useQuery({
    queryKey: ['auth-users', user?.id, sessionEpoch],
    queryFn: authApi.users.list,
  })
  const areas = useQuery({ queryKey: ['setup-areas', user?.id, user?.role, sessionEpoch], queryFn: mapFoundationApi.listAreas })

  const createMutation = useMutation({
    mutationFn: authApi.users.create,
    onSuccess: () => {
      message.success('用户已创建')
      setVisible(false)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['auth-users'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<UserCreatePayload> & { is_active?: boolean } }) =>
      authApi.users.update(id, payload),
    onSuccess: () => {
      message.success('用户信息已更新')
      setVisible(false)
      setEditing(null)
      form.resetFields()
      queryClient.invalidateQueries({ queryKey: ['auth-users'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ role: 'analyst', area_scopes: [] })
    setVisible(true)
  }

  const openEdit = (record: AuthUser) => {
    setEditing(record)
    form.setFieldsValue({
      username: record.username,
      display_name: record.display_name,
      role: record.role,
      password: '',
    })
    setVisible(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (editing) {
      const payload = {
        display_name: values.display_name,
        role: values.role,
        ...(values.password ? { password: values.password } : {}),
      }
      updateMutation.mutate({ id: editing.id, payload })
    } else {
      if (areas.isError || !areas.data) { message.error('请先成功读取厂区范围'); return }
      createMutation.mutate({ ...values, area_scopes: values.role === 'admin' ? [] : (values.area_scopes || []) })
    }
  }

  return (
    <div className="page page-scrollable">
      <div className="page-title">
        <h1>用户与权限</h1>
        <span className="sub">ACCOUNT · ROLE · ACCESS CONTROL</span>
      </div>
      <div className="card">
        <div className="card-head">
          <UserSwitchOutlined className="ico" />
          <span className="ti">系统账号</span>
          <span className="spacer" />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增用户</Button>
        </div>
        <div className="card-body scroll">
          {usersQuery.isError && <Alert type="error" message="账号读取失败" action={<Button onClick={() => void usersQuery.refetch()}>重试</Button>} />}
          <Table<AuthUser>
            rowKey="id"
            loading={usersQuery.isLoading}
            dataSource={usersQuery.isError ? [] : usersQuery.data || []}
            pagination={false}
            columns={[
              { title: '用户名', dataIndex: 'username' },
              { title: '显示名称', dataIndex: 'display_name' },
              {
                title: '角色',
                dataIndex: 'role',
                render: (role: UserRole) => <Tag color={role === 'admin' ? 'gold' : role === 'analyst' ? 'blue' : 'default'}>{ROLE_LABELS[role]}</Tag>,
              },
              {
                title: '状态',
                dataIndex: 'is_active',
                render: (active: boolean, record) => (
                  <Switch
                    size="small"
                    checked={active}
                    disabled={record.id === user?.id}
                    onChange={(checked) => updateMutation.mutate({ id: record.id, payload: { is_active: checked } })}
                  />
                ),
              },
              {
                title: '最后登录',
                dataIndex: 'last_login_at',
                render: (value?: string) => value ? new Date(value).toLocaleString('zh-CN') : '尚未登录',
              },
              {
                title: '操作',
                render: (_, record) => (
                  <Space>
                    <Button size="small" icon={<KeyOutlined />} onClick={() => openEdit(record)}>编辑 / 重置密码</Button>
                    <Button size="small" onClick={() => setScopeAccount(record)}>资料范围</Button>
                    {record.id !== user?.id && record.is_active && (
                      <Popconfirm
                        title="确认停用该账号？"
                        onConfirm={() => updateMutation.mutate({ id: record.id, payload: { is_active: false } })}
                      >
                        <Button size="small" danger>停用</Button>
                      </Popconfirm>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </div>
      </div>

      <Modal
        okText="保存用户"
        cancelText="取消"
        title={editing ? '编辑用户' : '新增用户'}
        open={visible}
        onCancel={() => setVisible(false)}
        onOk={submit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        destroyOnClose
      >
        <Form form={form} layout="vertical" requiredMark={false}>
          <Form.Item label="用户名" name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input disabled={Boolean(editing)} maxLength={64} />
          </Form.Item>
          <Form.Item label="显示名称" name="display_name">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="角色" name="role" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }))} />
          </Form.Item>
          {!editing && (selectedRole === 'admin' ? <Alert type="info" message="系统管理员能够管理全部厂区" /> : <>
            <Alert type="info" message="明确选择资料范围；未分配范围的账号不能访问厂区业务资料。" />
            {areas.isError ? <Alert type="error" message="厂区读取失败" action={<Button onClick={() => void areas.refetch()}>重试</Button>} /> :
              <AreaScopeFields areas={areas.data || []} />}
          </>)}
          <Form.Item
            label={editing ? '重置密码（留空则不修改）' : '初始密码'}
            name="password"
            rules={editing ? [] : [{ required: true, message: '请输入初始密码' }, { min: 12, message: '密码至少 12 位' }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
      {scopeAccount && <UserAreaScopeEditor key={scopeAccount.id} account={scopeAccount} close={() => setScopeAccount(null)} />}
    </div>
  )
}
