/**
 * 带本地缓存的 Leaflet TileLayer
 * 流程：IndexedDB 命中 → 直接显示；未命中 → fetch 后存入缓存再显示
 */

import L from 'leaflet'
import { getTile, putTile } from './tileCache'

export class CachedTileLayer extends L.TileLayer {
  createTile(coords: L.Coords, done: L.DoneCallback): HTMLElement {
    const img = document.createElement('img')
    img.alt = ''
    img.setAttribute('role', 'presentation')

    const url = this.getTileUrl(coords)

    getTile(url)
      .then((cached) => {
        if (cached) {
          // 从缓存加载
          const objUrl = URL.createObjectURL(cached)
          img.onload = () => URL.revokeObjectURL(objUrl)
          img.src = objUrl
          done(undefined, img)
        } else {
          // 从网络加载并缓存
          fetch(url)
            .then((res) => {
              if (!res.ok) throw new Error(`HTTP ${res.status}`)
              return res.blob()
            })
            .then((blob) => {
              putTile(url, blob).catch(() => {})
              const objUrl = URL.createObjectURL(blob)
              img.onload = () => URL.revokeObjectURL(objUrl)
              img.src = objUrl
              done(undefined, img)
            })
            .catch((err: unknown) => {
              done(err instanceof Error ? err : new Error(String(err)), img)
            })
        }
      })
      .catch((err: unknown) => {
        done(err instanceof Error ? err : new Error(String(err)), img)
      })

    return img
  }
}
