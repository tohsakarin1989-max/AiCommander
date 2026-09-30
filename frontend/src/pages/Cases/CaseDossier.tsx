import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { CaseQuality } from '../../types'
import './CaseDossier.css'

export const caseDossierViews = { overview: '概览', sources: '来源与明细', relations: '过程与关联', results: '研判成果', materials: '业务材料' }
export type CaseDossierView = keyof typeof caseDossierViews
export function caseDossierView(value: string | null): CaseDossierView {
  return value && Object.prototype.hasOwnProperty.call(caseDossierViews, value) ? value as CaseDossierView : 'overview'
}
export function CaseDossierNavigation() {
  const [params, setParams] = useSearchParams()
  const selected = caseDossierView(params.get('case_view'))
  return <nav className="case-dossier-nav" aria-label="案件档案分组">
    {Object.entries(caseDossierViews).map(([value, label]) => <button key={value} type="button" aria-current={selected === value ? 'page' : undefined}
      onClick={() => setParams(previous => { const next = new URLSearchParams(previous); next.set('case_view', value); return next }, { replace: true })}>{label}</button>)}
  </nav>
}
export function CaseDossierPanel({ view, active, children }: { view: CaseDossierView; active: CaseDossierView; children: ReactNode }) {
  return active === view ? <section className="case-dossier-panel" aria-label={caseDossierViews[view]}>{children}</section> : null
}
export function CaseQualityStatus({ quality }: { quality?: Partial<CaseQuality> | null }) {
  if (!quality?.validation) return <p>本版资料预检尚未形成，不以历史分数表示完整性。</p>
  return <div className="case-quality-status">
    <p>{quality.validation.can_save ? '录入格式有效' : '存在需修正的格式问题'}；{quality.completeness?.status === 'sufficient' ? '当前未提示关键缺口' : '部分资料仍可补充'}。不代表案件办结。</p>
    {!!quality.validation.errors.length && <ul>{quality.validation.errors.map(item => <li key={item.field}>{item.message}</li>)}</ul>}
    {!!quality.priority_gaps?.length && <><h4>关键补充（最多三项）</h4><ul>{quality.priority_gaps.slice(0, 3).map(item => <li key={item.field}><strong>{item.label}</strong>：{item.reason}</li>)}</ul></>}
    {quality.capabilities && <details><summary>这些资料可以支持哪些分析</summary><dl>{Object.entries(quality.capabilities).map(([key, value]) => <div key={key}>
      <dt>{value.label}</dt><dd>{{ ready: '资料就绪', partial: '部分资料', missing: '缺少资料' }[value.data_state]}{value.blockers.length ? `：${value.blockers.join('；')}` : ''}</dd>
    </div>)}</dl><p>这里只判断输入资料条件，模型、路网等运行状态另行检查。</p></details>}
  </div>
}
