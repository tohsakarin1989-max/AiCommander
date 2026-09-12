import { Map, Marker, setWorkerUrl, setWorkerCount } from '/static/maplibre-gl.mjs';

setWorkerUrl('/static/maplibre-gl-worker.mjs');
setWorkerCount(1);
window.renderFrozenMap = async (input) => {
  const { basemap, map: spec, production } = input;
  const features = [...(production?.features || [])];
  const positions = [];
  const coordinate = p => Array.isArray(p) && p.length >= 2
    && typeof p[0] === 'number' && typeof p[1] === 'number'
    && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 85;
  const collect = value => {
    if (coordinate(value)) positions.push(value);
    else if (Array.isArray(value)) value.forEach(collect);
  };
  features.forEach(f => collect(f.geometry?.coordinates));
  const entrances = spec.reference_points ?? [];
  if (!Array.isArray(entrances) || entrances.length > 3
      || entrances.some((p, i) => !coordinate([p.longitude, p.latitude]) || p.rank !== i + 1 || typeof p.title !== 'string')) {
    throw new Error('facility_map_entrances_invalid');
  }
  for (const point of entrances) positions.push([point.longitude, point.latitude]);
  if (input.reference_path !== undefined) {
    if (!Array.isArray(input.reference_path) || input.reference_path.length < 2
        || input.reference_path.length > 100000 || !input.reference_path.every(coordinate)) {
      throw new Error('invalid_road_document_geometry');
    }
    input.reference_path.forEach(point => positions.push(point));
  }
  const alternatives = input.reference_alternatives ?? [];
  if (!Array.isArray(alternatives) || alternatives.length > 1) throw new Error('invalid_road_alternatives');
  for (const path of alternatives) {
    if (!input.reference_path || !Array.isArray(path) || path.length < 2
        || path.length > 100000 || !path.every(coordinate)) throw new Error('invalid_road_alternative_geometry');
    path.forEach(point => positions.push(point));
  }
  if (spec.case_marker) {
    const m = spec.case_marker;
    const point = [m.longitude, m.latitude];
    if (!coordinate(point)) throw new Error('map_projection_out_of_range');
    positions.push(point);
    features.push({ type: 'Feature', properties: { report_kind: 'case' },
      geometry: { type: 'Point', coordinates: point } });
  }
  for (const candidate of spec.candidates) {
    const r = candidate.region;
    if (!r || r.type !== 'circle' || !coordinate(r.center)
      || typeof r.radius_m !== 'number' || !Number.isFinite(r.radius_m) || r.radius_m <= 0 || r.radius_m > 100000) {
      throw new Error('map_candidate_region_invalid');
    }
    const [lng, lat] = r.center.map(v => v * Math.PI / 180);
    const angle = r.radius_m / 6371008.8;
    const ring = Array.from({ length: 65 }, (_, i) => {
      const bearing = i * Math.PI / 32;
      const y = Math.asin(Math.sin(lat) * Math.cos(angle) + Math.cos(lat) * Math.sin(angle) * Math.cos(bearing));
      const x = lng + Math.atan2(Math.sin(bearing) * Math.sin(angle) * Math.cos(lat), Math.cos(angle) - Math.sin(lat) * Math.sin(y));
      return [x * 180 / Math.PI, y * 180 / Math.PI];
    });
    if (!ring.every(coordinate)) throw new Error('map_projection_out_of_range');
    positions.push(...ring);
    features.push({ type: 'Feature', properties: { report_kind: 'candidate' },
      geometry: { type: 'Polygon', coordinates: [ring] } });
  }
  if (!positions.length) throw new Error('map_extent_missing');
  const style = basemap.renderer === 'maplibre' ? basemap.style_url : {
    version: 8, sources: { public: { type: 'raster', tiles: [basemap.tile_url], tileSize: 256,
      minzoom: basemap.min_zoom ?? 0, maxzoom: basemap.max_zoom ?? 14, bounds: basemap.bounds } },
    layers: [{ id: 'public', type: 'raster', source: 'public' }],
  };
  const map = new Map({ container: 'map', style, interactive: false, attributionControl: false,
    localIdeographFontFamily: false,
    fadeDuration: 0, renderWorldCopies: false, canvasContextAttributes: { preserveDrawingBuffer: true },
    center: positions[0], zoom: 12 });
  window.mapRenderError = null;
  map.on('error', () => { window.mapRenderError = 'map_resource_or_render_failed'; });
  await new Promise((resolve, reject) => {
    map.once('load', resolve);
    map.once('error', () => reject(new Error('map_load_failed')));
  });
  const extent = positions.reduce((box, p) => [Math.min(box[0], p[0]), Math.min(box[1], p[1]),
    Math.max(box[2], p[0]), Math.max(box[3], p[1])], [180, 85, -180, -85]);
  map.fitBounds([[extent[0], extent[1]], [extent[2], extent[3]]],
    { padding: 45, maxZoom: 14, duration: 0 });
  map.addSource('report', { type: 'geojson', data: { type: 'FeatureCollection', features } });
  map.addLayer({ id: 'report-fill', source: 'report', type: 'fill', filter: ['==', '$type', 'Polygon'],
    paint: { 'fill-color': '#d97706', 'fill-opacity': 0.18 } });
  map.addLayer({ id: 'report-line', source: 'report', type: 'line', filter: ['!=', '$type', 'Point'],
    paint: { 'line-color': '#b45309', 'line-width': 2 } });
  map.addLayer({ id: 'report-point', source: 'report', type: 'circle', filter: ['==', '$type', 'Point'],
    paint: { 'circle-radius': 7, 'circle-color': ['case', ['==', ['get', 'report_kind'], 'case'], '#dc2626', '#0369a1'],
      'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
  const entranceLabels = new globalThis.Map();
  for (const point of entrances) {
    const key = `${point.longitude},${point.latitude}`;
    const group = entranceLabels.get(key) ?? { point, ranks: [] };
    group.ranks.push(point.rank);
    entranceLabels.set(key, group);
  }
  for (const { point, ranks } of entranceLabels.values()) {
    const element = document.createElement('div');
    element.textContent = ranks.join(',');
    element.style.cssText = 'font:700 18px/24px sans-serif;color:#14532d;background:#f0fdf4;border:2px solid #15803d;border-radius:16px;min-width:24px;text-align:center';
    new Marker({ element, anchor: 'bottom' }).setLngLat([point.longitude, point.latitude]).addTo(map);
  }
  if (alternatives.length) {
    map.addSource('saved-road-alternatives', { type: 'geojson', data: { type: 'Feature', properties: {},
      geometry: { type: 'MultiLineString', coordinates: alternatives } } });
    map.addLayer({ id: 'saved-road-alternatives', source: 'saved-road-alternatives', type: 'line',
      paint: { 'line-color': '#0369a1', 'line-width': 3, 'line-dasharray': [2, 2] } });
  }
  if (input.reference_path) {
    map.addSource('saved-road', { type: 'geojson', data: { type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: input.reference_path } } });
    map.addLayer({ id: 'saved-road', source: 'saved-road', type: 'line',
      paint: { 'line-color': '#0369a1', 'line-width': 4 } });
  }
  const notes = [`地图版本：${basemap.version}；红点：案件记录位置；蓝点：引用设施；${spec.schema === 'case-facility-map-5.2-1' ? '绿色编号：本轮选定的可信入口。' : '橙色：待核验候选范围。'}`,
    ...entrances.map(p => p.title),
    ...spec.candidates.map(c => `${c.rank}. ${c.title}（待核验）`), ...spec.warnings,
    `来源：${basemap.attribution || '见成果来源记录'}。范围不代表实际路线或已确认事实。`];
  if (input.reference_path) notes.push('蓝色实线：历史留存道路参考路径，不是实际行驶轨迹，不代表当前仍可通行。');
  if (alternatives.length) notes.push('蓝色虚线：同版本留存备选路径，不代表全部可选通道。');
  document.getElementById('legend').textContent = notes.join('\n');
  await new Promise(resolve => map.once('idle', resolve));
  if (window.mapRenderError) throw new Error(window.mapRenderError);
  window.mapRenderDone = true;
};
