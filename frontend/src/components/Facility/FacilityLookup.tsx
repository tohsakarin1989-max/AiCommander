import { openFacilityDossier } from '../../services/regionalContext'
import FacilitySearch from './FacilitySearch'

export default function FacilityLookup({ areaId }: { areaId: number | null }) {
  return <section id="facility-lookup" className="card" aria-label="查井场与设施">
    <div className="card-head"><h2 className="ti">查井场与设施</h2></div><div className="card-body">
      <p>查询授权辖区登记资料，不推断涉案关系。历史名称和来源别名只作为查找线索。</p>
      <FacilitySearch areaId={areaId} requireArea onChoose={asset => openFacilityDossier(asset.id)} actionLabel="打开档案" />
    </div>
  </section>
}
