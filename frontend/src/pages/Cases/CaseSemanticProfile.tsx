import type { CaseSemantics, SemanticReference } from '../../services/intelligenceFlow'
import './CaseSemanticProfile.css'

const fields: Record<string, string> = {
  description: '案情描述', location: '地点', modus_operandi: '作案手法',
  facility_type: '设施类型', oil_type: '油品', vehicle_info: '车辆信息', involved_items: '涉案物品',
  upstream_source: '来源线索', downstream_destination: '去向线索',
}
const categories: Record<string, string> = {
  vehicle: '车辆', oil: '油品', facility: '设施', tool: '工具', method: '手法',
  place_condition: '地点条件', time_condition: '时段', upstream_clue: '来源线索', downstream_clue: '去向线索',
}
const kinds: Record<string, string> = {
  stated: '原文陈述', negated: '原文否定', uncertain: '待核表述', inferred: '推断',
}
const gaps: Record<string, string> = {
  lineage_not_established: '来源或去向尚未明确', invalid_time_interval: '起止时间需核对',
  relative_time_requires_anchor: '相对时间缺少日期依据', time_expression_requires_context: '时刻缺少日期或上下文',
  extraction_limit: '文本提取未覆盖全部内容', invalid_structured_source: '结构化资料格式需核对',
  structured_source_too_large: '资料过大，尚未完成结构化提取', structured_extraction_limit: '结构化资料仅提取了部分内容',
}

function Reference({ value }: { value: SemanticReference }) {
  return <details className="case-semantics__reference">
    <summary>查看原文出处</summary>
    <p>{fields[value.field] || '来源字段'} · 字符 {value.start + 1} 至 {value.end}</p>
    <blockquote>{value.quote}</blockquote>
  </details>
}

export function semanticTimeLabel(value: string, precision: string) {
  return precision === 'hour' ? `${value.slice(0, 13).replace('T', ' ')}时` : value.replace('T', ' ')
}

export default function CaseSemanticProfile({ semantics, loading, error, updating }: {
  semantics?: CaseSemantics; loading?: boolean; error?: boolean; updating?: boolean
}) {
  return <section className="detail-section case-semantics" aria-label="案情语义画像">
    <h3>案情语义画像</h3>
    {error ? <p role="status">画像暂时无法读取，不影响案件保存。请稍后重试。</p>
      : loading ? <p role="status">正在读取已有画像…</p>
      : !semantics ? <p>当前尚无语义画像。已有案件资料仍可正常查看，后台生成后会自动显示。</p>
      : <>
        <p className="case-semantics__note">本地规则整理的原文表述，不是核实结论。复杂语义仍需结合上下文判断。</p>
        {updating && <p role="status" className="case-semantics__warning">画像更新中，以下为上一次处理结果。</p>}
        <ul className="case-semantics__items">
          {semantics.assertions.slice(0, 6).map((item, index) => <li key={index}>
            <span className={item.kind === 'stated' ? 'case-semantics__kind' : 'case-semantics__warning'}>{kinds[item.kind] || '类型待核'}</span>
            <strong>{item.value}</strong><span>{categories[item.category] || '词项'}</span>
            <Reference value={item.reference} />
          </li>)}
        </ul>
        {!semantics.assertions.length && <p>现有规则未提取出可展示词项，不表示案件没有线索。</p>}
        {semantics.assertions.length > 6 && <details>
          <summary>其余 {semantics.assertions.length - 6} 项表述</summary>
          <ul className="case-semantics__items">{semantics.assertions.slice(6).map((item, index) => <li key={index}>
            <span>{kinds[item.kind] || '类型待核'}</span><strong>{item.value}</strong><Reference value={item.reference} />
          </li>)}</ul>
        </details>}
        {!!semantics.time_intervals?.length && <details>
          <summary>时间表达 {semantics.time_intervals.length} 项</summary>
          <p>仅整理原文起止时间，未替代正式案发时间；未注明时区时不自动转换。</p>
          {semantics.time_intervals.map((item, index) => <div key={index}>
            <p>{semanticTimeLabel(item.start, item.start_precision)} 至 {semanticTimeLabel(item.end, item.end_precision)}</p>
            <Reference value={item.reference} />
          </div>)}
        </details>}
        {!!semantics.structured_sources?.entries.length && <details>
          <summary>结构化资料 {semantics.structured_sources.entries.length} 项</summary>
          <ul>{semantics.structured_sources.entries.map(({ reference }, index) => <li key={index}>
            <span>{fields[reference.field] || '资料'} / {reference.path.map(part => typeof part === 'number' ? `第${part + 1}项` : part).join(' / ') || '字段值'}：</span>
            {typeof reference.value === 'boolean' ? (reference.value ? '是' : '否') : JSON.stringify(reference.value)}
          </li>)}</ul>
        </details>}
        {!!semantics.potential_conflicts?.length && <p className="case-semantics__warning">以下词项存在不同表述，需结合时间和上下文核对：{semantics.potential_conflicts.map(item => item.value).join('、')}</p>}
        {!!semantics.information_gaps?.length && <details>
          <summary>信息缺口与提取限制 {semantics.information_gaps.length} 项</summary>
          <ul>{semantics.information_gaps.map((item, index) => <li key={index}>
            {gaps[item.code] || '本项信息待核对'}{item.field ? `（${fields[item.field] || '来源字段'}）` : ''}
            {item.reference && <Reference value={item.reference} />}
          </li>)}</ul>
        </details>}
        <small>规则版本：{semantics.rule_version}</small>
      </>}
  </section>
}
