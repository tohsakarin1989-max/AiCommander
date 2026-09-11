/** Decode the fixed engine's polyline6 into Leaflet [latitude, longitude]. */
export function roadPolyline(encoded: string): Array<[number, number]> {
  if (!encoded || encoded.length > 2_000_000) throw new Error('无效参考路径')
  let index = 0, latitude = 0, longitude = 0
  const points: Array<[number, number]> = []
  const delta = () => {
    let value = 0, shift = 0
    while (true) {
      if (index >= encoded.length || shift > 30) throw new Error('路径编码不完整')
      const byte = encoded.charCodeAt(index++) - 63
      if (byte < 0 || byte > 63) throw new Error('无效路径字符')
      value += (byte & 31) * 2 ** shift
      if (byte < 32) break
      shift += 5
    }
    return value % 2 ? -(Math.floor(value / 2) + 1) : value / 2
  }
  while (index < encoded.length) {
    latitude += delta(); longitude += delta()
    if (Math.abs(latitude) > 85_000_000 || Math.abs(longitude) > 180_000_000 || points.length >= 100000) throw new Error('路径超出有效范围')
    points.push([latitude / 1e6, longitude / 1e6])
  }
  if (points.length < 2) throw new Error('路径点不足')
  return points
}
