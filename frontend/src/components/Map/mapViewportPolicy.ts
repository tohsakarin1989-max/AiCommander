export interface MapLocateRequest { id: string; latitude: number; longitude: number }
export function createViewportPolicy() {
  let scope: string | undefined
  let fitted = false
  let lastRequest: string | undefined
  let lastFocus: string | undefined
  return {
    enter(nextScope: string, centered: boolean) {
      if (scope === nextScope) return
      scope = nextScope; fitted = centered; lastRequest = undefined; lastFocus = undefined
    },
    fit(preserve: boolean) { if (preserve && fitted) return false; fitted = true; return true },
    locate(request?: MapLocateRequest) {
      if (!request || request.id === lastRequest || !Number.isFinite(request.latitude) || Math.abs(request.latitude) > 85
        || !Number.isFinite(request.longitude) || Math.abs(request.longitude) > 180) return false
      lastRequest = request.id; fitted = true; return true
    },
    focus(id: string, preserve: boolean) { if (preserve && id === lastFocus) return false; lastFocus = id; fitted = true; return true },
  }
}
