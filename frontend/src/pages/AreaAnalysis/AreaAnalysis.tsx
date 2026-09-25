import RegionalAnalysisView from '../../components/Facility/RegionalAnalysisView'
import './AreaAnalysis.css'

export default function AreaAnalysis() {
  return <div className="page"><div className="page-title"><h1>区域综合研判</h1><span className="sub">设施条件对照 · 案件与事件时间线</span></div>
    <RegionalAnalysisView />
  </div>
}
