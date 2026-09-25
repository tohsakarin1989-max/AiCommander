import { Link } from 'react-router-dom'
import type { useRegionalContext } from '../../services/useRegionalContext'
import { regionalCalendarDate, regionalContextPath } from '../../services/regionalContext'
import './FacilityAnalysis.css'

const windowTime = (value?: string) => !value ? '不限' : Number.isFinite(Date.parse(value))
  ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium', hour12: false }).format(new Date(value)) : '无效时间'

export default function RegionalControls({ context }: { context: ReturnType<typeof useRegionalContext> }) {
  const caseOnlyFilters = ['keyword', 'statuses', 'case_types', 'oil_types', 'has_geo'].some(key => context.params.has(key))
  return <>
    <div className="regional-controls">
      <label>辖区<select aria-label="区域研判辖区" value={context.areaId ?? ''} onChange={e => context.update({ operational_area_id: Number(e.target.value) })}>
        {!context.scopes.length && <option value="">暂无授权辖区</option>}
        {context.scopes.map(scope => <option key={scope.operational_area_id} value={scope.operational_area_id}>{scope.area_name}</option>)}
      </select></label>
      <label>开始日期<input aria-label="区域开始日期" type="date" value={regionalCalendarDate(context.startDate)}
        onChange={e => context.update({ start_date: e.target.value ? `${e.target.value}T00:00:00+08:00` : null, time_scope: null })} /></label>
      <label>截止日期（不含）<input aria-label="区域截止日期" type="date" value={regionalCalendarDate(context.endDate)}
        onChange={e => context.update({ end_date: e.target.value ? `${e.target.value}T00:00:00+08:00` : null, time_scope: null })} /></label>
      <button className="btn-ghost" onClick={() => context.update({ start_date: null, end_date: null, time_scope: 'all_history' })}>全部授权历史</button>
    </div>
    <p>当前时间窗（北京时间，起含止不含）：{windowTime(context.startDate)} — {windowTime(context.endDate)}。调整日期按当日零时取值。</p>
    <nav className="regional-links" aria-label="同条件区域视图">
      {[['/cases/map', '案件与设施地图'], ['/area-analysis', '设施条件对照与时间线'], ['/cases/spacetime', '时空规律'], ['/jurisdiction', '辖区底座'], ['/events', '独立事件']].map(([path, label]) =>
        <Link key={path} to={regionalContextPath(path, context.params)}>{label}</Link>)}
    </nav>
    {context.error && <p role="alert">{context.error}</p>}
    {caseOnlyFilters && <p role="status">区域对照与时空统计采用当前辖区和时间窗；关键词、案件状态、类型、油品和坐标筛选保留供返回案件页使用，此处未将它们应用到设施与事件。</p>}
  </>
}
