import { Link } from 'react-router-dom'
import type { AttentionItem, AttentionGrounding } from '../../types/attention'

const labels = { explicit_links: '明确登记关联', spatial_proximity: '空间邻近背景',
  condition_similarity: '已知条件对照', production_background: '生产背景与资料缺口' }
const states = { repeated_conditions: '已有重复条件依据', new_information: '单条新增情况，不称为规律', background_only: '仅背景资料' }

export function AttentionItemContent({ item }: { item: AttentionItem }) {
  return <article className="facility-evidence" aria-label={`${item.label}的关注依据`}>
    <h3>{item.label} · {states[item.state] || '资料待核'}</h3>
    <p>{item.boundary}</p>
    {Object.entries(labels).map(([key, label]) => {
      const layer = item.layers[key as keyof typeof labels]
      if (!layer) return null
      if (layer.state === 'restricted') return <section key={key}><h4>{label}</h4><p>资料受限，不展示内容与数量。</p></section>
      if (layer.state === 'unavailable') return <section key={key}><h4>{label}</h4><p>资料暂不可读，不代表没有相关情况。</p></section>
      return <details key={key} open={key === 'explicit_links' || key === 'condition_similarity'}>
        <summary>{label}{layer.record_count != null ? ` · ${layer.record_count} 起独立来源记录` : ''}</summary>
        <p>{layer.boundary}</p>
        {(layer.items || []).slice(0, 10).map((row, index) => <div key={index}>
          <strong>{row.value || row.label || (key === 'spatial_proximity' ? '位置邻近' : '已有来源资料')}</strong>
          {row.independent_count != null && <span> · {row.independent_count} 起独立来源记录</span>}
          {row.distance_km != null && <span> · 直线 {row.distance_km.toFixed(2)} 公里（非道路距离）</span>}
          {!!row.case_ids?.length && <p>{row.case_ids.slice(0, 10).map(id => <Link key={id} to={`/cases?caseId=${id}`} style={{ marginRight: 12 }}>记录 {id}</Link>)}</p>}
          {row.references?.slice(0, 3).map((ref, i) => <blockquote key={i}>
            {ref.reference.quote || '原文定位见对应记录'}<small> · 记录 {ref.case_id} · 修订 {ref.source_revision_id ?? '未保存'}</small>
          </blockquote>)}
        </div>)}
        {!layer.items?.length && <p>{key === 'production_background' ? '生产详情保留在原台账资料区。' : '未取得该类依据，不作否定结论。'}</p>}
        {!!layer.gaps?.length && <p>缺口：{layer.gaps.join('；')}</p>}
      </details>
    })}
    {!!item.evidence_refs.length && <details><summary>来源与版本引用</summary><ul>{item.evidence_refs.map(ref => <li key={ref}>{ref}</li>)}</ul></details>}
  </article>
}

export default function AttentionGrounds({ value }: { value: AttentionGrounding }) {
  return <section aria-label="区域与设施关注依据">
    <h2>区域与设施关注依据</h2><p>{value.boundary}</p>
    {(value.coverage.complete === false || value.coverage.state === 'partial') && <p role="status">本次仅完成部分资料读取，不代表完整范围内只有这些关注项。</p>}
    {!value.items.length && <p>当前没有足够依据形成关注项；不为凑数量生成建议。</p>}
    {value.items.slice(0, 3).map(item => <AttentionItemContent key={item.object_key} item={item} />)}
    <small>已读取 {value.coverage.cases_scanned} 条授权记录；规则版本 {value.version}。同源记录按明确来源关系去重。</small>
  </section>
}
