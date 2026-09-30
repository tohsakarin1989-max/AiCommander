import type { TopicSnapshot } from '../../services/analysisTopics'
import { FacilityDossierContent } from '../../components/Facility/FacilityDossierDrawer'
import CaseProcessView from '../Cases/CaseProcessView'
import { CaseQualityStatus } from '../Cases/CaseDossier'
import { Link } from 'react-router-dom'
import { resultPath } from '../../services/results'

export function TopicBusinessContext({ snapshot }: { snapshot: TopicSnapshot }) {
  const workspace = snapshot.case_context
  const process = workspace?.profile.data?.payload.semantics?.process
  const result = workspace?.result.data
  return <section aria-label="关注对象本版内容">
    {snapshot.population_boundary && <p>{snapshot.population_boundary}</p>}
    {workspace && <><h3>案件 #{workspace.case_id} 的资料变化</h3>
      <p>本版冻结的画像状态：{workspace.profile?.status === 'ready' ? '已有可读资料' : '尚未全部就绪'}，不是案件办理状态。</p>
      <CaseQualityStatus quality={workspace.detail_profile?.data?.quality} />
      {process ? <CaseProcessView process={process} /> : <p>本版没有就绪的案件过程；没有重新提取原文。</p>}
      {result ? <Link to={resultPath('case', result.id)}>打开本版引用的案件成果</Link> : <p>本版未引用可读案件成果。</p>}
    </>}
    {snapshot.facility_context && <><h3>本版冻结的设施资料</h3><p>以下是专题形成时留存的读取结果，不是设施当前最新档案。</p>
      <FacilityDossierContent data={snapshot.facility_context} params={new URLSearchParams()} /></>}
  </section>
}
