import { describe, expect, it } from 'vitest'
import { offlineMapRequest } from './offlineMapRequest'

const id = '11111111-1111-4111-8111-111111111111'
const origin = 'http://internal.test'
describe('offline vector request boundary', () => {
  const composite = 'Noto Sans CJK SC Regular,Noto Sans Mongolian Regular,Noto Emoji Regular'
  it.each([encodeURIComponent(composite), composite.replace(/ /g, '%20')])('permits the fixed composite font %s', font => {
    const path = `/api/maps/${id}/glyphs/${font}/127744-127999.pbf`
    expect(offlineMapRequest(path, id, origin, 7).url).toBe(`${origin}${path}?operational_area_id=7`)
  })
  it.each(['Other', '%ZZ', encodeURIComponent(composite + '/extra'),
    encodeURIComponent(composite + ',Other')])('blocks unapproved font %s', font => {
    expect(() => offlineMapRequest(`/api/maps/${id}/glyphs/${font}/0-255.pbf`, id, origin, 7))
      .toThrow('offline_resource_forbidden')
  })
  it.each([`/api/maps/${id}/style.json`, `/api/maps/tiles/${id}/6/54/22`,
    `/api/maps/${id}/glyphs/Noto%20Sans%20CJK%20SC%20Regular/0-255.pbf`,
    `/api/maps/${id}/sprite@2x.png`])('keeps %s on the authorized snapshot', path => {
    const request = offlineMapRequest(path, id, origin, 7)
    expect(request.url).toBe(`${origin}${path}?operational_area_id=7`)
    expect(request.credentials).toBe('same-origin')
  })
  it.each(['https://external.test/image.png', '//external.test/image.png', '/api/cases',
    '/api/maps/current/style.json', `/api/maps/${id}/style.json?token=secret`,
    `/api/maps/${id}/style.json?operational_area_id=9`,
    `http://user:pass@internal.test/api/maps/${id}/style.json`,
    `/api/maps/${id}/style.json#fragment`])('blocks %s', path => {
    expect(() => offlineMapRequest(path, id, origin, 7)).toThrow('offline_resource_forbidden')
  })
  it('does not append a duplicate scope parameter', () => {
    expect(offlineMapRequest(`/api/maps/${id}/style.json?operational_area_id=7`, id, origin, 7).url)
      .toBe(`${origin}/api/maps/${id}/style.json?operational_area_id=7`)
  })
})
