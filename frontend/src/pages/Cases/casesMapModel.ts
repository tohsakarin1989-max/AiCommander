export type CasesMapViewState =
  | { kind: 'loading'; message: string; shouldRenderMap: false }
  | { kind: 'error'; message: string; shouldRenderMap: false }
  | { kind: 'empty'; message: string; shouldRenderMap: false }
  | { kind: 'ready'; message: null; shouldRenderMap: true; warning?: string }

interface CasesMapViewStateInput {
  isLoading: boolean
  isError?: boolean
  mapConfigError?: boolean
  markerCount: number
  totalCases: number
}

export function getCasesMapViewState(input: CasesMapViewStateInput): CasesMapViewState {
  if (input.isLoading) {
    return {
      kind: 'loading',
      message: '加载地图数据...',
      shouldRenderMap: false,
    }
  }

  if (input.isError) {
    return {
      kind: 'error',
      message: '案件数据加载失败',
      shouldRenderMap: false,
    }
  }

  if (input.markerCount === 0) {
    return {
      kind: 'empty',
      message: input.totalCases > 0 ? '暂无带经纬度的案件' : '暂无案件数据',
      shouldRenderMap: false,
    }
  }

  return {
    kind: 'ready',
    message: null,
    shouldRenderMap: true,
    ...(input.mapConfigError ? { warning: '地图配置加载失败，已使用默认底图' } : {}),
  }
}
