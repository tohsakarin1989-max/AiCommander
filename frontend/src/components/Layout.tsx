import React, { useState } from 'react'
import { Layout as AntLayout, Menu } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import type { MenuProps } from 'antd'
import {
  HomeOutlined,
  DatabaseOutlined,
  TeamOutlined,
  FileTextOutlined,
  SettingOutlined,
  EnvironmentOutlined,
  ProfileOutlined,
  RobotOutlined,
  RadarChartOutlined,
  FolderOutlined,
  BulbOutlined,
  ApartmentOutlined,
  SolutionOutlined,
  CarOutlined,
  FieldTimeOutlined,
} from '@ant-design/icons'

const { Content, Sider } = AntLayout
type MenuItem = Required<MenuProps>['items'][number]

interface LayoutProps {
  children: React.ReactNode
}

const GROUP_KEYS = ['case-analysis', 'meeting-reports', 'ai-assist', 'system']

const getInitialOpenKey = (pathname: string): string => {
  if (pathname.startsWith('/cases') || pathname.startsWith('/area') ||
      pathname.startsWith('/graphs') || pathname.startsWith('/patrols') ||
      pathname.startsWith('/gangs')) return 'case-analysis'
  if (pathname.startsWith('/meetings') || pathname.startsWith('/reports') ||
      pathname.startsWith('/conclusions') || pathname.startsWith('/deployment'))
    return 'meeting-reports'
  if (pathname.startsWith('/assistant') || pathname.startsWith('/agents'))
    return 'ai-assist'
  if (pathname.startsWith('/settings') || pathname.startsWith('/dashboard'))
    return 'system'
  return ''
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const k = getInitialOpenKey(location.pathname)
    return k ? [k] : []
  })

  const menuItems: MenuItem[] = [
    { key: '/', icon: <HomeOutlined />, label: '首页' },
    {
      key: 'case-analysis',
      icon: <FolderOutlined />,
      label: '案件分析',
      children: [
        { key: '/cases', icon: <DatabaseOutlined />, label: '案件管理' },
        { key: '/cases/map', icon: <EnvironmentOutlined />, label: '案件地图' },
        { key: '/cases/spacetime', icon: <FieldTimeOutlined />, label: '时空研判' },
        { key: '/area-analysis', icon: <RadarChartOutlined />, label: '区域研判' },
        { key: '/graphs/serial', icon: <ApartmentOutlined />, label: '串案图谱' },
        { key: '/cases/features', icon: <ProfileOutlined />, label: '案件预处理' },
        { key: '/patrols', icon: <CarOutlined />, label: '巡逻管理' },
        { key: '/gangs', icon: <TeamOutlined />, label: '团伙分析' },
      ],
    },
    {
      key: 'meeting-reports',
      icon: <TeamOutlined />,
      label: '会议与报告',
      children: [
        { key: '/meetings', icon: <TeamOutlined />, label: '圆桌会议' },
        { key: '/reports', icon: <FileTextOutlined />, label: '分析报告' },
        { key: '/conclusions', icon: <SolutionOutlined />, label: '结论工厂' },
        { key: '/deployment', icon: <BulbOutlined />, label: '工作部署建议' },
      ],
    },
    {
      key: 'ai-assist',
      icon: <RobotOutlined />,
      label: '智能辅助',
      children: [
        { key: '/assistant', icon: <RobotOutlined />, label: '智能助手' },
        { key: '/agents', icon: <RobotOutlined />, label: '侦查Agent' },
      ],
    },
    {
      key: 'system',
      icon: <SettingOutlined />,
      label: '系统管理',
      children: [
        { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
        { key: '/dashboard', icon: <RadarChartOutlined />, label: '实时指挥大屏' },
      ],
    },
  ]

  // 手风琴：同一时间只展开一个分组
  const handleOpenChange = (keys: string[]) => {
    const newKey = keys.find((k) => !openKeys.includes(k))
    setOpenKeys(newKey ? [newKey] : [])
  }

  const handleMenuClick = ({ key }: { key: string }) => {
    if (!GROUP_KEYS.includes(key)) navigate(key)
  }

  return (
    <AntLayout style={{ minHeight: '100vh', background: '#0a0e17' }}>
      <Sider width={200} style={{ background: '#0d1117', borderRight: '1px solid #1e293b' }}>
        {/* Logo */}
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            borderBottom: '1px solid #1e293b',
            color: '#7dd3fc',
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: '0.5px',
          }}
        >
          ⬡ AI案件分析
        </div>
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[location.pathname]}
          openKeys={openKeys}
          onOpenChange={handleOpenChange}
          items={menuItems}
          onClick={handleMenuClick}
          style={{ background: '#0d1117', borderRight: 'none' }}
        />
      </Sider>
      <AntLayout style={{ background: '#0a0e17' }}>
        <Content
          style={{
            margin: '16px',
            padding: 20,
            background: '#0d1117',
            borderRadius: 6,
            border: '1px solid #1e293b',
            minHeight: 280,
          }}
        >
          {children}
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

export default Layout
