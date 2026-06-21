import { describe, expect, it } from 'vitest'
import { connectDashboardRealtime, type DashboardSocketLike } from './dashboardRealtime'

class FakeSocket implements DashboardSocketLike {
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  closed = false

  close() {
    this.closed = true
  }
}

describe('dashboardRealtime', () => {
  it('ignores socket callbacks after cleanup closes the connection', () => {
    const events: string[] = []
    const socket = new FakeSocket()

    const connection = connectDashboardRealtime({
      socket,
      onConnectedChange: connected => events.push(`connected:${connected}`),
      onInitialData: () => events.push('initial'),
      onUpdate: () => events.push('update'),
    })

    socket.onopen?.()
    connection.cleanup()
    socket.onclose?.()
    socket.onmessage?.({ data: JSON.stringify({ type: 'update', data: {} }) })

    expect(socket.closed).toBe(true)
    expect(events).toEqual(['connected:true'])
  })

  it('routes initial data and update payloads while active', () => {
    const events: string[] = []
    const socket = new FakeSocket()

    connectDashboardRealtime({
      socket,
      onConnectedChange: connected => events.push(`connected:${connected}`),
      onInitialData: data => events.push(`initial:${data.cases.length}`),
      onUpdate: data => events.push(`update:${data.new_cases.length}`),
    })

    socket.onmessage?.({ data: JSON.stringify({ type: 'initial_data', data: { cases: [1, 2] } }) })
    socket.onmessage?.({ data: JSON.stringify({ type: 'update', data: { new_cases: [3] } }) })

    expect(events).toEqual(['initial:2', 'update:1'])
  })
})
