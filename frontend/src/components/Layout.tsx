import React, { useState } from 'react'
import { Layout as AntLayout, Menu } from 'antd'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  HomeOutlined,
  DatabaseOutlined,
  TeamOutlined,
  FileTextOutlined,
  SettingOutlined,
  EnvironmentOutlined,
  ProfileOutlined,
  RobotOutlined,
  DashboardOutlined,
} from '@ant-design/icons'

const { Header, Content, Sider } = AntLayout

interface LayoutProps {
  children: React.ReactNode
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const menuItems = [
    {
      key: '/',
      icon: <HomeOutlined />,
      label: '首页',
    },
    {
      key: '/cases',
      icon: <DatabaseOutlined />,
      label: '案件管理',
    },
    {
      key: '/cases/features',
      icon: <ProfileOutlined />,
      label: '案件预处理',
    },
    {
      key: '/cases/map',
      icon: <EnvironmentOutlined />,
      label: '案件地图',
    },
    {
      key: '/meetings',
      icon: <TeamOutlined />,
      label: '圆桌会议',
    },
    {
      key: '/reports',
      icon: <FileTextOutlined />,
      label: '分析报告',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '系统设置',
    },
    {
      key: '/deployment',
      icon: <TeamOutlined />,
      label: '工作部署建议',
    },
    {
      key: '/assistant',
      icon: <RobotOutlined />,
      label: '智能助手',
    },
    {
      key: '/conclusions',
      icon: <FileTextOutlined />,
      label: '结论工厂',
    },
    {
      key: '/agents',
      icon: <RobotOutlined />,
      label: '侦查Agent',
    },
    {
      key: '/graphs/serial',
      icon: <ProfileOutlined />,
      label: '串案图谱',
    },
    {
      key: '/dashboard',
      icon: <DashboardOutlined />,
      label: '实时指挥大屏',
    },
  ]

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
      >
        <div
          style={{
            height: 32,
            margin: 16,
            background: 'rgba(0, 0, 0, 0.06)',
            borderRadius: 4,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontWeight: 'bold',
          }}
        >
          {collapsed ? 'AI' : 'AI案件分析'}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <AntLayout>
        <Header
          style={{
            padding: '0 24px',
            background: '#fff',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
          }}
        >
          <h1 style={{ margin: 0, fontSize: 20 }}>AI案件分析系统</h1>
        </Header>
        <Content
          style={{
            margin: '24px 16px',
            padding: 24,
            background: '#fff',
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
