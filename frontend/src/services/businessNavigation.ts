import { businessContextKeys, caseContextPath } from './caseContext'

const readingPaths = new Set(['/cases', '/cases/map', '/case-intelligence', '/graphs/evidence', '/graphs',
  '/assistant', '/topics', '/reports', '/jurisdiction', '/area-analysis', '/events', '/dashboard', '/workbench'])
const returnKeys = [...businessContextKeys, 'topic', 'revision', 'resultId', 'kind', 'materialId', 'subject', 'subjectId', 'query', 'source', 'sourceId', 'catalogQ', 'catalogKind', 'catalogOffset', 'meetingId']

/** One-level, same-app return location. Never copy credentials or nested URLs. */
export function safeBusinessReturn(value: string | null): string | null {
  if (!value || value.length > 4096 || !value.startsWith('/') || value.startsWith('//') || /[\\\r\n]/.test(value)) return null
  const [path, query = ''] = value.split('?')
  if (!readingPaths.has(path) || query.includes('#')) return null
  const source = new URLSearchParams(query), selected = new URLSearchParams()
  for (const key of returnKeys) for (const item of source.getAll(key)) selected.append(key, item)
  return `${path}${selected.size ? `?${selected}` : ''}`
}

export function businessContextPath(target: string, source: URLSearchParams, originPath: string): string {
  const [path, query = ''] = caseContextPath(target, source).split('?')
  const next = new URLSearchParams(query)
  const back = safeBusinessReturn(source.get('return_to')) ?? safeBusinessReturn(`${originPath}?${source}`)
  // The facility remains in the return location. It must not reopen the global
  // drawer over the material that the user just chose to read.
  if (path === '/reports') next.delete('assetId')
  if (back && back !== path) next.set('return_to', back)
  return `${path}${next.size ? `?${next}` : ''}`
}

export function retainTopicSelection(previous: URLSearchParams, topic: string, revision?: number) {
  const next = new URLSearchParams(previous)
  next.set('topic', topic); next.delete('revision'); next.delete('source'); next.delete('sourceId')
  if (revision != null) next.set('revision', String(revision))
  return next
}
