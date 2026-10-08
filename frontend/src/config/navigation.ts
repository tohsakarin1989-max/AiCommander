export interface NavigationPage {
  label: string
  path: string
  adminOnly?: boolean
  analystOnly?: boolean
  feature?: 'bonus_accounting' | 'legacy_operations' | 'showcase' | 'agent_lab'
}
export const navigation: { label: string; pages: NavigationPage[] }[] = [
  { label: '工作台', pages: [
    { label: '日常工作', path: '/workbench' },
  ] },
  { label: '指挥大屏', pages: [{ label: '案件态势总览', path: '/dashboard' }] },
  { label: '案件资料', pages: [
    { label: '案件列表', path: '/cases' },
    { label: '奖金核算', path: '/cases/bonus', feature: 'bonus_accounting' },
  ] },
  { label: '案件研判', pages: [
    { label: '研判助手', path: '/assistant' },
    { label: '专题研判', path: '/topics', analystOnly: true },
  ] },
  { label: '空间研判', pages: [
    { label: '案件与设施地图', path: '/cases/map' },
    { label: '区域综合研判', path: '/area-analysis' }, { label: '周期态势与覆盖', path: '/situation' },
    { label: '辖区底座', path: '/jurisdiction' }, { label: '事件中心', path: '/events' },
  ] },
  { label: '研判成果', pages: [{ label: '成果与材料', path: '/reports' }] },
  { label: '高级功能', pages: [
    { label: '多模型会议', path: '/meetings' },
    { label: '经验与历史分析', path: '/case-intelligence' },
    { label: '关系图谱', path: '/graphs/serial' }, { label: '证据图谱', path: '/graphs/evidence' },
    { label: '历史部署参考', path: '/deployment', adminOnly: true },
    { label: '能力演示', path: '/showcase', analystOnly: true, feature: 'showcase' },
    { label: '自动化实验', path: '/intelli-inspect', analystOnly: true, feature: 'showcase' },
  ] },
  { label: '系统运维', pages: [
    { label: '首次启用', path: '/settings/setup', adminOnly: true },
    { label: '系统配置', path: '/settings', adminOnly: true }, { label: '用户与权限', path: '/settings/users', adminOnly: true },
    { label: '预处理维护', path: '/cases/features', adminOnly: true },
    { label: '智能运行运维', path: '/agents', adminOnly: true },
    { label: 'Agent 试用', path: '/agent-lab', adminOnly: true, feature: 'agent_lab' },
  ] },
]

type FeatureEnabled = (feature: NonNullable<NavigationPage['feature']>) => boolean
const mayShowPage = (page: NavigationPage, role: string, enabled: FeatureEnabled) =>
  (!page.adminOnly || role === 'admin') && (!page.analystOnly || role !== 'viewer') &&
  (!page.feature || enabled(page.feature))

/** Deep links remain named even when they no longer need a permanent menu entry. */
const compatibilityPages: { group: string; page: NavigationPage }[] = [
  { group: '工作台', page: { label: '待判断事项', path: '/suggestions' } },
  { group: '案件资料', page: { label: '案件工作界面', path: '/case-review' } },
  { group: '空间研判', page: { label: '区域综合研判 · 时间规律', path: '/cases/spacetime' } },
]

export function navigationContext(path: string, role: string) {
  for (const group of navigation) {
    // A disabled feature is still a known route. Its gate explains availability;
    // hiding its menu must not turn the breadcrumb into "page not found".
    const page = group.pages.find(item => item.path === path && mayShowPage(item, role, () => true))
    if (page) return { group: group.label, page }
  }
  return compatibilityPages.find(item => item.page.path === path && mayShowPage(item.page, role, () => true))
}

export function visibleNavigation(role: string, enabled: (feature: NonNullable<NavigationPage['feature']>) => boolean) {
  return navigation.map(group => ({ ...group, pages: group.pages.filter(page => mayShowPage(page, role, enabled))
  })).filter(group => group.pages.length > 0)
}
