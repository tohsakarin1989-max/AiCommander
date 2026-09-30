import type { CaseProcess, ProcessStructuredReference, ProcessTextReference } from '../../services/caseProcess'

const kinds: Record<string, string> = { stated: '原文陈述', negated: '原文否定', uncertain: '不确定', inferred: '推断', mixed: '不同性质表述并存' }
const dimensions: Record<string, string> = { action: '动作', time: '时间', facility: '设施', oil: '油品', place: '地点角色', place_role: '地点角色', upstream: '来源', downstream: '去向', object: '对象', measurement: '计量依据' }
const roles: Record<string, string> = { source: '原文来源表述', destination: '原文去向表述', incident: '案发地点', discovery: '发现地点', mentioned: '提及地点', source_candidate: '来源候选', custody: '保管地点', unknown: '角色未明确' }
const stages: Record<string, string> = { involved: '涉案', seized: '扣押', transferred: '转移', recovered: '回收', unknown: '阶段未知' }
const units: Record<string, string> = { tonne: '吨', liter: '升', kg: '千克', m3: '立方米', unknown: '单位未知' }
const precisions: Record<string, string> = { hour: '小时精度', minute: '分钟精度' }

export function ProcessReference({ reference }: { reference: ProcessTextReference | ProcessStructuredReference }) {
  return <details className="case-semantics__reference"><summary>查看版本化出处</summary>
    <p>来源版本：{reference.source_revision_id ?? '尚未绑定'} · 快照路径：{reference.snapshot_path.join(' / ')}</p>
    {reference.kind === 'text' ? <><p>字符 {reference.start + 1} 至 {reference.end}</p><blockquote>{reference.quote}</blockquote></>
      : <pre className="case-process__source">{JSON.stringify(reference.value, null, 2)}</pre>}
  </details>
}

export default function CaseProcessView({ process }: { process: CaseProcess }) {
  return <section className="case-process" aria-label="案件过程依据">
    <h4>已交代的环节</h4><p>{process.boundary}</p>
    {process.coverage.state === 'partial' && <p role="status">当前仅有部分过程片段，未覆盖内容仍需结合原文。</p>}
    {!process.events.length && <p>尚未整理出有原文依据的过程片段，不代表没有案件过程。</p>}
    <ol>{process.events.map((event, index) => <li key={event.id}>
      <strong>片段 {index + 1} · {event.actions.map(action => `${action.value}（${kinds[action.kind] || '待核'}）`).join('；') || '动作未明确'}</strong>
      <p>{kinds[event.statement_kind] || '表述性质待核'}；规则整理，未经人工认定。</p>
      {!!event.objects.length && <p>同句涉及：{event.objects.map(item => `${item.value}（${kinds[item.kind] || '待核'}）`).join('、')}。同句出现不证明主客体关系。</p>}
      {!!event.time_intervals.length && <p>原文时间：{event.time_intervals.map(time => `${time.start}（${precisions[time.start_precision] || '精度未明确'}）至 ${time.end}（${precisions[time.end_precision] || '精度未明确'}，${time.timezone || '时区未注明'}）`).join('；')}。不自动作为已确认发生时间。</p>}
      {!!event.locations.length && <p>地点：{event.locations.map(place => `${place.value} · ${roles[place.role] || '角色待核'}（${kinds[place.kind] || '待核'}）`).join('；')}</p>}
      {!!event.measurements.length && <p>原文数量：{event.measurements.map(item => `${item.oil_type} ${item.value} ${units[item.unit] || item.unit}（${kinds[item.kind] || '待核'}，阶段未知）`).join('；')}。未与结构化计量合并。</p>}
      {!!event.missing_dimensions.length && <p>尚未交代：{event.missing_dimensions.map(key => dimensions[key] || key).join('、')}。不新增必填操作。</p>}
      <ProcessReference reference={event.reference} />
    </li>)}</ol>
    {!!process.relations.length && <details><summary>原文明示的环节关系 {process.relations.length} 项</summary>
      <p>仅记录原文表达，不确认实际发生顺序、来源或因果。</p>
      {process.relations.map(relation => <div key={relation.id}><p>{relation.type === 'precedes' ? '先后表述' : '关联表述'} · {kinds[relation.kind] || '待核'}</p><ProcessReference reference={relation.reference} /></div>)}
    </details>}
    <h4>不同或相互矛盾的记录</h4>
    {process.conflicts.length ? process.conflicts.map(conflict => <div key={conflict.id}>
      <p>{conflict.value}存在不同表述，需核对是否同一时段、对象；不自动选择其中一项。</p>
      {conflict.references.map((reference, index) => <ProcessReference key={index} reference={reference} />)}
    </div>) : <p>当前规则未标记冲突，不代表记录已完全一致。</p>}
    <details><summary>案件背景中的地点与计量记录</summary>
      <p>下列结构化记录属于案件背景，未自动绑定到每个环节，不混合阶段或换算未知单位。</p>
      {process.structured_context.locations.map((location, index) => <div key={index}>
        <p>{roles[location.role] || '地点角色待核'}：{location.description || '描述未记录'}</p><ProcessReference reference={location.reference} />
      </div>)}
      {process.structured_context.measurements.map((measurement, index) => <div key={index}>
        <p>{stages[measurement.stage || 'unknown'] || measurement.stage}：{measurement.value ?? '数量未知'} {units[measurement.unit || 'unknown'] || measurement.unit}；测量方法：{measurement.method || '未记录'}；含水率：{measurement.water_cut ?? '未知'}（{measurement.water_cut_basis || '口径未注明'}）</p>
        <ProcessReference reference={measurement.reference} />
      </div>)}
      {!process.structured_context.locations.length && !process.structured_context.measurements.length && <p>尚无对应结构化背景记录。</p>}
    </details>
    <small>过程版本：{process.version} · 来源版本：{process.source_revision_id ?? '未绑定'}</small>
  </section>
}
