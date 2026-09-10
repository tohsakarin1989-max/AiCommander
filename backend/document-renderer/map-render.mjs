import { Map, setWorkerUrl, setWorkerCount } from '/static/maplibre-gl.mjs';

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
    fadeDuration: 0, renderWorldCopies: false, canvasContextAttributes: { preserveDrawingBuffer: true },
    center: positions[0], zoom: 12 });
  window.mapRenderError = null;
  map.on('error', () => { window.mapRenderError = 'map_resource_or_render_failed'; });
  await new Promise((resolve, reject) => {
    map.once('load', resolve);
    map.once('error', () => reject(new Error('map_load_failed')));
  });
  const xs = positions.map(p => p[0]), ys = positions.map(p => p[1]);
  map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]],
    { padding: 45, maxZoom: 14, duration: 0 });
  map.addSource('report', { type: 'geojson', data: { type: 'FeatureCollection', features } });
  map.addLayer({ id: 'report-fill', source: 'report', type: 'fill', filter: ['==', '$type', 'Polygon'],
    paint: { 'fill-color': '#d97706', 'fill-opacity': 0.18 } });
  map.addLayer({ id: 'report-line', source: 'report', type: 'line', filter: ['!=', '$type', 'Point'],
    paint: { 'line-color': '#b45309', 'line-width': 2 } });
  map.addLayer({ id: 'report-point', source: 'report', type: 'circle', filter: ['==', '$type', 'Point'],
    paint: { 'circle-radius': 7, 'circle-color': ['case', ['==', ['get', 'report_kind'], 'case'], '#dc2626', '#0369a1'],
      'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
  const notes = [`地图版本：${basemap.version}；红点：案件记录位置；蓝点：引用设施；橙色：待核验候选范围。`,
    ...spec.candidates.map(c => `${c.rank}. ${c.title}（待核验）`), ...spec.warnings,
    `来源：${basemap.attribution || '见成果来源记录'}。范围不代表实际路线或已确认事实。`];
  document.getElementById('legend').textContent = notes.join('\n');
  await new Promise(resolve => map.once('idle', resolve));
  if (window.mapRenderError) throw new Error(window.mapRenderError);
  window.mapRenderDone = true;
};
