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
    { label: '案件研判', path: '/case-intelligence' }, { label: '研判助手', path: '/assistant' },
    { label: '相似条件组', path: '/gangs' },
  ] },
  { label: '空间研判', pages: [
    { label: '案件地图', path: '/cases/map' }, { label: '时空研判', path: '/cases/spacetime' },
    { label: '态势研判', path: '/situation' }, { label: '时空区域', path: '/area-analysis' },
    { label: '辖区底座', path: '/jurisdiction' }, { label: '事件中心', path: '/events' },
    { label: '防控部署建议', path: '/deployment', adminOnly: true },
  ] },
  { label: '研判成果', pages: [{ label: '分析报告', path: '/reports' }] },
  { label: '高级功能', pages: [
    { label: '多模型会议', path: '/meetings' },
    { label: '关系图谱', path: '/graphs/serial' }, { label: '证据图谱', path: '/graphs/evidence' },
    { label: '历史情报结论', path: '/conclusions' }, { label: '历史首页', path: '/legacy-home' },
    { label: '预处理维护', path: '/cases/features', adminOnly: true },
    { label: '智能运行运维', path: '/agents', adminOnly: true },
    { label: 'Agent 试用', path: '/agent-lab', adminOnly: true, feature: 'agent_lab' },
    { label: '能力演示', path: '/showcase', analystOnly: true, feature: 'showcase' },
    { label: '自动化实验', path: '/intelli-inspect', analystOnly: true, feature: 'showcase' },
    { label: '巡逻参考', path: '/patrols', adminOnly: true, feature: 'legacy_operations' },
  ] },
  { label: '系统设置', pages: [
    { label: '系统配置', path: '/settings', adminOnly: true }, { label: '用户与权限', path: '/settings/users', adminOnly: true },
  ] },
]

export function visibleNavigation(role: string, enabled: (feature: NonNullable<NavigationPage['feature']>) => boolean) {
  return navigation.map(group => ({ ...group, pages: group.pages.filter(page =>
    (!page.adminOnly || role === 'admin') && (!page.analystOnly || role !== 'viewer') &&
    (!page.feature || enabled(page.feature)),
  ) })).filter(group => group.pages.length > 0)
}
