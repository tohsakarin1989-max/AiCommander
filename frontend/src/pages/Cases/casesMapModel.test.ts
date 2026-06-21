import { describe, expect, it } from 'vitest'
import { getCasesMapViewState } from './casesMapModel'

describe('casesMapModel', () => {
  it('shows a data-load error before any empty map state', () => {
    expect(getCasesMapViewState({
      isLoading: false,
      isError: true,
      markerCount: 0,
      totalCases: 0,
    })).toEqual({
      kind: 'error',
      message: '案件数据加载失败',
      shouldRenderMap: false,
    })
  })

  it('keeps map rendering available when only optional map config fails', () => {
    expect(getCasesMapViewState({
      isLoading: false,
      isError: false,
      mapConfigError: true,
      markerCount: 2,
      totalCases: 4,
    })).toEqual({
      kind: 'ready',
      message: null,
      shouldRenderMap: true,
      warning: '地图配置加载失败，已使用默认底图',
    })
  })

  it('shows empty only after case data loads successfully with no coordinates', () => {
    expect(getCasesMapViewState({
      isLoading: false,
      isError: false,
      markerCount: 0,
      totalCases: 3,
    })).toEqual({
      kind: 'empty',
      message: '暂无带经纬度的案件',
      shouldRenderMap: false,
    })
  })
})
