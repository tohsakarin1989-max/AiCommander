import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Select, Space, Tag, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBlocker } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { mapFoundationApi } from '../../services'
import OfflineMapManager from './OfflineMapManager'
import InternalRoadManager from './InternalRoadManager'
import MapReadinessPanel from './MapReadinessPanel'
import MapLedgerPanel from './MapLedgerPanel'
import MapDataIssueWork from './MapDataIssueWork'

function GovernanceWorkspace({ initialAreaId }: { initialAreaId?: number }) {
  const { user, sessionEpoch } = useAuth(), queryClient = useQueryClient()
  const [sourceForm] = Form.useForm()
  const [selectedSourceId, setSelectedSourceId] = useState<number>()
  const [ledgerDirty, setLedgerDirty] = useState(false)
  const appliedArea = useRef<number>(), mounted = useRef(true)
  const blocker = useBlocker(ledgerDirty)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm('台账页面还有未保存配置、所选文件或未确认的修正请求。离开将丢失本页输入，服务器已保存的批次仍可找回。确认已核对并离开吗？')) blocker.proceed()
    else blocker.reset()
  }, [blocker])
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    if (!ledgerDirty) return
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard)
  }, [ledgerDirty])
  const dirtyChanged = useCallback((dirty: boolean) => setLedgerDirty(dirty), [])
  const sourcesQuery = useQuery({ queryKey: ['map-foundation-sources', user?.id, sessionEpoch], queryFn: mapFoundationApi.listSources, gcTime: 0 })
  const areasQuery = useQuery({ queryKey: ['map-maintenance-areas', user?.id, sessionEpoch], queryFn: async () => (await mapFoundationApi.maintenanceScope()).areas, gcTime: 0 })
  const conflictsQuery = useQuery({ queryKey: ['map-foundation-conflicts', user?.id, sessionEpoch], queryFn: mapFoundationApi.listConflicts, gcTime: 0 })
  const sources = sourcesQuery.isSuccess ? sourcesQuery.data : []
  const areas = areasQuery.isSuccess ? areasQuery.data : []
  useEffect(() => {
    if (initialAreaId != null && appliedArea.current !== initialAreaId && areas.some(item => item.id === initialAreaId)) {
      sourceForm.setFieldValue('operational_area_id', initialAreaId); appliedArea.current = initialAreaId
    } else if (!sourceForm.getFieldValue('operational_area_id') && areas.length) {
      sourceForm.setFieldValue('operational_area_id', (areas.find(item => item.is_default) || areas[0]).id)
    }
  }, [areasQuery.data, sourceForm, initialAreaId])
  const refresh = useCallback(() => {
    for (const key of ['map-foundation-conflicts', 'jurisdiction-assets', 'jurisdiction-summary', 'map-readiness', 'facility-dossier']) {
      void queryClient.invalidateQueries({ queryKey: [key] })
    }
  }, [queryClient])
  const createSource = useMutation({ mutationFn: mapFoundationApi.createSource,
    onSuccess: source => {
      if (!mounted.current) return
      void queryClient.invalidateQueries({ queryKey: ['map-foundation-sources'] })
      setSelectedSourceId(source.id); sourceForm.resetFields(); message.success('来源已登记，请明确模板后预览文件')
    }, onError: () => { if (mounted.current) message.error('来源未保存，输入仍保留；请检查来源标识、权限或网络后重试') } })
  const resolve = useMutation({ mutationFn: ({ id, decision }: { id: number; decision: 'reject' | 'retry' }) => mapFoundationApi.resolveConflict(id, decision),
    onSuccess: () => { if (mounted.current) { refresh(); message.success('旧异常记录状态已更新；标记待重导不会自动写入设施') } },
    onError: () => { if (mounted.current) message.error('异常状态更新未确认，请刷新后核对') } })
  return <>
    {user?.role === 'admin' && <><MapReadinessPanel />
      <div id="offline-map-management"><OfflineMapManager initialAreaId={initialAreaId} /></div>
      <div id="internal-road-management"><InternalRoadManager sources={sources} /></div></>}
    <Card id="map-source-management" className="jurisdiction-card map-governance-card" title="生产台账整理与更新" extra={<Tag>授权范围内资料维护</Tag>}>
      <Alert showIcon type="info" message="首次确认来源与模板，以后只核对变化和异常"
        description="原件、工作表、原列、行号和来源修订保留。公共参考不能覆盖内网核验，未知坐标系不猜测，不按名称自动合并设施。" />
      {sourcesQuery.isError && <Alert type="error" message="来源读取失败，未展示旧缓存。" action={<Button onClick={() => void sourcesQuery.refetch()}>重试</Button>} />}
      <Space wrap style={{ margin: '16px 0', width: '100%' }}>
        <Select aria-label="生产台账数据来源" allowClear style={{ minWidth: 280 }} value={selectedSourceId} placeholder="选择已登记来源" loading={sourcesQuery.isPending}
          options={sources.map(item => ({ value: item.id, label: `${item.name} · ${item.source_key} · ${item.operational_area.name}` }))}
          onChange={value => {
            if (ledgerDirty && !window.confirm('切换来源将清除本页未保存输入或未确认请求。请先核对当前批次；确认仍要切换吗？')) return
            setSelectedSourceId(value); setLedgerDirty(false)
          }} />
        <span>已登记来源 {sources.length}</span>
      </Space>
      <details><summary>登记新的台账来源（保留原来源优先级规则）</summary>
        <Form name="map-source-create" form={sourceForm} layout="vertical" style={{ maxWidth: 560 }} initialValues={{ source_type: 'ledger', trust_rank: 100 }}
          disabled={createSource.isPending || ledgerDirty} onFinish={values => createSource.mutate(values)}>
          <Form.Item name="name" label="来源名称" rules={[{ required: true }]}><Input placeholder="例如：生产井主台账" /></Form.Item>
          <Form.Item name="source_key" label="稳定来源标识" rules={[{ required: true }]}><Input placeholder="例如 production-well-ledger" /></Form.Item>
          <Form.Item name="operational_area_id" label="所属厂区" rules={[{ required: true }]}>
            <Select placeholder="选择授权厂区" options={areas.map(item => ({ value: item.id, label: item.name }))} />
          </Form.Item>
          {areasQuery.isError && <Alert type="error" message="厂区读取失败，请刷新后再登记。" />}
          <Form.Item name="source_type" label="来源类型"><Select options={[
            { value: 'ledger', label: '内部生产台账' }, { value: 'manual', label: '人工核验数据' },
            { value: 'internal_gis', label: '内部 GIS' }, { value: 'public_map', label: '公共地图参考' },
          ]} /></Form.Item>
          <Form.Item name="trust_rank" label="来源优先级"><InputNumber min={0} max={100} /></Form.Item>
          <Button htmlType="submit" loading={createSource.isPending}>保存来源</Button>
        </Form>
      </details>
      {selectedSourceId && sources.some(source => source.id === selectedSourceId)
        ? <MapLedgerPanel key={selectedSourceId} sourceId={selectedSourceId} onChanged={refresh} onDirtyChange={dirtyChanged} />
        : <p>先选择来源。首份文件可先查看表头，再确认坐标、单位和生产属性映射。</p>}
      {conflictsQuery.isSuccess && conflictsQuery.data.length > 0 && <details><summary>旧版异常隔离区（{conflictsQuery.data.length}），原入口保留</summary>
        <p>新批次请优先从最近批次逐行修正。旧“标记待重导”只改变状态，仍需重新导入；不等于异常已修复。</p>
        {conflictsQuery.data.map(item => <div key={item.id} style={{ margin: '12px 0' }}>
          第 {item.row_number} 行 · {item.source_record_id || '无来源编号'} · {item.error_message}
          <Space><Button disabled={resolve.isPending} onClick={() => resolve.mutate({ id: item.id, decision: 'retry' })}>标记待重导</Button>
            <Button danger disabled={resolve.isPending} onClick={() => { if (window.confirm('确认驳回这条旧异常声明？此操作不会删除原始来源记录。')) resolve.mutate({ id: item.id, decision: 'reject' }) }}>驳回</Button></Space>
        </div>)}
      </details>}
      {conflictsQuery.isError && <Alert type="warning" message="旧异常隔离区读取失败，请稍后刷新；不代表没有异常。" />}
      <MapDataIssueWork key={selectedSourceId || 'all'} sourceId={selectedSourceId} />
    </Card>
  </>
}

export default function MapDataGovernance(props: { initialAreaId?: number } = {}) {
  const { user, sessionEpoch } = useAuth()
  const permission = useQuery({ queryKey: ['map-maintenance-scope', user?.id, sessionEpoch],
    queryFn: mapFoundationApi.maintenanceScope, enabled: user?.role === 'analyst', retry: false, gcTime: 0 })
  return user?.role === 'admin' || (permission.isSuccess && permission.data.areas.length > 0)
    ? <GovernanceWorkspace key={`${user?.id}:${sessionEpoch}`} {...props} /> : null
}
