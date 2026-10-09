import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CaseExportMenu from './CaseExportMenu'

const state = vi.hoisted(() => ({ values: [] as unknown[], index: 0, get: vi.fn(), menu: (_: { key: string }) => undefined as unknown,
  buttons: {} as Record<string, { disabled: boolean; click: () => unknown }>, click: vi.fn(), error: vi.fn(),
}))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useState: (initial: unknown) => {
  const index = state.index++
  if (state.values.length <= index) state.values[index] = initial
  return [state.values[index], (value: unknown) => { state.values[index] = typeof value === 'function' ? value(state.values[index]) : value }]
} }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'analyst' }, sessionEpoch: 1 }) }))
vi.mock('../../services/api', () => ({ default: { get: state.get } }))
vi.mock('../../components/OutputTemplatePicker', () => ({ default: () => <p>用户配置，不是官方样表</p> }))
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: [
  { key: 'case_number', label: '记录编号' }, { key: 'oil_volume', label: '数量' }, { key: 'oil_volume_unit', label: '单位' },
], isPending: false, error: null }) }))
vi.mock('antd', () => ({
  message: { success: vi.fn(), error: state.error }, Checkbox: () => null, Input: () => null,
  Dropdown: ({ menu, children }: { menu: { onClick: typeof state.menu }; children: React.ReactNode }) => { state.menu = menu.onClick; return children },
  Modal: ({ children, footer }: { children: React.ReactNode; footer: React.ReactNode }) => <section>{children}{footer}</section>,
  Space: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Button: ({ children, onClick, disabled }: { children: React.ReactNode; onClick: () => unknown; disabled: boolean }) => {
    state.buttons[String(children)] = { disabled, click: onClick }; return <button>{children}</button>
  },
}))
function render() {
  state.index = 0
  return renderToStaticMarkup(<CaseExportMenu params={{ page: 3, page_size: 10, keyword: '管线', time_basis: 'discovery' }} />)
}
describe('通用明细输出配置', () => {
  beforeEach(() => {
    vi.clearAllMocks(); state.values = [false, true, [{ key: 'case_number', label: '本单位编号' }]]
    state.get.mockResolvedValue({ data: new Blob(['sheet']) })
    vi.stubGlobal('document', { createElement: () => ({ href: '', download: '', click: state.click }) })
    vi.stubGlobal('URL', { createObjectURL: () => 'blob:sheet', revokeObjectURL: vi.fn() })
  })
  afterEach(() => vi.unstubAllGlobals())
  it('不重复输入业务内容，导出使用全筛选与用户列映射，不携带分页', async () => {
    const html = render()
    expect(html).toContain('全部授权匹配记录'); expect(html).toContain('未经过单位官方表样确认')
    state.menu({ key: 'xlsx' })
    await vi.waitFor(() => expect(state.click).toHaveBeenCalledOnce())
    expect(state.get).toHaveBeenCalledWith('/case-exports/ledger.xlsx', expect.objectContaining({ params: {
      keyword: '管线', time_basis: 'discovery', output_configuration: JSON.stringify({ columns: [{ key: 'case_number', label: '本单位编号' }] }),
    } }))
  })
  it('数量缺单位时禁用导出，菜单也不能绕过', () => {
    state.values[2] = [{ key: 'case_number', label: '编号' }, { key: 'oil_volume', label: '数量' }]
    expect(render()).toContain('数量必须与单位同时导出')
    expect(state.buttons['导出 Excel'].disabled).toBe(true)
    state.menu({ key: 'xlsx' })
    expect(state.get).not.toHaveBeenCalled()
  })
})
