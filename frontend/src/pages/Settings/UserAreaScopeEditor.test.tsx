import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UserAreaScopeEditor from './UserAreaScopeEditor'
import type { AuthUser } from '../../services/auth'

type Grant = { operational_area_id: number; access_level: string }
type QueryState = { data?: unknown; isFetching: boolean; isError: boolean; refetch: () => void }
type Mutation = { mutationFn: () => Promise<unknown>; onSuccess: () => void; onError: (error: Error) => void }
const state = vi.hoisted(() => ({
  scopes: { data: undefined, isFetching: false, isError: false, refetch: vi.fn() } as QueryState,
  areas: { data: undefined, isFetching: false, isError: false, refetch: vi.fn() } as QueryState,
  mutations: [] as Mutation[], initialValues: [] as unknown[], values: [] as Grant[],
  replace: vi.fn(), validate: vi.fn(), close: vi.fn(), invalidate: vi.fn(),
}))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' }, sessionEpoch: 8 }) }))
vi.mock('../../services/auth', () => ({ authApi: { users: { scopes: vi.fn(), replaceScopes: (...args: unknown[]) => state.replace(...args) } } }))
vi.mock('../../services/mapFoundation', () => ({ mapFoundationApi: { listAreas: vi.fn() } }))
vi.mock('@tanstack/react-query', () => ({
  useQuery: ({ queryKey }: { queryKey: unknown[] }) => queryKey[0] === 'user-area-scopes' ? state.scopes : state.areas,
  useQueryClient: () => ({ invalidateQueries: state.invalidate }),
  useMutation: (options: Mutation) => { state.mutations.push(options); return { isPending: false, mutate: vi.fn() } },
}))
vi.mock('antd', () => {
  const Wrapper = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  const Form = Object.assign(({ children, initialValues }: { children?: ReactNode; initialValues?: unknown }) => {
    state.initialValues.push(initialValues)
    return <form>{children}</form>
  }, {
    useForm: () => [{ validateFields: state.validate }], Item: Wrapper,
    List: ({ children }: { children: (fields: unknown[], operations: object) => ReactNode }) => children([], { add: vi.fn(), remove: vi.fn() }),
  })
  return {
    Form, Space: Wrapper, Select: () => <select />,
    Alert: ({ message, description }: { message: ReactNode; description?: ReactNode }) => <aside>{message}{description}</aside>,
    Modal: ({ children, okButtonProps }: { children: ReactNode; okButtonProps: { disabled: boolean } }) => <section><button disabled={okButtonProps.disabled}>保存范围</button>{children}</section>,
    Button: ({ children }: { children: ReactNode }) => <button>{children}</button>,
    message: { success: vi.fn(), error: vi.fn() },
  }
})

const account = { id: 12, display_name: '合成账号', role: 'analyst' } as AuthUser
const render = (user = account) => renderToStaticMarkup(<UserAreaScopeEditor account={user} close={state.close} />)

describe('资料范围编辑使用新鲜授权与乐观冲突保护', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.scopes = { data: [{ operational_area_id: 2, access_level: 'read' }], isFetching: false, isError: false, refetch: vi.fn() }
    state.areas = { data: [{ id: 2, name: '合成厂区', status: 'active' }], isFetching: false, isError: false, refetch: vi.fn() }
    state.mutations = []; state.initialValues = []; state.values = []
    state.validate.mockImplementation(async () => ({ area_scopes: state.values }))
    state.replace.mockResolvedValue([])
  })

  it('旧缓存仍在刷新时不挂载表单也不能保存', async () => {
    state.scopes.isFetching = true
    const html = render()
    expect(html).toContain('<button disabled="">保存范围</button>')
    expect(html).toContain('正在读取范围')
    expect(html).not.toContain('<form>')
    expect(state.initialValues).toEqual([])
    await expect(state.mutations[0].mutationFn()).rejects.toThrow('最新授权')
    expect(state.replace).not.toHaveBeenCalled()
  })

  it.each(['scopes', 'areas'] as const)('%s 读取失败时隐藏缓存授权并禁用保存', key => {
    state[key].isError = true
    const html = render()
    expect(html).toContain('授权读取失败，不能保存空范围代替原配置')
    expect(html).toContain('<button disabled="">保存范围</button>')
    expect(html).not.toContain('<form>')
    expect(state.replace).not.toHaveBeenCalled()
  })

  it('新鲜读取完成后只用新范围初始化，保存携带读取时的预期范围', async () => {
    state.scopes.isFetching = true; render()
    state.scopes = { ...state.scopes, isFetching: false, data: [{ operational_area_id: 3, access_level: 'write', area_name: '新范围' }] }
    state.areas.data = [{ id: 3, name: '新范围', status: 'active' }]
    const html = render()
    expect(html).toContain('<form>')
    expect(state.initialValues).toEqual([{ area_scopes: [{ operational_area_id: 3, access_level: 'write' }] }])
    state.values = [{ operational_area_id: 3, access_level: 'read' }]
    await state.mutations[state.mutations.length - 1].mutationFn()
    expect(state.replace).toHaveBeenCalledWith(12, state.values, [{ operational_area_id: 3, access_level: 'write' }])
  })

  it('清空授权仍携带原范围，空快照也作为明确预期值发送', async () => {
    render(); await state.mutations[0].mutationFn()
    expect(state.replace).toHaveBeenLastCalledWith(12, [], [{ operational_area_id: 2, access_level: 'read' }])
    state.scopes.data = []; render()
    state.values = [{ operational_area_id: 2, access_level: 'read' }]
    await state.mutations[state.mutations.length - 1].mutationFn()
    expect(state.replace).toHaveBeenLastCalledWith(12, state.values, [])
  })

  it('409 或保存失败不关闭编辑器，也不发送第二次替换', async () => {
    state.replace.mockRejectedValue(Object.assign(new Error('账号范围已更新'), { status: 409 }))
    render()
    await expect(state.mutations[0].mutationFn()).rejects.toThrow('账号范围已更新')
    state.mutations[0].onError(new Error('账号范围已更新'))
    expect(state.close).not.toHaveBeenCalled()
    expect(state.replace).toHaveBeenCalledTimes(1)
    expect(state.invalidate).not.toHaveBeenCalled()
  })

  it('表单打开后的查询刷新不能把旧输入绑定到新授权快照', async () => {
    render()
    state.scopes.data = [{ operational_area_id: 3, access_level: 'write' }]
    state.values = [{ operational_area_id: 2, access_level: 'write' }]
    await state.mutations[0].mutationFn()
    expect(state.replace).toHaveBeenCalledWith(12, state.values, [{ operational_area_id: 2, access_level: 'read' }])
  })

  it('管理员账号不以厂区范围伪装限域账号', () => {
    const html = render({ ...account, role: 'admin' })
    expect(html).toContain('不能用厂区授权将管理员限制为普通业务人员')
    expect(html).toContain('<button disabled="">保存范围</button>')
    expect(html).not.toContain('<form>')
  })
})
