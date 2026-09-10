import { lazy, Suspense, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { showcaseApi, type ShowcaseRecord, type ShowcaseScenario } from '../../services/showcase'
import './Showcase.css'
import { useAuth } from '../../auth/AuthContext'
import { clearDeniedShowcaseHistory } from './showcaseCache'
const ShowcaseMap = lazy(() => import('./ShowcaseMap'))

const scenarios: { id: ShowcaseScenario; title: string; detail: string }[] = [
  { id: 'normal', title: '一次录入，形成证据', detail: '导入内置中文CSV → 标准画像 → 设施候选 → 简报' },
  { id: 'missing_location', title: '证据不足，明确停止', detail: '移除坐标，观察信息缺口与空候选' },
  { id: 'model_unavailable', title: '模型故障，业务继续', detail: '在隔离实例注入超时，保留规则计算结果' },
]

function Lines({ values }: { values: string[] }) {
  return values.length ? <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul> : <p>无记录</p>
}

export default function Showcase() {
  const client = useQueryClient()
  const { user, sessionEpoch } = useAuth()
  const historyKey = ['showcase-history', user?.id, sessionEpoch]
  const generation = useRef(0)
  const deniedRef = useRef(false)
  const [denied, setDenied] = useState(false)
  const [record, setRecord] = useState<ShowcaseRecord | null>(null)
  const [request, setRequest] = useState<{ scenario: ShowcaseScenario; id: string } | null>(null)
  const reject = (error: unknown) => {
    if ([401, 403, 404].includes((error as { status?: number }).status || 0)) {
      deniedRef.current = true; generation.current++; setDenied(true); setRecord(null); setRequest(null)
      void clearDeniedShowcaseHistory(client, historyKey)
    }
  }
  const history = useQuery({ queryKey: historyKey, queryFn: async ({ signal }) => {
    try {
      const data = await showcaseApi.history(signal)
      return deniedRef.current ? { items: [] } : data
    } catch (error) { reject(error); throw error }
  }, retry: false, enabled: !denied })
  const run = useMutation({ mutationFn: (input: { scenario: ShowcaseScenario; id: string; generation: number }) => showcaseApi.create(input.scenario, input.id),
    onError: reject,
    onSuccess: (data, input) => { if (!deniedRef.current && input.generation === generation.current) {
      setRecord(data); setRequest(null); void client.invalidateQueries({ queryKey: historyKey })
    } } })
  const replay = useMutation({ mutationFn: (input: { id: string; generation: number }) => showcaseApi.read(input.id), onError: reject,
    onSuccess: (data, input) => { if (!deniedRef.current && input.generation === generation.current) setRecord(data) } })
  const busy = run.isPending || replay.isPending
  const result = record?.result
  const casePoint = useMemo(() => ({ name: '合成案件（非真实案发点）',
    latitude: result?.case?.latitude ?? null, longitude: result?.case?.longitude ?? null }), [result])
  const start = (scenario: ShowcaseScenario) => {
    const input = { scenario, id: crypto.randomUUID() }
    run.reset(); replay.reset(); setRequest(input); setRecord(null)
    run.mutate({ ...input, generation: ++generation.current })
  }
  const openReplay = (id: string) => {
    run.reset(); replay.reset(); setRecord(null); setRequest(null)
    replay.mutate({ id, generation: ++generation.current })
  }

  return <main className="showcase">
    <header className="showcase-intro">
      <span className="showcase-kicker">业务能力展示 / SYNTHETIC DATA</span>
      <h1>从一条案件，到可核对的依据</h1>
      <p>调用日常系统同一套业务服务。所有案件、设施与坐标均为合成数据，不读取正式案件，不向外部模型发送信息。</p>
      <p>这是实时规则计算，不冒充实时大模型推理；故障注入不是实际服务停机。</p>
    </header>
    {history.isPending && <p role="status">正在检查展示服务…</p>}
    {(history.isError || denied) && <div role="alert" className="showcase-notice">展示服务未启用、无访问权限或暂不可用。请联系管理员检查 ENABLE_SHOWCASE；日常业务不受影响。</div>}
    <section className="showcase-scenarios" aria-label="展示场景">
      {scenarios.map(item => <button key={item.id} disabled={busy || !history.isSuccess || denied} onClick={() => start(item.id)}>
        <strong>{item.title}</strong><span>{item.detail}</span>
      </button>)}
    </section>
    {busy && <p role="status">正在{run.isPending ? '隔离运行真实业务服务' : '读取历史结果'}…</p>}
    {(run.isError || replay.isError) && <div role="alert">请求未完成，不能据此判断服务已成功执行。
      {request && !denied && <button disabled={busy} onClick={() => { replay.reset(); setRecord(null); run.mutate({ ...request, generation: ++generation.current }) }}>按原请求重试（不重复运行）</button>}</div>}
    <div className="showcase-content">
      <section aria-label="运行结果">
        {!record && !busy && <p className="showcase-empty">选择一个场景，查看真实运行结果及其边界。</p>}
        {record && !denied && !history.isError && <>
          <div className="showcase-result-heading"><h2>{record.view_kind === 'live_result' ? '本次运行结果' : '历史轨迹回放'}</h2>
            <span>{record.status === 'completed' ? '运行结束' : record.status === 'expired' ? '运行已过期' : record.status === 'failed' ? '运行失败' : '运行未结束'}</span></div>
          <p>{record.view_kind === 'historical_replay' ? '读取已保存结果，未重新执行工具。' : '以下内容由本次服务调用生成。'} 记录时间：{record.created_at}</p>
          {record.error && <p role="alert">{record.error}</p>}
          {result?.import && <section className="showcase-section"><h3>00 / 真实 CSV 导入</h3>
            <p>内置合成文件 {result.import.filename}，成功解析 {result.import.rows} 行；时间解释：{result.import.time_zone}。</p>
            <p>此入口仅导入内置合成样本，不接收正式案件文件。使用日常导入相同的解析、标准化及保存服务。</p>
            <details><summary>查看导入原文、字段映射与摘要</summary><pre>{result.import.csv}</pre>
              <pre>{JSON.stringify(result.import.field_mapping, null, 2)}</pre><code>{result.import.sha256}</code></details>
          </section>}
          {result?.case && <section className="showcase-section"><h3>01 / 合成输入与画像</h3>
            <p>{result.case.description}</p><p>案发时间：{result.case.occurred_time} · {result.case.location}</p>
            <p>原始事实：{result.original_facts_unchanged ? '运行前后摘要一致' : '一致性未通过'}</p>
            <details><summary>查看标准画像与版本</summary><p>{result.profile?.schema_version} / {result.profile?.dictionary_version}</p>
              <pre>{JSON.stringify(result.profile?.payload, null, 2)}</pre></details></section>}
          {result?.map_features && <Suspense fallback={<p role="status">正在加载地图组件…</p>}>
            <ShowcaseMap casePoint={casePoint} facilities={result.map_features} /></Suspense>}
          {result?.analysis && <section className="showcase-section"><h3>02 / 候选与反向证据</h3>
            <p>算法：{result.analysis.algorithm_version} · {result.analysis.summary}</p>
            {result.analysis.hypotheses.length === 0 && <p>没有候选；不为展示补造推断。</p>}
            {result.analysis.hypotheses.map(item => <article className="showcase-candidate" key={item.id}>
              <h4>{item.title}</h4><p>{item.claim}</p><p>规则支持度：{item.score}（不是准确概率）</p>
              <h5>支持依据</h5><Lines values={item.supporting_evidence} />
              <h5>反向证据与信息缺口</h5><Lines values={[...item.counter_evidence, ...item.information_gaps]} />
              <details><summary>证据编号与边界</summary><Lines values={item.evidence_refs} /><p>{item.boundary}</p></details>
            </article>)}<Lines values={result.analysis.information_gaps} /></section>}
          {result?.brief && <section className="showcase-section"><h3>03 / 本次成果简报</h3><p>{result.brief.summary}</p>
            <p>简报按本次成果生成时间统计，不把成果生成时间当作案发时间。</p>
            <Lines values={result.brief.information_gaps} /><details><summary>简报引用</summary><Lines values={result.brief.evidence_refs} /></details></section>}
          {result?.fault && <div className="showcase-notice">故障演练：注入模型超时 {result.fault.calls} 次，实际执行器返回 {result.fault.status}，降级方式 {result.fault.fallback_mode}。</div>}
          {result?.trace && <section className="showcase-section"><h3>真实调用轨迹</h3><ol>{result.trace.map(step => <li key={step.sequence}>
            {step.service} · {step.duration_ms} ms · {step.result_status === 'degraded' ? '业务降级' : step.result_status || '已返回'}
          </li>)}</ol><p>{result.boundary}</p><details><summary>输入与版本追溯</summary>
            <p>{result.dataset_version}</p><code>{result.input_digest}</code><p>展示记录：{record.id}</p></details></section>}
        </>}
      </section>
      <aside><h2>历史回放</h2><p>仅显示当前账号最近 20 次。</p>
        {history.data?.items.length === 0 && <p>暂无运行记录。</p>}
        {!denied && !history.isError && history.data?.items.map(item => <button className="showcase-history" key={item.id} disabled={busy} onClick={() => openReplay(item.id)}>
          {scenarios.find(s => s.id === item.scenario)?.title}<small>{item.created_at} · {item.status}</small>
        </button>)}
      </aside>
    </div>
  </main>
}
