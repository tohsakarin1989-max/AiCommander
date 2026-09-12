import type { ReactNode } from 'react'
import { useRuntimeFeatures } from '../config/useRuntimeFeatures'
import type { RuntimeFeatures } from '../services/runtime'

export default function RuntimeFeatureGate({ feature, label, children }: {
  feature: keyof RuntimeFeatures
  label: string
  children: ReactNode
}) {
  const { availability, query } = useRuntimeFeatures()
  const state = availability[feature]
  if (state === 'enabled') return <>{children}</>
  return <div className="empty-state" style={{ height: '60vh' }} role={state === 'unavailable' ? 'alert' : 'status'}>
    <div>{state === 'loading' ? `正在确认${label}是否可用…`
      : state === 'disabled' ? `${label}未启用` : `${label}状态暂不可用`}</div>
    <p>{state === 'disabled' ? '当前部署未启用此功能，可继续使用其他已启用模块。'
      : state === 'unavailable' ? '未能读取后台功能状态，暂时无法确认是否启用。' : '请稍候。'}</p>
    {state === 'unavailable' && <button className="btn-ghost" onClick={() => void query.refetch()}>重新读取功能状态</button>}
  </div>
}
