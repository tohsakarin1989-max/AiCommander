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
type ReadQuality = Partial<CaseQuality> & { state?: string }
const CURRENT_QUALITY_RULE = 'case-quality-8.0.0-1'
export function hasCurrentCaseQuality(quality?: ReadQuality | null): quality is ReadQuality & { validation: NonNullable<CaseQuality['validation']> } {
  return quality?.state !== 'stale' && quality?.rule_version === CURRENT_QUALITY_RULE && !!quality.validation
}
export function CaseQualityStatus({ quality, readState = 'ready' }: {
  quality?: ReadQuality | null; readState?: 'ready' | 'loading' | 'unavailable'
}) {
  if (readState === 'loading') return <p role="status">正在读取本版资料状态，暂不使用旧缓存判断。</p>
  if (readState === 'unavailable') return <p role="alert">本版资料状态暂不可读，不能据此判断没有缺项。</p>
  if (quality?.state === 'stale' || (quality?.validation && !hasCurrentCaseQuality(quality))) {
    return <p>当前只有历史规则结果，尚未按本版规则评估；历史分值仅供参考，不作为当前缺项或待办。打开页面不会重新分析。</p>
  }
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
