import { useLayoutEffect, useRef } from 'react'
import { init, type EChartsCoreOption } from 'echarts'
import { mountSituationChart } from './situationChartLifecycle'

export default function SituationChart({ option, height }: { option: EChartsCoreOption; height: number }) {
  const element = useRef<HTMLDivElement>(null)
  const lifecycle = useRef<ReturnType<typeof mountSituationChart<EChartsCoreOption>> | null>(null)
  const latest = useRef(option)
  latest.current = option
  useLayoutEffect(() => {
    const node = element.current!
    const mounted = mountSituationChart(node, latest.current,
      size => init(node, undefined, size), notify => {
        const observer = new ResizeObserver(notify)
        observer.observe(node)
        return () => observer.disconnect()
      })
    lifecycle.current = mounted
    return () => { lifecycle.current = null; mounted.dispose() }
  }, [])
  useLayoutEffect(() => { lifecycle.current?.update(option) }, [option])
  return <div ref={element} style={{ height, width: '100%' }} />
}
