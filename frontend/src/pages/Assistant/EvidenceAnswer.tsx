import type { EvidenceAnswer as Answer, QueryCard } from '../../services/intelligentQueries'

export function answerValid(value: unknown, cards: QueryCard[]): value is Answer {
  if (!value || typeof value !== 'object') return false
  const answer = value as Answer
  return answer.schema_version === 'query-answer-6.4-1' && typeof answer.summary === 'string'
    && typeof answer.boundary === 'string' && Array.isArray(answer.information_gaps)
    && answer.information_gaps.every(item => typeof item === 'string') && Array.isArray(answer.findings)
    && answer.findings.every(item => item && typeof item.text === 'string' && Number.isInteger(item.card_index)
      && item.card_index >= 0 && item.card_index < cards.length && Array.isArray(item.evidence_refs)
      && item.evidence_refs.every(ref => typeof ref === 'string'))
}

export default function EvidenceAnswer({ answer, cards }: { answer: unknown; cards: QueryCard[] }) {
  if (!answerValid(answer, cards)) return <p role="alert">答案依据结构不完整，请核对下方工具结果，不能据此作出结论。</p>
  return <section className="query-answer" aria-label="有依据的回答">
    <h2>回答与依据</h2><p>{answer.summary}</p>
    <ol>{answer.findings.map((finding, index) => <li key={index}>
      <p>{finding.text} <a href={`#query-card-${finding.card_index}`}>核对依据 {finding.card_index + 1}</a></p>
      {!!finding.evidence_refs.length && <details><summary>来源引用</summary><ul>{finding.evidence_refs.map((ref, i) => <li key={i}>{ref}</li>)}</ul></details>}
    </li>)}</ol>
    {!!answer.information_gaps.length && <><h3>尚不能回答的部分</h3><ul>{answer.information_gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></>}
    <p className="query-history-note">{answer.boundary}</p>
  </section>
}
