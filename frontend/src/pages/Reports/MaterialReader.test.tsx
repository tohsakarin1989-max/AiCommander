import type { ReactElement, ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialReader from './MaterialReader'
import { resultsApi, type ResultMaterial } from '../../services/results'

const state = vi.hoisted(() => ({ effects: [] as (() => void | (() => void))[], refs: [] as { current: unknown }[], cursor: 0 }))
vi.mock('react', async importOriginal => ({ ...await importOriginal<typeof import('react')>(),
  useState: (initial: unknown) => [initial, vi.fn()],
  useRef: (initial: unknown) => state.refs[state.cursor++] ?? (state.refs[state.cursor - 1] = { current: initial }),
  useEffect: (effect: () => void | (() => void)) => state.effects.push(effect),
}))
vi.mock('@tanstack/react-query', () => ({ useMutation: () => ({ mutate: vi.fn(), isPending: false }) }))
vi.mock('./MaterialMap', () => ({ default: () => null }))
vi.mock('./MaterialJudgment', () => ({ default: () => null }))

const fixture = (): ResultMaterial => ({ kind: 'case', id: 'frozen-case', title: '固定案情', content_sha256: 'a'.repeat(64),
  schema_version: 'case-1', subject: { kind: 'case', id: 3 }, created_at: '2026-10-05', availability: 'available',
  body: {}, sources: [], boundary: [], judgments: [], document: { schema_version: 'document-1', blocks: [] },
  presentation: { template: 'case_summary', label: '案件资料摘要', schema_version: 'material-presentation-7.4-1',
    options: [{ id: 'full', label: '完整资料' }, { id: 'case_summary', label: '案件资料摘要' }], boundary: '通用整理格式' } })

function findElement(node: ReactNode, predicate: (node: ReactElement<Record<string, unknown>>) => boolean): ReactElement<Record<string, unknown>> | undefined {
  if (!node || typeof node !== 'object') return undefined
  if (Array.isArray(node)) return node.map(child => findElement(child, predicate)).find(Boolean)
  const element = node as ReactElement<Record<string, unknown>>
  return predicate(element) ? element : findElement(element.props?.children as ReactNode, predicate)
}

describe('材料导出异步边界', () => {
  let link: { href: string; download: string; click: ReturnType<typeof vi.fn> }
  beforeEach(() => {
    state.effects = []; state.refs = []; state.cursor = 0
    link = { href: '', download: '', click: vi.fn() }
    vi.stubGlobal('document', { createElement: vi.fn(() => link) })
    vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn(), setTimeout: vi.fn() })
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:verified'), revokeObjectURL: vi.fn() })
  })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  function reader(material = fixture(), identity = '7:1', onTemplateChange = vi.fn()) {
    state.cursor = 0
    return MaterialReader({ material, identity, allowed: true, onSaved: vi.fn(), onTemplateChange })
  }
  const startWord = (tree: ReactNode) => (findElement(tree, node => node.type === 'button' && node.props.children === '导出本版 Word')!.props.onClick as () => void)()

  it('下载使用当前格式和内容摘要，并以对应中文业务名称保存', async () => {
    const download = vi.spyOn(resultsApi, 'document').mockResolvedValue(new Blob(['verified']))
    startWord(reader())
    await vi.waitFor(() => expect(link.click).toHaveBeenCalledOnce())
    expect(download).toHaveBeenCalledWith(expect.objectContaining({ id: 'frozen-case' }), 'docx', expect.any(AbortSignal),
      { template: 'case_summary', expectedContentSha256: 'a'.repeat(64) })
    expect(link.download).toBe('案件成果-固定案情-2026-10-05-aaaaaaaa-案件资料摘要.docx')
  })
  it('对象或账号切换后迟到下载不得落盘', async () => {
    let resolve: (value: Blob) => void = () => undefined
    vi.spyOn(resultsApi, 'document').mockImplementation(() => new Promise(done => { resolve = done }))
    startWord(reader())
    reader({ ...fixture(), id: 'another-case' }, '8:2')
    resolve(new Blob(['old']))
    await Promise.resolve(); await Promise.resolve()
    expect(link.click).not.toHaveBeenCalled(); expect(URL.createObjectURL).not.toHaveBeenCalled()
  })
  it('格式切换立即终止在途导出，不能以新格式标签保存旧格式文件', async () => {
    let resolve: (value: Blob) => void = () => undefined
    const download = vi.spyOn(resultsApi, 'document').mockImplementation(() => new Promise(done => { resolve = done }))
    const change = vi.fn(); const tree = reader(fixture(), '7:1', change)
    startWord(tree)
    ;(findElement(tree, node => node.type === 'select')!.props.onChange as (event: { target: { value: string } }) => void)({ target: { value: 'full' } })
    expect(download.mock.calls[0][2]?.aborted).toBe(true); expect(change).toHaveBeenCalledWith('full')
    resolve(new Blob(['old format']))
    await Promise.resolve(); await Promise.resolve()
    expect(link.click).not.toHaveBeenCalled()
  })
  it('卸载或会话过期立即终止在途导出', async () => {
    let resolve: (value: Blob) => void = () => undefined
    const download = vi.spyOn(resultsApi, 'document').mockImplementation(() => new Promise(done => { resolve = done }))
    const tree = reader(); const cleanup = state.effects[0]() as () => void
    startWord(tree)
    const expired = vi.mocked(window.addEventListener).mock.calls.find(call => call[0] === 'aic:auth-expired')![1] as () => void
    expired(); cleanup()
    expect(download.mock.calls[0][2]?.aborted).toBe(true)
    resolve(new Blob(['old session']))
    await Promise.resolve(); await Promise.resolve()
    expect(link.click).not.toHaveBeenCalled()
  })
})
