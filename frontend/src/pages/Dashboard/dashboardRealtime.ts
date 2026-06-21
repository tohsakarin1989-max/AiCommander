export interface DashboardSocketLike {
  onopen: ((event: any) => void) | null
  onerror: ((event: any) => void) | null
  onclose: ((event: any) => void) | null
  onmessage: ((event: any) => void) | null
  close: () => void
}

interface DashboardRealtimeOptions {
  socket: DashboardSocketLike
  onConnectedChange: (connected: boolean) => void
  onInitialData: (data: any) => void
  onUpdate: (data: any) => void
  onMalformedMessage?: () => void
}

export function connectDashboardRealtime(options: DashboardRealtimeOptions) {
  let active = true
  const { socket } = options

  const whenActive = (callback: () => void) => {
    if (active) callback()
  }

  socket.onopen = () => whenActive(() => options.onConnectedChange(true))
  socket.onerror = () => whenActive(() => options.onConnectedChange(false))
  socket.onclose = () => whenActive(() => options.onConnectedChange(false))
  socket.onmessage = (event) => whenActive(() => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'initial_data') {
        options.onInitialData(payload.data || {})
      }
      if (payload.type === 'update') {
        options.onUpdate(payload.data || {})
      }
    } catch (_) {
      options.onMalformedMessage?.()
      options.onConnectedChange(false)
    }
  })

  return {
    socket,
    cleanup: () => {
      active = false
      socket.onopen = null
      socket.onerror = null
      socket.onclose = null
      socket.onmessage = null
      socket.close()
    },
  }
}
