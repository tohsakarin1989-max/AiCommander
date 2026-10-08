import { useState } from 'react'

export type FacilityTimeSelection = {
  valid_at: string | null; valid_from: string | null; valid_to: string | null; known_at: string | null
  knowledge_mode: 'as_known' | 'retrospective' | null
}
export function facilityLocalTime(value?: string) {
  return value && Number.isFinite(Date.parse(value)) ? new Date(Date.parse(value) + 8 * 3_600_000).toISOString().slice(0, 23).replace(/:00\.000$/, '').replace(/\.000$/, '') : ''
}
export function facilityQueryInstant(value: string): string | null {
  if (!value) return null
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value)
  if (!match) throw new Error('请填写完整查询时刻')
  const complete = `${match[1]}:${match[2] || '00'}.${(match[3] || '0').padEnd(3, '0')}`
  const instant = new Date(`${complete}+08:00`)
  if (!Number.isFinite(instant.valueOf()) || new Date(instant.valueOf() + 8 * 3_600_000).toISOString().slice(0, 23) !== complete) throw new Error('查询时刻无效')
  return instant.toISOString()
}
export function makeFacilityTimeSelection(input: { period: 'point' | 'interval'; mode: 'as_known' | 'retrospective'; start: string; end: string; known: string;
  original?: { start?: string; end?: string; known?: string } }): FacilityTimeSelection {
  const read = (key: 'start' | 'end' | 'known') => input.original?.[key] && Number.isFinite(Date.parse(input.original[key]!)) && input[key] === facilityLocalTime(input.original[key])
    ? input.original[key]! : facilityQueryInstant(input[key])
  const start = read('start'), end = input.period === 'interval' ? read('end') : null
  const known = input.mode === 'as_known' ? read('known') : null
  if (input.period === 'interval' && (!start || !end || Date.parse(start) > Date.parse(end))) throw new Error('请填写完整、顺序有效的业务区间；不会取中点代替。')
  if (input.mode === 'as_known' && (!start || !known || Date.parse(known) > Date.now())) throw new Error('当时已知口径需业务时点或区间，以及不晚于现在的获知截止。')
  return { valid_at: input.period === 'point' ? start : null, valid_from: input.period === 'interval' ? start : null,
    valid_to: end, known_at: known, knowledge_mode: input.mode }
}

export function FacilityTimeControls({ validAt, validFrom, validTo, knownAt, knowledgeMode, onApply }: {
  validAt?: string; validFrom?: string; validTo?: string; knownAt?: string; knowledgeMode?: 'as_known' | 'retrospective'
  onApply: (selection: FacilityTimeSelection) => void
}) {
  const [period, setPeriod] = useState<'point' | 'interval'>(validFrom ? 'interval' : 'point')
  const [mode, setMode] = useState<'as_known' | 'retrospective'>(knowledgeMode ?? (knownAt ? 'as_known' : 'retrospective'))
  const [start, setStart] = useState(() => facilityLocalTime(validFrom ?? validAt))
  const [end, setEnd] = useState(() => facilityLocalTime(validTo))
  const [known, setKnown] = useState(() => facilityLocalTime(knownAt))
  const [error, setError] = useState('')
  return <form className="facility-time-controls" onSubmit={event => {
    event.preventDefault()
    try { onApply(makeFacilityTimeSelection({ period, mode, start, end, known, original: { start: validFrom ?? validAt, end: validTo, known: knownAt } })); setError('') }
    catch (failure) { setError(failure instanceof Error ? failure.message : '历史条件无效，未回退当前资料。') }
  }}>
    <p>按需查看生产资料；使用北京时间，不改变案件统计时间窗。模糊案发时间保留完整区间，不用中点代表。</p>
    <div><label>资料口径<select value={mode} onChange={event => setMode(event.target.value as typeof mode)}>
      <option value="retrospective">现在回看历史（标明后来补录）</option><option value="as_known">当时知道什么（固定获知截止）</option>
    </select></label><label>业务时间<select value={period} onChange={event => setPeriod(event.target.value as typeof period)}>
      <option value="point">明确时点</option><option value="interval">完整不确定区间</option>
    </select></label></div>
    <div><label>{period === 'point' ? '业务有效时点' : '业务区间开始'}<input type="datetime-local" step="0.001" value={start} onChange={event => setStart(event.target.value)} /></label>
      {period === 'interval' && <label>业务区间结束<input type="datetime-local" step="0.001" value={end} onChange={event => setEnd(event.target.value)} /></label>}
      {mode === 'as_known' && <label>系统已知截止<input type="datetime-local" step="0.001" value={known} onChange={event => setKnown(event.target.value)} /></label>}</div>
    <p>{mode === 'retrospective' ? '资料截止由本次请求固定为现在；后补资料不冒充当时已经掌握。' : '晚于获知截止收到的资料不参与本次历史判断；读取仍受当前权限限制。'}</p>
    <div><button className="btn-ghost" type="submit">查看指定条件资料</button><button className="btn-ghost" type="button" onClick={() => {
      setStart(''); setEnd(''); setKnown(''); setPeriod('point'); setMode('retrospective'); setError('')
      onApply({ valid_at: null, valid_from: null, valid_to: null, known_at: null, knowledge_mode: null })
    }}>清空，查看当下</button></div>
    {error && <p role="alert">{error}</p>}
  </form>
}
