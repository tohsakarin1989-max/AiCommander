// Dev-only fixture, not part of the production router. No real business records.
import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import LeafletMap from '../../src/components/Map/LeafletMap'
import MapPicker from '../../src/components/Map/MapPicker'
import SpaceTimeMap from '../../src/components/Map/SpaceTimeMap'
import JurisdictionAssetMap from '../../src/pages/Jurisdiction/JurisdictionAssetMap'
import { createOfflineVectorStyle } from '../../src/components/Map/offlineVectorStyle'

const snapshot = '11111111-1111-4111-8111-111111111111'
Object.assign(window, { fixtureStyle: createOfflineVectorStyle(snapshot, [122, 45.2, 127, 49.1]) })
function Fixture() {
  const [view, setView] = useState('none')
  const [selection, setSelection] = useState('尚未选点')
  return <main style={{ width: 1100, background: '#0f172a', color: 'white' }}>
    <h1>隔离组件验证：非生产发布</h1>
    {['none', 'cases', 'picker', 'heat', 'assets'].map(name =>
      <button key={name} onClick={() => setView(name)}>{name}</button>)}
    <p data-testid="selection">{selection}</p>
    {view === 'cases' && <LeafletMap markers={[]} operationalAreaId={1} height={650} />}
    {view === 'picker' && <MapPicker operationalAreaId={1} height={650}
      onChange={(lat, lng) => setSelection(`${lat},${lng}`)} />}
    {view === 'heat' && <SpaceTimeMap operationalAreaId={1} height={650} heatPoints={[]} />}
    {view === 'assets' && <JurisdictionAssetMap operationalAreaId={1} height={650} assets={[]} />}
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)
