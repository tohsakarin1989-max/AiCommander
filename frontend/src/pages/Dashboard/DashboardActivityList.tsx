import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AimOutlined, PauseOutlined, CaretRightOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import type { DashboardActivity } from '../../services/dashboard'
import { validMapCoordinate } from './dailyDashboardModel'

export default function DashboardActivityList({ items, onLocate, auto = true }: {
  items: DashboardActivity[]; onLocate: (point: [number, number]) => void; auto?: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const previous = useRef<Set<string> | null>(null)
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const [paused, setPaused] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const interacting = hovered || focused
  useEffect(() => {
    const keys = new Set(items.map(item => item.id))
    setFresh(new Set(previous.current ? [...keys].filter(key => !previous.current!.has(key)) : []))
    previous.current = keys
    const timer = window.setTimeout(() => setFresh(new Set()), 2000)
    return () => window.clearTimeout(timer)
  }, [items])
  useEffect(() => {
    if (!auto || paused || interacting) return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame = 0
    let last = 0
    const tick = (time: number) => {
      const element = container.current
      if (element && !media.matches && last) {
        const distance = element.scrollHeight - element.clientHeight
        if (distance > 0) {
          element.scrollTop += distance * Math.min(time - last, 100) / 45_000
          if (element.scrollTop >= distance - 1) element.scrollTop = 0
        }
      }
      last = time
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [auto, paused, interacting])
  return <>
    {auto && items.length > 0 && <Tooltip title={paused ? '继续轮播' : '暂停轮播'}><button className="activity-pause" aria-label={paused ? '继续轮播' : '暂停轮播'} aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? <CaretRightOutlined /> : <PauseOutlined />}</button></Tooltip>}
    <div ref={container} className="activity-list" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onFocus={() => setFocused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false) }}>
      {!items.length && <p className="daily-message">本期暂无可展示记录</p>}
      {items.map(item => <article key={item.id} className={fresh.has(item.id) ? 'activity-new' : ''}>
        <time dateTime={item.recorded_at}>{new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(item.recorded_at))}</time>
        <Link to={item.result_id ? `/reports?resultId=${encodeURIComponent(item.result_id)}` : `/cases?caseId=${item.case_id}`}><strong>{item.title}</strong><span>{item.case_number}</span></Link>
        {item.detail && <small>{item.detail}</small>}
        {validMapCoordinate(item.latitude, item.longitude) && <Tooltip title="地图定位"><button aria-label={`定位 ${item.case_number}`} onClick={() => onLocate([item.latitude!, item.longitude!])}><AimOutlined /></button></Tooltip>}
      </article>)}
    </div>
  </>
}
