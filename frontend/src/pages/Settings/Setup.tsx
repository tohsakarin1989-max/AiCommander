import { useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space, Table, Tag, message } from 'antd'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { mapFoundationApi, type OperationalArea } from '../../services/mapFoundation'

export function setupDestination(path: string, areaId?: number, hash = '') {
  return `${path}${areaId == null ? '' : `?operational_area_id=${areaId}`}${hash}`
}

export default function Setup() {
  const { user, sessionEpoch } = useAuth()
  const client = useQueryClient()
  const [areaId, setAreaId] = useState<number>()
  const [editor, setEditor] = useState<OperationalArea | 'new' | null>(null)
  const [form] = Form.useForm<{ code: string; name: string }>()
  const identity = [user?.id, user?.role, sessionEpoch]
  const areas = useQuery({ queryKey: ['setup-areas', ...identity], queryFn: mapFoundationApi.listAreas })
  const available = areas.isError ? [] : (areas.data || [])
  const selectedId = available.some(area => area.id === areaId) ? areaId
    : available.find(area => area.is_default && area.status === 'active')?.id
  const sources = useQuery({ queryKey: ['setup-sources', ...identity], queryFn: mapFoundationApi.listSources })
  const snapshots = useQuery({ queryKey: ['setup-snapshots', ...identity, selectedId],
    queryFn: () => mapFoundationApi.listSnapshots(selectedId), enabled: selectedId != null })
  const refresh = () => { void client.invalidateQueries({ queryKey: ['setup-areas'] }); void client.invalidateQueries({ queryKey: ['map-foundation-areas'] }) }
  const save = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields()
      if (editor === 'new') return mapFoundationApi.createArea(values)
      if (!editor) throw new Error('请选择厂区')
      return mapFoundationApi.updateArea(editor.id, { name: values.name })
    },
    onSuccess: () => { refresh(); setEditor(null); message.success('厂区已保存，已有资料和账号范围未移动') },
    onError: (error: Error) => message.error(error.message),
  })
  const makeDefault = useMutation({
    mutationFn: (id: number) => mapFoundationApi.updateArea(id, { is_default: true }),
    onSuccess: () => { refresh(); message.success('默认厂区已更新；已有账号范围未改变') },
    onError: (error: Error) => message.error(error.message),
  })
  const sourceRows = sources.isError ? [] : (sources.data || []).filter(source => source.operational_area.id === selectedId)
  const currentMap = snapshots.isError ? undefined : snapshots.data?.find(snapshot => snapshot.status === 'current')
  const edit = (area: OperationalArea | 'new') => {
    setEditor(area); form.resetFields(); form.setFieldsValue(area === 'new' ? {} : { code: area.code, name: area.name })
  }
  return <div className="page page-scrollable">
    <div className="page-title"><h1>首次启用</h1><span className="sub">先明确资料属于哪里、谁可以使用，再开始录入</span></div>
    <Alert type="info" showIcon message="这里读取实际配置，不会自动导入、改写或重新分析业务数据。"
      description="模型可以稍后配置。地图已发布仅表示有版本记录，不代替断网打开地图的实际检查。" />
    <section className="card" style={{ marginTop: 16 }}>
      <div className="card-head"><h2 className="ti">1. 厂区与辖区</h2><span className="spacer" /><Button onClick={() => edit('new')}>新增厂区</Button></div>
      <div className="card-body">
        <p>尚未录入正式资料时，可将“默认厂区”更名为实际单位；更名保留稳定编号，不移动原有数据。更换默认厂区不会重新分配已有账号。</p>
        {areas.isError ? <Alert type="error" message="厂区读取失败" action={<Button onClick={() => void areas.refetch()}>重试</Button>} /> :
          <Table rowKey="id" size="small" loading={areas.isPending} dataSource={available} pagination={false} columns={[
            { title: '厂区', dataIndex: 'name' }, { title: '编码', dataIndex: 'code' },
            { title: '状态', render: (_, area) => <Space><Tag>{area.status === 'active' ? '启用' : '停用'}</Tag>{area.is_default && <Tag color="green">默认</Tag>}</Space> },
            { title: '操作', render: (_, area) => <Space><Button size="small" onClick={() => edit(area)}>更名</Button><Button size="small" disabled={area.is_default || area.status !== 'active' || makeDefault.isPending} onClick={() => makeDefault.mutate(area.id)}>设为默认</Button></Space> },
          ]} />}
      </div>
    </section>
    <section className="card"><div className="card-head"><h2 className="ti">2. 账号与范围</h2></div><div className="card-body">
      <p>为录入人员、查看人员明确分配厂区；角色权限与厂区权限共同生效。系统管理员能够管理全部厂区，不作为限域业务账号使用。</p>
      <Link className="btn-primary" to="/settings/users">配置用户与资料范围</Link>
    </div></section>
    <section className="card"><div className="card-head"><h2 className="ti">3. 地图与首批台账</h2></div><div className="card-body">
      <label htmlFor="setup-area">检查厂区 </label><Select id="setup-area" style={{ minWidth: 220 }} value={selectedId} onChange={setAreaId}
        options={available.filter(area => area.status === 'active').map(area => ({ value: area.id, label: area.name }))} placeholder="先建立厂区" />
      {selectedId == null ? <p>暂无可检查的厂区；请先完成上方配置。</p> : <>
        <p>{snapshots.isPending ? '正在读取地图版本…' : snapshots.isError ? '地图版本读取失败，不能确认是否可用。' : currentMap ? `当前地图：${currentMap.version}` : '尚无已发布地图；案件文字录入不受影响。'}</p>
        {snapshots.isError && <Button onClick={() => void snapshots.refetch()}>重读地图版本</Button>}
        <p>{sources.isPending ? '正在读取台账来源…' : sources.isError ? '台账来源读取失败，不能当成没有资料。' : sourceRows.length ? `已登记来源：${sourceRows.map(source => source.name).join('、')}` : '尚未登记台账来源；请先配置来源、坐标系及字段模板，再预览导入。'}</p>
        {sources.isError && <Button onClick={() => void sources.refetch()}>重读来源</Button>}
      </>}
      <Space wrap><Link to={setupDestination('/jurisdiction', selectedId, '#offline-map-management')}>导入与发布离线地图</Link><Link to={setupDestination('/jurisdiction', selectedId, '#map-source-management')}>登记首批台账</Link><Link to={setupDestination('/cases/map', selectedId)}>打开业务地图检查</Link></Space>
    </div></section>
    <section className="card"><div className="card-head"><h2 className="ti">4. 开始日常工作</h2></div><div className="card-body">
      <p>管理员确认配置后，请用实际业务角色检查录入、查阅、地图与材料。缺少模型或道路资料要保留未启用提示，不影响基础录入。</p>
      <Link className="btn-primary" to="/workbench">进入日常工作</Link>
    </div></section>
    <Modal title={editor === 'new' ? '新增厂区' : '厂区更名'} okText="保存" cancelText="取消" open={editor != null} onCancel={() => setEditor(null)} onOk={() => save.mutate()} confirmLoading={save.isPending}>
      <Form form={form} layout="vertical"><Form.Item name="code" label="稳定编码" rules={[{ required: true, whitespace: true, message: '请输入厂区编码' }]}><Input disabled={editor !== 'new'} maxLength={64} /></Form.Item>
        <Form.Item name="name" label="厂区名称" rules={[{ required: true, whitespace: true, message: '请输入厂区名称' }]}><Input maxLength={200} /></Form.Item></Form>
    </Modal>
  </div>
}
