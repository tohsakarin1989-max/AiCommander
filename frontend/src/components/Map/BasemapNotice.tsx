import type { BasemapStatus } from './offlineBasemap'

export function BasemapNotice({ status, onRetry }: { status: BasemapStatus; onRetry: () => void }) {
  if (status === 'ready') return null
  return <div role="status" style={{ position: 'absolute', top: 8, left: 50, right: 8,
    zIndex: 500, padding: '8px 12px', fontSize: 14, color: '#e2e8f0',
    background: '#0f172a', border: '1px solid #64748b', pointerEvents: 'none' }}>
    {status === 'loading' ? '正在加载内网地图…'
      : '底图未配置或加载失败；当前覆盖物不代表底图完整，请联系管理员。'}
    {status === 'unavailable' && <button type="button" onClick={onRetry}
      style={{ marginLeft: 8, pointerEvents: 'auto' }}>重试当前地图</button>}
  </div>
}
