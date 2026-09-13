import type { BasemapStatus } from './offlineBasemap'

export function BasemapNotice({ status, onRetry }: { status: BasemapStatus; onRetry: () => void }) {
  if (status === 'ready') return <details aria-label="底图来源与空白说明" style={{
    position: 'absolute', top: 8, left: 50, zIndex: 500,
    maxWidth: 'min(32rem, calc(100% - 66px))', padding: '6px 10px',
    color: 'var(--ink-1)', background: 'var(--bg-1)',
    border: '1px solid var(--line)', borderRadius: 4,
    fontSize: 14, lineHeight: 1.5,
  }}>
    <summary style={{ cursor: 'pointer' }}>底图空白不代表没有道路</summary>
    <p style={{ margin: '6px 0 0' }}>公开地图按来源已有资料显示，空白可能是未收录或图层未显示。
      道路是否存在、是否连通及能否通行，需结合内部资料和核验记录判断。</p>
  </details>
  return <div role="status" style={{ position: 'absolute', top: 8, left: 50, right: 8,
    zIndex: 500, padding: '8px 12px', fontSize: 14, color: 'var(--warn)',
    background: 'var(--bg-1)', border: '1px solid var(--line)', borderRadius: 4, pointerEvents: 'none' }}>
    {status === 'loading' ? '正在加载内网地图…'
      : '底图未配置或加载失败；当前覆盖物不代表底图完整，请联系管理员。'}
    {status === 'unavailable' && <button type="button" onClick={onRetry}
      style={{ marginLeft: 8, pointerEvents: 'auto' }}>重试当前地图</button>}
  </div>
}
