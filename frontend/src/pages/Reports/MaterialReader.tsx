import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { isResultKind, resultKinds, resultPath, resultsApi } from '../../services/results'
import type { ResultMaterial } from '../../services/results'
import { knowledgeApi } from '../../services/knowledge'
import { buildReportReviewPresentation } from './reportPresentationModel'
import MaterialJudgment from './MaterialJudgment'
import MaterialMap from './MaterialMap'

const experienceStates: Record<string, string> = { draft: '草稿／待确认', confirmed: '已确认', archived: '已归档' }

export function MaterialDocument({ material }: { material: ResultMaterial }) {
  return <article className="material-document" aria-label="固定版本正文">
    {material.document.blocks.map((block, index) => block.kind === 'heading' ? <h2 key={index}>{block.text}</h2>
      : block.kind === 'table' ? <table key={index}><caption>{block.text}</caption><tbody>{block.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => j === 0 ? <th key={j} scope="row">{cell}</th> : <td key={j}>{cell}</td>)}</tr>)}</tbody></table>
      : block.kind === 'map' ? <p key={index}>地图依据见下方“同源地图”；使用本材料冻结的点位与版本，不表示实际轨迹。</p>
      : <p className={block.kind === 'source' ? 'material-source' : undefined} key={index}>{block.text}</p>)}
  </article>
}
export default function MaterialReader({ material, identity, allowed, onSaved }: { material: ResultMaterial; identity: string; allowed: boolean; onSaved: () => void }) {
  const [exporting, setExporting] = useState(false)
  const [notice, setNotice] = useState('')
  const active = useRef(true)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => { active.current = true; return () => { active.current = false; controller.current?.abort() } }, [])
  const review = useMutation({ mutationFn: () => knowledgeApi.reviewReport(Number(material.id)) })
  const reviewResult = review.data ? buildReportReviewPresentation(review.data) : null
  async function download(format: 'docx' | 'pdf') {
    if (exporting) return
    const abort = new AbortController(); controller.current = abort; setExporting(true); setNotice('')
    try {
      const blob = await resultsApi.document(material, format, abort.signal)
      if (!active.current || abort.signal.aborted) return
      const url = URL.createObjectURL(blob); const link = document.createElement('a')
      link.href = url; link.download = `材料-${material.content_sha256.slice(0, 16)}.${format}`; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000); setNotice('已导出当前内容版本，未重新分析。')
    } catch { if (active.current && !abort.signal.aborted) setNotice('导出未完成。请核对权限、内容版本或本地渲染服务，未生成省略内容的替代材料。') }
    finally { if (active.current) setExporting(false) }
  }
  return <section className="material-reader" aria-label="统一成果阅读">
    <header><p>{resultKinds[material.kind]} · {material.created_at}</p><h1>{material.title}</h1></header>
    <p>正在阅读固定版本。正文、引用和导出使用同一内容，不随原始资料后续更新而改写。</p>
    <div className="material-actions"><button className="btn-ghost" disabled={exporting} onClick={() => void download('docx')}>导出本版 Word</button>
      <button className="btn-ghost" disabled={exporting} onClick={() => void download('pdf')}>导出本版 PDF</button>
      {exporting && <span role="status">正在生成材料…</span>}</div>
    {notice && <p role="status">{notice}</p>}
    <MaterialDocument material={material} />
    <MaterialMap material={material} identity={identity} />
    {material.experience_review && <section aria-label="经验确认状态"><h2>经验确认状态</h2><p>{experienceStates[material.experience_review.status] || '状态待核'} · {material.experience_review.reviewer_label || '尚无确认人'}</p><p>{material.experience_review.review_note}</p><small>这是当前人工确认记录，不改写上方冻结正文。</small></section>}
    <details><summary>引用与版本</summary><p>内容摘要：<code>{material.content_sha256}</code></p>
      <p>结构版本：{material.schema_version}</p><ul>{material.sources.map((source, i) => <li key={i}>
        {isResultKind(source.kind) ? <Link to={resultPath(source.kind, source.id)}>{resultKinds[source.kind]} #{source.id}</Link> : <span>{source.kind} #{source.id}</span>}
        <small> · {source.content_sha256}</small></li>)}</ul></details>
    <ul className="material-boundary">{material.boundary.map((line, i) => <li key={i}>{line}</li>)}</ul>
    <MaterialJudgment key={`${material.kind}:${material.id}:${material.content_sha256}`} identity={identity} material={material} allowed={allowed} onSaved={onSaved} />
    {material.kind === 'meeting' && allowed && <details><summary>高级可选：对这份会议报告审稿</summary>
      <p>保留原会议审稿能力；不改变已冻结报告，也不是案件必经步骤。</p>
      <button className="btn-ghost" disabled={review.isPending} onClick={() => review.mutate()}>检查本报告表达</button>
      {review.error && <p role="alert">审稿服务未完成，不影响材料阅读。</p>}
      {reviewResult && <><p>{reviewResult.totalFindings} 项建议，仍需人工判断。</p><ul>{reviewResult.findingLines.map((line, i) => <li key={i}>{line}</li>)}</ul><ul>{reviewResult.suggestedFixes.map((line, i) => <li key={i}>{line}</li>)}</ul></>}
    </details>}
  </section>
}
