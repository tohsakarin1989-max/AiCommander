import { useMemo } from 'react'
import type { CaseResult } from '../../types/caseResult'
import LeafletMap from '../Map/LeafletMap'
import { caseResultMapModel } from './caseResultMapModel'

export default function CaseResultMap({ result, operationalAreaId }: { result: CaseResult; operationalAreaId?: number }) {
  const map = useMemo(() => caseResultMapModel(result), [result])
  if (!map.snapshotRef || !map.hypothesisRegions.length) return null
  return <div className="case-result__map">
    <h4>候选空间展开</h4>
    <p>使用本成果固定的地图版本和案件记录位置，不混入后来修改的坐标。</p>
    <LeafletMap {...map} operationalAreaId={operationalAreaId} height={320} />
    <p className="case-result__note">圆形表示待核验范围，虚线只表示空间关系，不代表实际路线或正式事实链条。</p>
  </div>
}
