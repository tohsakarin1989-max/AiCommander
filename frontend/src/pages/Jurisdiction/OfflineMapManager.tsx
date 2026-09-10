import { Alert, Button, Card, Select, Space, Steps, Tag, Upload, message } from 'antd'
import { CloudUploadOutlined, RollbackOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { mapFoundationApi } from '../../services'


export default function OfflineMapManager() {
  const queryClient = useQueryClient()
  const [areaId, setAreaId] = useState<number>()
  const [bundleId, setBundleId] = useState<number>()

  const areasQuery = useQuery({ queryKey: ['operational-areas'], queryFn: mapFoundationApi.listAreas })
  const bundlesQuery = useQuery({ queryKey: ['offline-map-bundles'], queryFn: mapFoundationApi.listOfflineBundles })
  const snapshotsQuery = useQuery({
    queryKey: ['offline-map-snapshots', areaId],
    queryFn: () => mapFoundationApi.listSnapshots(areaId),
    enabled: areaId != null,
  })

  useEffect(() => {
    if (!areaId && areasQuery.data?.length) {
      setAreaId((areasQuery.data.find(item => item.is_default) || areasQuery.data[0]).id)
    }
  }, [areaId, areasQuery.data])

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['offline-map-bundles'] })
    void queryClient.invalidateQueries({ queryKey: ['offline-map-snapshots'] })
  }

  const importMutation = useMutation({
    mutationFn: mapFoundationApi.importOfflineBundle,
    onSuccess: bundle => {
      refresh()
      setBundleId(bundle.id)
      message.success(bundle.idempotent_replay ? '该地图包已校验过，未重复导入' : '公共地图更新包已校验并进入内网')
    },
    onError: () => message.error('地图包校验失败，当前离线地图未改变'),
  })
  const buildMutation = useMutation({
    mutationFn: () => {
      if (!areaId || !bundleId) throw new Error('请选择厂区和地图包')
      return mapFoundationApi.buildSnapshot(areaId, bundleId)
    },
    onSuccess: () => {
      refresh()
      message.success('新离线地图已构建，发布前不影响普通用户')
    },
    onError: () => message.error('地图构建失败，上一有效版本继续使用'),
  })
  const publishMutation = useMutation({
    mutationFn: mapFoundationApi.publishSnapshot,
    onSuccess: () => {
      refresh()
      message.success('离线地图版本已发布')
    },
    onError: () => message.error('发布失败，当前地图版本未改变'),
  })
  const rollbackMutation = useMutation({
    mutationFn: mapFoundationApi.rollbackSnapshot,
    onSuccess: () => {
      refresh()
      message.success('已切回所选离线地图版本')
    },
    onError: () => message.error('回滚失败，请检查离线瓦片文件'),
  })

  const snapshots = snapshotsQuery.data ?? []
  const current = snapshots.find(item => item.status === 'current')
  const ready = snapshots.find(item => item.status === 'ready')

  return (
    <Card className="jurisdiction-card offline-map-manager" title="真正离线厂区地图" extra={<Tag color={current ? 'green' : 'orange'}>{current ? '离线可用' : '待发布'}</Tag>}>
      <Alert
        showIcon
        type="info"
        message="浏览器缓存只用于加速；正式底图由内网 MBTiles 服务提供"
        description="联网区地图包只含公共道路、村屯、水系和边界；重点井、管线和技防位置只在内网合并。"
      />
      <Steps
        size="small"
        current={current ? 3 : ready ? 2 : bundleId ? 1 : 0}
        items={[{ title: '验包' }, { title: '选择厂区' }, { title: '构建' }, { title: '发布' }]}
      />
      <div className="offline-map-manager__controls">
        <Upload
          accept=".zip"
          maxCount={1}
          showUploadList={false}
          beforeUpload={file => {
            importMutation.mutate(file)
            return false
          }}
        >
          <Button icon={<CloudUploadOutlined />} loading={importMutation.isPending}>导入受控地图包</Button>
        </Upload>
        <Select
          placeholder="选择厂区"
          value={areaId}
          options={(areasQuery.data ?? []).map(item => ({ value: item.id, label: item.name }))}
          onChange={value => setAreaId(value)}
        />
        <Select
          placeholder="选择已验地图包"
          value={bundleId}
          options={(bundlesQuery.data ?? []).map(item => ({ value: item.id, label: `${item.provider} · ${item.source_version}` }))}
          onChange={value => setBundleId(value)}
        />
        <Button type="primary" disabled={!areaId || !bundleId} loading={buildMutation.isPending} onClick={() => buildMutation.mutate()}>
          构建新版本
        </Button>
      </div>
      <div className="offline-map-manager__versions">
        {snapshots.map(item => (
          <div key={item.id}>
            <span><strong>{item.version}</strong><small>{item.status === 'current' ? '当前使用' : item.status === 'ready' ? '待发布' : '历史版本'}</small></span>
            <Space>
              <Tag color={item.status === 'current' ? 'green' : item.status === 'ready' ? 'blue' : 'default'}>{item.status}</Tag>
              {item.status === 'ready' && <Button size="small" onClick={() => publishMutation.mutate(item.id)}>发布</Button>}
              {item.status === 'superseded' && <Button size="small" icon={<RollbackOutlined />} onClick={() => rollbackMutation.mutate(item.id)}>回滚</Button>}
            </Space>
          </div>
        ))}
        {!snapshots.length && <span className="jurisdiction-muted">该厂区尚未构建离线地图版本。</span>}
      </div>
    </Card>
  )
}
