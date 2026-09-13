import React from 'react'
import { createRoot } from 'react-dom/client'
import CaseFacilityComparison from '../src/components/CaseResult/CaseFacilityComparison'
import { facilityMapFixture } from '../src/components/CaseResult/facilityMapFixture'
import { LegacyCandidateReference } from '../src/components/CaseResult/CaseRoadComparison'
import '../src/components/CaseResult/CaseResultPanel.css'

createRoot(document.getElementById('root')!).render(<main style={{ maxWidth: 1000, margin: '24px auto', padding: 24, fontFamily: 'system-ui' }}>
  <h1>候选地图交互验收（隔离合成样本）</h1>
  <CaseFacilityComparison content={facilityMapFixture()} />
  <LegacyCandidateReference currentFacility><p>原活动区域候选继续保留</p></LegacyCandidateReference>
</main>)
