import { useState } from 'react'
import { Button, InputNumber, Select } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { spatialCoverageApi, type CoverageResult, type CoverageSummary } from '../../services/spatialCoverage'
import './SpatialCoveragePanel.css'
import CoverageRoadPanel from './CoverageRoadPanel'
import CoverageGeometryMap from './CoverageGeometryMap'

const METRICS: [keyof Pick<CoverageSummary, 'target_count' | 'covered_count' | 'overlap_count' | 'unknown_count' | 'outside_known_count'>, string][] = [
  ['target_count', '登记井点'], ['covered_count', '名义覆盖井点'],
  ['overlap_count', '其中重复覆盖'], ['outside_known_count', '登记范围外'], ['unknown_count', '覆盖未知'],
]

const STATE_LABELS: Record<string, string> = {
  usable: '资料可用', excluded_inactive: '已停用', excluded_offline: '离线',
  unknown_outside_validity: '来源有效期不适用', unknown_status_expired: '状态过期',
  unknown_status_validity: '缺状态有效期', unknown_operational_status: '状态未知',
  unknown_coordinate: '坐标待核', unknown_coverage_radius: '缺覆盖范围',
  excluded_by_scenario: '方案排除',
}

export default function SpatialCoveragePanel() {
  const [result, setResult] = useState<CoverageResult | null>(null)
  const [recent, setRecent] = useState<string[]>([])
  const [disabled, setDisabled] = useState<number[]>([])
  const [moved, setMoved] = useState<number | undefined>()
  const [latitude, setLatitude] = useState<number | null>(null)
  const [longitude, setLongitude] = useState<number | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [draftChanged, setDraftChanged] = useState(false)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const history = useQuery({ queryKey: ['spatial-comparison-history', historyPage],
    queryFn: () => spatialCoverageApi.list(historyPage), enabled: historyOpen, retry: false, staleTime: 0 })

  const run = async (baseline = false) => {
    setPending(true)
    setError('')
    // Never leave an earlier successful result looking like this request's output.
    setResult(null)
    try {
      const next = await spatialCoverageApi.compare({
        disabled_resource_ids: baseline ? [] : disabled,
        movements: !baseline && moved !== undefined && latitude !== null && longitude !== null
          ? [{ resource_id: moved, latitude, longitude }] : [],
      })
      setResult(next)
      setRecent(current => [next.id, ...current.filter(id => id !== next.id)].slice(0, 10))
      setDraftChanged(false)
      if (historyOpen) void history.refetch()
      if (baseline) { setDisabled([]); setMoved(undefined); setLatitude(null); setLongitude(null) }
    } catch {
      setError('计算未完成。请检查访问权限、登记资料或稍后重试；未返回替代结果。')
    } finally { setPending(false) }
  }

  const openHistory = async (id: string) => {
    setPending(true); setError(''); setResult(null)
    try {
      setResult(await spatialCoverageApi.get(id))
      setDisabled([]); setMoved(undefined); setLatitude(null); setLongitude(null); setDraftChanged(false)
    } catch { setError('历史方案不存在、校验失败或来源权限已变化，不能展示旧结果。') }
    finally { setPending(false) }
  }

  const incompleteMovement = moved !== undefined && (latitude === null || longitude === null)
  return <section className="sw-coverage" aria-label="空间覆盖方案比较" aria-busy={pending}>
    <header><div><h2>空间覆盖方案比较</h2><p>自动读取当前辖区登记井与设备，查看资源变化影响。不生成执行任务。</p></div>
      <Button onClick={() => void run(true)} disabled={pending}>计算当前覆盖</Button></header>
    {pending && <p role="status">正在读取授权资源并计算，请稍候…</p>}
    {error && <p role="alert">{error}</p>}
    {!result && !pending && !error && <p>仅当需要比较方案时运行。坐标、覆盖范围和设备状态缺失时保留“未知”，不自动补齐。</p>}
    <details onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>历史方案目录</summary>
      {history.isFetching && <p role="status">正在读取授权目录…</p>}
      {history.isError && <p role="alert">历史目录读取失败，请重试。</p>}
      {historyOpen && !history.isFetching && !history.isError && history.data && <>
        <ul>{history.data.items.map(item => <li key={item.id}>
          <Button type="link" disabled={pending} onClick={() => void openHistory(item.id)}>
            {new Date(item.created_at).toLocaleString('zh-CN')} · 辖区 {item.operational_area_id} · {item.id.slice(0, 8)}
          </Button></li>)}</ul>
        {!history.data.items.length && <p>当前授权范围内没有保存的方案。</p>}
        <div className="sw-coverage-road-actions"><Button disabled={historyPage <= 1 || history.isFetching} onClick={() => setHistoryPage(value => value - 1)}>上一页</Button>
          <span>第 {historyPage} 页，共 {history.data.total} 条</span>
          <Button disabled={historyPage * 10 >= history.data.total || history.isFetching} onClick={() => setHistoryPage(value => value + 1)}>下一页</Button></div>
      </>}
      <Button disabled={history.isFetching} onClick={() => void history.refetch()}>刷新历史目录</Button>
      <p>目录不包含覆盖结果，打开方案时再次检查当前来源权限。</p>
    </details>
    {recent.length > 0 && <label className="sw-coverage-history">本次访问保存的方案
      <Select aria-label="查看已保存方案" placeholder="重新检查权限后查看" value={result?.historical ? result.id : undefined}
        disabled={pending} options={recent.map((id, index) => ({ value: id, label: `方案 ${recent.length - index} · ${id.slice(0, 8)}` }))}
        onChange={id => void openHistory(id)} /></label>}
    {result && <>
      <p className="sw-coverage-context">辖区 {result.input_snapshot.area_id} · {new Date(result.input_snapshot.as_of).toLocaleString('zh-CN')} · 已保存</p>
      {result.historical && <p role="status">历史结果：{result.freshness === 'unchanged_inputs' ? '输入未变更' : result.freshness === 'conditions_expired' ? '条件已过期' : '来源已变化或需重新计算'}。{result.history_boundary}</p>}
      {draftChanged && <p role="status">方案参数已调整，下表仍为上一次计算结果。</p>}
      <div className="sw-coverage-table"><table><caption>登记井点名义覆盖对照，单位：个</caption>
        <thead><tr><th scope="col">口径</th><th scope="col">基准</th><th scope="col">方案</th><th scope="col">变化</th></tr></thead>
        <tbody>{METRICS.map(([key, label]) => <tr key={key}><th scope="row">{label}</th>
          <td>{result.baseline[key]}</td><td>{result.scenario[key]}</td><td>{result.scenario[key] - result.baseline[key]}</td></tr>)}</tbody>
      </table></div>
      {result.baseline.area_coverage && <details><summary>登记区域覆盖面积</summary>
        <p>{result.baseline.area_coverage.boundary}</p>
        {result.baseline.area_coverage.boundary_kind === 'registered_bbox_not_exact_factory_boundary'
          && <p>当前边界为登记矩形范围，不是精确厂区边界。</p>}
        {result.baseline.area_coverage.state === 'unavailable' || result.scenario.area_coverage?.state === 'unavailable'
          ? <p>面积暂不可用。请核查登记边界、PostGIS服务及资源资料；不会用井点数量估算面积。</p>
          : <div className="sw-coverage-table"><table><caption>名义面积对照，平方米（显示值取整）</caption>
            <thead><tr><th>口径</th><th>基准</th><th>方案</th></tr></thead><tbody>
              {([
                ['boundary_area_m2', '登记范围面积'], ['known_covered_area_m2', '已知名义覆盖并集'],
                ['unique_overlap_area_m2', '重复覆盖区域（去重）'], ['uncovered_area_m2', '未覆盖面积（资料完整时）'],
              ] as const).map(([key, label]) => <tr key={key}><th>{label}</th>
                {[result.baseline.area_coverage, result.scenario.area_coverage].map((area, index) => <td key={index}>
                  {area?.[key] == null ? '未知' : area[key]!.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                </td>)}
              </tr>)}
            </tbody></table></div>}
        {(result.baseline.area_coverage.state === 'partial' || result.scenario.area_coverage?.state === 'partial')
          && <p>部分设备资料不完整，已知覆盖之外不能直接认定为盲区。</p>}
      </details>}
      {result.baseline.area_coverage?.map_geometry && <details onToggle={event => setMapOpen(event.currentTarget.open)}>
        <summary>在离线底图上比较覆盖范围</summary>
        {mapOpen && <CoverageGeometryMap key={result.id} baseline={result.baseline.area_coverage.map_geometry}
          scenario={result.scenario.area_coverage?.map_geometry} areaId={result.input_snapshot.area_id}
          snapshotRef={result.input_snapshot.map_snapshot_id} />}
      </details>}
      <p>{result.boundary}</p><p>设备名义覆盖与机动车道路关联分开计算。覆盖改善不代表已证明防控效果提升。</p>
      <CoverageRoadPanel key={result.id} comparisonId={result.id} />
      <details><summary>调整假设方案</summary>
        <div className="sw-coverage-controls"><label>假设不可用的设备
          <Select mode="multiple" aria-label="假设不可用的设备" value={disabled} disabled={pending}
            options={result.baseline.resources.map(row => ({ value: row.resource_id, label: `设备 ${row.resource_id}` }))}
            onChange={values => { setDisabled(values); setDraftChanged(true) }} /></label>
          <label>假设移动一个设备
            <Select allowClear aria-label="假设移动一个设备" value={moved} disabled={pending}
              options={result.baseline.resources.filter(row => row.state === 'usable' && !disabled.includes(row.resource_id))
                .map(row => ({ value: row.resource_id, label: `设备 ${row.resource_id}` }))}
              onChange={value => { setMoved(value); setLatitude(null); setLongitude(null); setDraftChanged(true) }} /></label>
          {moved !== undefined && <><label>假设纬度（WGS84）<InputNumber aria-label="假设纬度" value={latitude} min={-90} max={90} disabled={pending}
            onChange={value => { setLatitude(value); setDraftChanged(true) }} /></label>
            <label>假设经度（WGS84）<InputNumber aria-label="假设经度" value={longitude} min={-180} max={180} disabled={pending}
              onChange={value => { setLongitude(value); setDraftChanged(true) }} /></label></>}
        </div>
        <Button onClick={() => void run()} disabled={pending || incompleteMovement || (moved !== undefined && disabled.includes(moved))}>计算并保存方案</Button>
        <p>只调整本次假设，不移动地图真实点位，不修改设备状态。未知资料不能通过假设移动补成有效资料。</p>
      </details>
      <details><summary>设备条件与证据版本</summary>
        <ul>{result.baseline.resources.map(row => <li key={row.resource_id}>设备 {row.resource_id}：{STATE_LABELS[row.state] || '条件待核'}</li>)}</ul>
        <p>算法：{result.algorithm_version}</p><p className="sw-coverage-digest">输入指纹：{result.input_digest}</p>
      </details>
    </>}
  </section>
}
