import { useRef } from 'react'
import { Alert, Button, Form, Modal, Select, Space, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi, type AuthUser, type AreaScopeGrant } from '../../services/auth'
import { mapFoundationApi, type OperationalArea } from '../../services/mapFoundation'
import { useAuth } from '../../auth/AuthContext'

export function AreaScopeFields({ areas }: { areas: OperationalArea[] }) {
  return <Form.List name="area_scopes">{(fields, { add, remove }) => <>
    {fields.map(field => <Space key={field.key} align="baseline" wrap>
      <Form.Item name={[field.name, 'operational_area_id']} label="厂区" rules={[{ required: true, message: '请选择厂区' }]}>
        <Select style={{ width: 220 }} showSearch optionFilterProp="label" options={areas.map(area => ({ value: area.id, label: `${area.name}${area.status === 'active' ? '' : '（停用，须移除）'}`, disabled: area.status !== 'active' }))} />
      </Form.Item>
      <Form.Item name={[field.name, 'access_level']} label="范围权限" rules={[{ required: true, message: '请选择权限' }]}>
        <Select style={{ width: 130 }} options={[{ value: 'read', label: '只读' }, { value: 'write', label: '读写' }, { value: 'manage', label: '管理' }]} />
      </Form.Item><Button danger onClick={() => remove(field.name)}>移除</Button>
    </Space>)}
    <Button onClick={() => add({ access_level: 'read' })}>添加厂区范围</Button>
  </>}</Form.List>
}

export default function UserAreaScopeEditor({ account, close }: { account: AuthUser; close: () => void }) {
  const { user, sessionEpoch } = useAuth()
  const [form] = Form.useForm<{ area_scopes: AreaScopeGrant[] }>()
  const client = useQueryClient()
  const scopes = useQuery({ queryKey: ['user-area-scopes', user?.id, sessionEpoch, account.id], queryFn: () => authApi.users.scopes(account.id),
    gcTime: 0, refetchOnMount: 'always', refetchOnWindowFocus: false, refetchOnReconnect: false })
  const areas = useQuery({ queryKey: ['setup-areas', user?.id, user?.role, sessionEpoch], queryFn: mapFoundationApi.listAreas })
  // Freeze the same snapshot as the form; a later refetch must not bless old
  // form values with a newer authorization baseline.
  const initialScopes = useRef<AreaScopeGrant[]>()
  const ready = !scopes.isFetching && !scopes.isError && !areas.isError && scopes.data != null && areas.data != null
  if (ready && initialScopes.current === undefined) initialScopes.current = scopes.data.map(({ operational_area_id, access_level }) => ({ operational_area_id, access_level }))
  const save = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields()
      if (!ready || !initialScopes.current) throw new Error('请先成功读取最新授权')
      return authApi.users.replaceScopes(account.id, values.area_scopes || [], initialScopes.current)
    },
    onSuccess: () => { void client.invalidateQueries(); message.success('范围已保存，后续读取按新范围校验'); close() },
    onError: (error: Error) => message.error(error.message),
  })
  return <Modal title={`${account.display_name} · 资料范围`} okText="保存范围" cancelText="取消" open onCancel={close} onOk={() => save.mutate()}
    confirmLoading={save.isPending} okButtonProps={{ disabled: !ready || account.role === 'admin' }}>
    {account.role === 'admin' ? <Alert type="info" message="系统管理员能够管理全部厂区" description="不能用厂区授权将管理员限制为普通业务人员；请使用研判人员或只读账号。" /> : <>
      <Alert type="warning" message="角色与厂区权限共同生效" description="只读角色不会因配置读写范围而获得写入能力。移除全部范围后，该账号不能访问任何厂区业务资料。" />
      {(scopes.isError || areas.isError) ? <Alert type="error" message="授权读取失败，不能保存空范围代替原配置" action={<Button onClick={() => { void scopes.refetch(); void areas.refetch() }}>重试</Button>} /> :
        ready ? <Form form={form} layout="vertical" initialValues={{ area_scopes: initialScopes.current }}><AreaScopeFields areas={areas.data} /></Form> : <p role="status">正在读取范围…</p>}
    </>}
  </Modal>
}
