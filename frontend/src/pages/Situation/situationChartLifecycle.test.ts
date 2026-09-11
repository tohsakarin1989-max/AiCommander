import { expect, it, vi } from 'vitest'
import { mountSituationChart } from './situationChartLifecycle'

it('does not initialize a hidden chart; uses latest options when visible', () => {
  const node = { isConnected: true, clientWidth: 0, clientHeight: 0 }
  const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  const create = vi.fn(() => chart)
  let notify = () => {}
  const mounted = mountSituationChart(node as HTMLElement, { value: 1 }, create,
    callback => { notify = callback; return vi.fn() })
  mounted.update({ value: 2 })
  expect(create).not.toHaveBeenCalled()
  Object.assign(node, { clientWidth: 500, clientHeight: 200 })
  notify()
  expect(create).toHaveBeenCalledWith({ width: 500, height: 200 })
  expect(chart.setOption).toHaveBeenLastCalledWith({ value: 2 })
  mounted.dispose()
})

it('never resizes canvas to zero or recreates a disposed chart', () => {
  const node = { isConnected: true, clientWidth: 500, clientHeight: 200 }
  const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
  const create = vi.fn(() => chart)
  const unwatch = vi.fn()
  let notify = () => {}
  const mounted = mountSituationChart(node as HTMLElement, {}, create,
    callback => { notify = callback; return unwatch })
  node.clientWidth = 0
  notify()
  mounted.update({})
  expect(chart.resize).not.toHaveBeenCalled()
  expect(chart.setOption).toHaveBeenCalledOnce()
  mounted.dispose()
  node.clientWidth = 500
  notify()
  mounted.update({})
  mounted.dispose()
  expect(unwatch).toHaveBeenCalledOnce()
  expect(chart.dispose).toHaveBeenCalledOnce()
  expect(create).toHaveBeenCalledOnce()
  expect(chart.setOption).toHaveBeenCalledOnce()
})
