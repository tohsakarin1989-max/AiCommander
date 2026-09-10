/** Leaflet uses 256px world tiles; the GL adapter maps its camera to zoom - 1. */
export function vectorZoomLimits(minNativeZoom: number, displayMaxZoom: number) {
  return {
    leafletMin: minNativeZoom + 1,
    leafletMax: displayMaxZoom + 1,
    glMin: minNativeZoom,
    glMax: displayMaxZoom,
  }
}
