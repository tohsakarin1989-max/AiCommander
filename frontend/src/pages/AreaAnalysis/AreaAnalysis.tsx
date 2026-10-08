import { Link, useLocation } from 'react-router-dom'
import RegionalAnalysisView from '../../components/Facility/RegionalAnalysisView'
import SpaceTimeAnalysis from '../Cases/SpaceTimeAnalysis'
import './AreaAnalysis.css'
import { regionalContextPath } from '../../services/regionalContext'

export function regionalViewPath(search: string, hash: string, view: 'conditions' | 'time') {
  const params = new URLSearchParams(search)
  params.set('regional_view', view)
  return `/area-analysis?${params}${hash}`
}

export default function AreaAnalysis() {
  const { search, hash } = useLocation()
  const view = new URLSearchParams(search).get('regional_view') === 'time' ? 'time' : 'conditions'
  return <div className="page region-workspace"><div className="page-title"><h1>区域综合研判</h1></div>
    <nav className="regional-view-navigation" aria-label="区域研判视图">
      <Link className="btn-ghost" to={regionalViewPath(search, hash, 'conditions')} aria-current={view === 'conditions' ? 'page' : undefined}>设施条件与时间线</Link>
      <Link className="btn-ghost" to={regionalViewPath(search, hash, 'time')} aria-current={view === 'time' ? 'page' : undefined}>时间规律</Link>
      <Link className="btn-ghost" to={regionalContextPath('/assistant', new URLSearchParams(search))}>带本页条件询问助手</Link>
    </nav>
    {view === 'time' ? <SpaceTimeAnalysis embedded /> : <RegionalAnalysisView />}
  </div>
}
