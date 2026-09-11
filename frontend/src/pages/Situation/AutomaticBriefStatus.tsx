type Props = {
  loading: boolean
  failed: boolean
  errorStatus?: number
  count?: number
  summary?: string
  unavailable?: boolean
  version?: string
  retry: () => void
}

export default function AutomaticBriefStatus(props: Props) {
  const missing = props.failed && props.errorStatus === 404
  const ready = !props.failed && !props.unavailable && props.count !== undefined
  return <div className="sw-auto-status" aria-live="polite">
    <span>当前自动简报</span>
    {ready ? <>
      <strong>{props.count} 项建议</strong>
      <small>{props.summary}</small>
      <code>{props.version}</code>
    </> : <>
      <strong>{props.loading ? '正在读取' : missing ? '尚无简报' : '暂不可用'}</strong>
      <small>{missing ? '尚未生成首期完整周期简报，不代表本期已有0项建议。'
        : props.loading ? '正在核对最新完整周期结果。'
          : '当前无法读取有效简报，不能据此判断没有变化或建议。'}</small>
      {!props.loading && <button className="btn-ghost" onClick={props.retry}>重新读取简报</button>}
    </>}
  </div>
}
