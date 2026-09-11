interface Chart<Option> {
  setOption: (option: Option) => void
  resize: (size: { width: number; height: number }) => void
  dispose: () => void
}

/** Never initialize/resize a hidden canvas, or revive it after unmount. */
export function mountSituationChart<Option>(
  element: HTMLElement, initial: Option,
  create: (size: { width: number; height: number }) => Chart<Option>,
  watch: (notify: () => void) => () => void,
) {
  let chart: Chart<Option> | undefined
  let option = initial
  let disposed = false
  let dirty = true
  const resize = () => {
    if (disposed || !element.isConnected || element.clientWidth <= 0 || element.clientHeight <= 0) return
    const size = { width: element.clientWidth, height: element.clientHeight }
    if (!chart) chart = create(size)
    else chart.resize(size)
    if (dirty) { chart.setOption(option); dirty = false }
  }
  const unwatch = watch(resize)
  resize()
  return {
    update(next: Option) {
      if (disposed) return
      option = next
      dirty = true
      resize()
    },
    dispose() {
      if (disposed) return
      disposed = true
      unwatch()
      chart?.dispose()
      chart = undefined
    },
  }
}
