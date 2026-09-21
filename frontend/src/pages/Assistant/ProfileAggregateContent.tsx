import { Link } from 'react-router-dom'
import { rowsOf, textValue } from './queryPresentation'

const kinds: Record<string, string> = {
  stated: '原文明述', negated: '原文否定', uncertain: '不确定', inferred: '推断',
  conflicting: '相互冲突', missing: '缺少表述',
}
const categories: Record<string, string> = {
  method: '作案手法', oil: '油品', facility: '设施', place_condition: '地点条件',
  time_condition: '时间条件', tool: '工具', vehicle: '车辆', upstream_clue: '来源线索', downstream_clue: '去向线索',
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
function percentage(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${(value * 100).toFixed(1)}%` : '无可用分母'
}
function CaseExamples({ title, value }: { title: string; value: unknown }) {
  const rows = rowsOf(value)
  return <section><h3>{title}</h3>
    {rows.length ? <ul>{rows.map((row, index) => <li key={index}>
      {typeof row.case_id === 'number' && Number.isInteger(row.case_id) && row.case_id > 0
        ? <Link to={`/cases?caseId=${row.case_id}`}>案件 #{row.case_id}</Link> : '来源不可用'}
      {row.profile_version != null && `，画像版本 ${textValue(row.profile_version)}`}
    </li>)}</ul> : <p>本批没有可展示案例，不代表已排除其他情况。</p>}
  </section>
}

export function ProfileAggregateContent({ data }: { data: Record<string, unknown> }) {
  const coverage = record(data.coverage)
  const statistics = record(data.statistics)
  const model = record(data.model_extraction)
  if (data.schema_version !== 'profile-aggregate-5.3-1'
      || typeof coverage.complete !== 'boolean' || typeof statistics.denominator !== 'number') {
    return <p role="alert">专题统计结构不完整，不能据此判断没有符合条件的案件。</p>
  }
  return <div className="profile-aggregate-content">
    <p>{coverage.complete ? '已遍历全部授权候选范围' : '尚未遍历全部范围，以下仅为部分统计'}：
      {textValue(coverage.scanned_cases)} / {textValue(coverage.authorized_cases)} 起案件。</p>
    <dl className="query-comparison">
      <div><dt>满足组合条件</dt><dd>{textValue(statistics.matched)} 起</dd></div>
      <div><dt>存在不同或相反表述</dt><dd>{textValue(statistics.unmatched)} 起</dd></div>
      <div><dt>条件资料不足</dt><dd>{textValue(statistics.unknown)} 起</dd></div>
    </dl>
    <p>画像缺失、过期或不完整：{textValue(statistics.unavailable_profile_count)} 起，
      占已遍历案件 {percentage(statistics.unavailable_profile_ratio)}。未知不按否定处理。</p>
    {typeof model.candidate_count === 'number' && <details><summary>已有模型理解能力状态</summary>
      <p>引用校验通过的模型提取候选：{textValue(model.candidate_count)} 项；不混入下方规则条件统计。</p>
      <ul>{Object.entries(record(model.profile_states)).map(([state, count]) => <li key={state}>
        {({ ready: '已有可核对片段', partial: '部分提取', not_enabled: '模型未启用', unavailable: '模型不可用',
          invalid: '模型引用校验失败', profile_unavailable: '画像不可用' } as Record<string, string>)[state] || '未知状态'}：{textValue(count)} 起</li>)}</ul>
      <p>{textValue(model.boundary)}</p>
    </details>}
    <h3>条件分布</h3>
    <p>下列计数按匹配案组中的案件去重。分布列表和代表案例均分页显示，计数不随分页变化。</p>
    <ul>{rowsOf(data.patterns).map((row, index) => <li key={index}>
      {categories[String(row.category)] || '其他条件'}：{textValue(row.value)}，
      {kinds[String(row.kind)] || '未知'}，{textValue(row.case_count)} 起
    </li>)}</ul>
    <CaseExamples title="匹配案组代表案例" value={data.items} />
    <CaseExamples title="不同或相反表述案例" value={data.counterexamples} />
    <CaseExamples title="资料不足案例" value={data.unknown_examples} />
    <details><summary>各类表述缺失比例</summary>
      <p>分母仅为引用校验通过且提取未达上限的画像；缺少文字表述不等于现实中不存在。</p>
      <ul>{rowsOf(data.missingness).map((row, index) => <li key={index}>
        {categories[String(row.category)] || '其他条件'}：{textValue(row.missing_count)} / {textValue(row.denominator)}，
        {percentage(row.ratio)}
      </li>)}</ul>
    </details>
    <p>{textValue(data.boundary)}</p>
  </div>
}
