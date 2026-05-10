import type { CSSProperties } from 'react'
import type { DashboardListItem } from './dashboardCommandModel'

interface AutoScrollListProps {
  items: DashboardListItem[]
  durationSeconds?: number
}

const AutoScrollList: React.FC<AutoScrollListProps> = ({ items, durationSeconds = 46 }) => {
  const safeItems = items.length > 0
    ? items
    : [{ title: '暂无数据', detail: '等待案件、链条或材料数据接入。', tone: 'empty' as const }]
  const loopItems = [...safeItems, ...safeItems]
  const style = { '--scroll-duration': `${durationSeconds}s` } as CSSProperties

  return (
    <div className="db-auto-list" style={style}>
      <div className="db-auto-track">
        {loopItems.map((item, index) => (
          <div className={`db-list-item db-list-item--${item.tone || 'normal'}`} key={`${item.title}-${index}`}>
            <strong>{item.title}</strong>
            <span>{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AutoScrollList
