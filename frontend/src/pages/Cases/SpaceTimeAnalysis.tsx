import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactECharts from 'echarts-for-react'
import { useRegionalAnalysis } from '../../services/useRegionalAnalysis'
import { regionalContextPath } from '../../services/regionalContext'
import RegionalControls from '../../components/Facility/RegionalControls'
import SpaceTimeMap from '../../components/Map/SpaceTimeMap'
import './SpaceTimeAnalysis.css'

export function hourDayMatrix(rows: { weekday: number; hour: number; count: number }[], timeSlot: string, dayFilter: string) {
  return rows.filter(item => (dayFilter === 'all' || (dayFilter === 'weekday' ? item.weekday < 5 : item.weekday >= 5))
    && (timeSlot === 'all' || (timeSlot === 'midnight' ? item.hour < 6 : timeSlot === 'day' ? item.hour >= 6 && item.hour < 18 : item.hour >= 18)))
    .map(item => [item.hour, item.weekday, item.count])
}

export default function SpaceTimeAnalysis() {
  const { context, query, data } = useRegionalAnalysis()
  const [timeSlot, setTimeSlot] = useState('all')
  const [dayFilter, setDayFilter] = useState('all')
  const matrix = useMemo(() => hourDayMatrix(data?.statistics.hour_day ?? [], timeSlot, dayFilter), [data?.statistics.hour_day, timeSlot, dayFilter])
  const heatPoints = useMemo(() => (data?.cases.items ?? []).filter(item => item.latitude != null && item.longitude != null)
    .map(item => ({ lat: item.latitude!, lng: item.longitude!, intensity: 1 })), [data?.cases.items])
  const months = data?.statistics.monthly ?? []
  const spatialMonths = [...new Set(data?.statistics.spatial_monthly?.map(item => item.month) ?? [])].sort()
  const spatialGroups = new Map<string, Map<string, number>>()
  for (const item of data?.statistics.spatial_monthly ?? []) {
    const key = `${item.cell_latitude},${item.cell_longitude}`
    const values = spatialGroups.get(key) ?? new Map<string, number>()
    values.set(item.month, item.case_count); spatialGroups.set(key, values)
  }
  const spatial = {
    tooltip: { trigger: 'axis' }, legend: { type: 'scroll' },
    grid: { top: 45, bottom: 40, left: 45, right: 20 },
    xAxis: { type: 'category', data: spatialMonths }, yAxis: { type: 'value', minInterval: 1 },
    series: [...spatialGroups.entries()].map(([key, values]) => ({ name: `位置格 ${key}`, type: 'line', data: spatialMonths.map(month => values.get(month) ?? 0) })),
  }
  const option = {
    tooltip: { position: 'top' },
    grid: { top: 20, bottom: 70, left: 50, right: 12 },
    xAxis: { type: 'category', data: Array.from({ length: 24 }, (_, i) => `${i}时`), splitArea: { show: true } },
    yAxis: { type: 'category', data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'], splitArea: { show: true } },
    visualMap: { min: 0, max: Math.max(1, ...matrix.map(item => item[2])), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
    series: [{ type: 'heatmap', data: matrix, label: { show: true } }],
  }
  const monthly = {
    tooltip: { trigger: 'axis' }, legend: { data: ['案件', '事件（单列）'] },
    grid: { top: 40, bottom: 35, left: 45, right: 20 },
    xAxis: { type: 'category', data: months.map(item => item.month) }, yAxis: { type: 'value', minInterval: 1 },
    series: [{ name: '案件', type: 'line', data: months.map(item => item.case_count) },
      { name: '事件（单列）', type: 'line', data: months.map(item => item.event_count) }],
  }
  return <div className="sta-page">
    <div className="page-title"><h1>时空研判分析</h1><span className="sub">同范围案件分布与全库时间规律</span></div>
    <RegionalControls context={context} />
    {query.isError && <p role="alert">时空资料读取失败，未使用旧缓存或推断为空。<button onClick={() => void query.refetch()}>重试</button></p>}
    {query.isFetching && !data && <p role="status">正在读取授权区域资料…</p>}
    {data && <>
      <p>{data.boundary}</p>
      <p>完整匹配案件 {data.cases.total} 起，事件 {data.events.total} 条。下方矩阵与月度趋势使用后端全库聚合，不以地图展示量代替总体。</p>
      <div className="sta-filter-bar">
        <label>矩阵时段 <select aria-label="矩阵时段" value={timeSlot} onChange={e => setTimeSlot(e.target.value)}>
          <option value="all">全天</option><option value="midnight">深夜 0—6</option><option value="day">白天 6—18</option><option value="evening">夜间 18—24</option>
        </select></label>
        <label>矩阵星期 <select aria-label="矩阵星期" value={dayFilter} onChange={e => setDayFilter(e.target.value)}>
          <option value="all">全部</option><option value="weekday">工作日</option><option value="weekend">周末</option>
        </select></label><span>细分只调整下方规律矩阵，区域时间窗保持不变。</span>
      </div>
      <section className="card"><div className="card-head"><h2>案件空间分布</h2></div>
        <SpaceTimeMap key={context.areaId} heatPoints={heatPoints} predictionHotspots={[]} height={430} operationalAreaId={context.areaId!} snapshotRef={data.versions.map_snapshot_id ?? undefined} />
        <p>地图显示 {heatPoints.length} 起有坐标案件；无有效坐标 {data.cases.missing_coordinates} 起仍计入总量。
          {data.coverage.cases_truncated && ' 地图点位已限额，不代表完整总体。'}热力表示记录分布，不表示未来发案概率。</p>
        <Link to={regionalContextPath('/cases/map', context.params)}>在同范围地图中选择案件、设施与事件</Link>
      </section>
      <section className="card"><div className="card-head"><h2>时段与星期规律（北京时间）</h2></div>
        {data.statistics.hour_day ? <ReactECharts option={option} style={{ height: 350 }} /> : <p>全库时段聚合暂不可读，未从有限点位推算。</p>}
      </section>
      <section className="card"><div className="card-head"><h2>月度趋势</h2></div>
        {data.statistics.monthly ? <ReactECharts option={monthly} style={{ height: 300 }} /> : <p>全库月度聚合暂不可读。</p>}
        <p>案件和事件按来源分别展示，已关联案件的事件不重复计入案件曲线。</p>
      </section>
      <section className="card"><div className="card-head"><h2>位置分布的月度变化</h2></div>
        {data.statistics.spatial_monthly ? <ReactECharts option={spatial} style={{ height: 330 }} /> : <p>同范围位置分布聚合暂不可读。</p>}
        <p>按 {data.statistics.spatial_grid_degrees ?? '已登记'} 度格网汇总同一时间窗内的有坐标案件；这是记录位置分布，不是风险分或预测。</p>
      </section>
    </>}
  </div>
}
