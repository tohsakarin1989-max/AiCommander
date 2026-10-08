import { useState } from 'react'
import { Alert, Button, Input } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '../../auth/AuthContext'
import { jurisdictionApi } from '../../services/jurisdiction'
import { facilityEntryPatch, facilityHasUsablePoint } from './caseEntryAssistance'

export default function CaseFacilityPicker({ areaId, disabled, onApply }: {
  areaId?: number; disabled: boolean; onApply: (patch: Record<string, unknown>) => void
}) {
  const { user, sessionEpoch } = useAuth()
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const result = useQuery({ queryKey: ['case-facility-choice', user?.id, sessionEpoch, areaId, search, offset],
    enabled: open && areaId !== undefined && Boolean(search), retry: false,
    queryFn: () => jurisdictionApi.listAssets({ operational_area_id: areaId, keyword: search, status: 'active', skip: offset, limit: 21 }) })
  const rows = result.isSuccess ? result.data : []
  return <details className="case-entry-section" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>从授权设施目录复用地点（可选）</summary>
    {open && <>
      <p>按井名、编号或地址查找。同名设施请核对编号与厂区。只复用地点资料，不自动建立涉案关联，也不填入时间、油量或人员。</p>
      <Input.Search aria-label="查找录入地点设施" placeholder="输入井名、编号或地址" value={keyword} maxLength={200}
        disabled={disabled || areaId === undefined} onChange={event => setKeyword(event.target.value)}
        onSearch={value => { setSearch(value.trim()); setOffset(0) }} enterButton="查找设施" />
      {areaId === undefined && <p>请先选择本案所属厂区。</p>}
      {result.isFetching && <p role="status">正在查找授权设施…</p>}
      {result.isError && <Alert type="error" message="设施读取失败或权限已变化；未使用旧结果，可稍后重新查找。" />}
      {search && result.isSuccess && rows.length === 0 && <p>当前条件下没有匹配设施，可继续手工填写地点。</p>}
      {rows.slice(0, 20).map(asset => <div key={asset.id} className="case-facility-choice">
        <div><strong>{asset.name}</strong><p>编号：{asset.external_id || `系统编号 ${asset.id}`} · 所属厂区 #{asset.operational_area_id} · {asset.verified ? '已核验' : '未核验'}{asset.address ? ` · ${asset.address}` : ''}</p></div>
        <Button size="small" disabled={disabled} onClick={() => onApply(facilityEntryPatch(asset))}>使用地点文字</Button>
        {facilityHasUsablePoint(asset) && <Button size="small" disabled={disabled} onClick={() => onApply(facilityEntryPatch(asset, true))}>位置已核对，使用地点与坐标</Button>}
      </div>)}
      {search && <div className="case-entry-actions"><Button disabled={disabled || !offset || result.isFetching} onClick={() => setOffset(value => Math.max(0, value - 20))}>上一页设施</Button>
        <span>第 {offset / 20 + 1} 页</span><Button disabled={disabled || rows.length <= 20 || result.isFetching} onClick={() => setOffset(value => value + 20)}>下一页设施</Button></div>}
    </>}
  </details>
}
