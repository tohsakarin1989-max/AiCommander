/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly DEV: boolean
  readonly PROD: boolean
  readonly MODE: string
  readonly BASE_URL: string
  readonly VITE_API_BASE_URL?: string
  readonly VITE_ENABLE_BONUS_ACCOUNTING?: string
  readonly VITE_MAP_TILE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
