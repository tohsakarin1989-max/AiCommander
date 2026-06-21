# AiCommander 全面升级实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 UI 深色主题化、Leaflet 地图升级、时空研判新页面、Prompt 质量优化。

**Architecture:** 前端通过 Ant Design v5 `darkAlgorithm` 全局深色主题 + 手动 token 覆盖实现统一样式；地图层用 react-leaflet 替换 ECharts 散点图，新增地图拾取器；时空研判作为独立页面；后端 Prompt 在现有文件中增补涉油专业内容。

**Tech Stack:** React 18 + TypeScript + Ant Design 5 + react-leaflet 4 + leaflet 1.9 + react-leaflet-cluster + FastAPI + pytest

---

## 文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| Modify | `frontend/package.json` | 添加 leaflet 相关依赖 |
| Modify | `frontend/src/App.tsx` | 注入 Ant Design 深色主题 token |
| Modify | `frontend/src/components/Layout.tsx` | 深色主题 + 手风琴侧边栏 |
| Create | `frontend/src/components/Map/LeafletMap.tsx` | 核心 Leaflet 地图组件 |
| Create | `frontend/src/components/Map/MapPicker.tsx` | 案件表单地图拾取器 |
| Modify | `frontend/src/pages/Cases/Cases.tsx` | 表单内嵌 MapPicker |
| Modify | `frontend/src/pages/Cases/CasesMap.tsx` | 替换 ECharts → LeafletMap |
| Create | `frontend/src/pages/Cases/SpaceTimeAnalysis.tsx` | 时空研判页面 |
| Modify | `frontend/src/App.tsx` | 注册新路由 `/cases/spacetime` |
| Modify | `frontend/src/pages/Home/Home.tsx` | 深色统计卡片 |
| Modify | `backend/app/ai/agents/analyst.py` | 涉油 Prompt 专业化 |
| Modify | `backend/app/ai/agents/moderator.py` | 报告 schema 新增字段 |

---

## Task 1: 安装前端 Leaflet 依赖

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: 安装依赖**

```bash
cd <repo>/frontend
npm install leaflet react-leaflet react-leaflet-cluster
npm install --save-dev @types/leaflet
```

- [ ] **Step 2: 验证安装成功**

```bash
cat node_modules/leaflet/package.json | grep '"version"'
cat node_modules/react-leaflet/package.json | grep '"version"'
```

预期输出：leaflet `1.9.x`，react-leaflet `4.x`

- [ ] **Step 3: Commit**

```bash
cd <repo>
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: 安装 react-leaflet 地图依赖"
```

---

## Task 2: Ant Design 全局深色主题

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 修改 App.tsx，注入深色 token**

将 `frontend/src/App.tsx` 中的 `<ConfigProvider locale={zhCN}>` 替换为：

```tsx
import { ConfigProvider, theme } from 'antd'

// 在 App() 函数内，替换 ConfigProvider：
<ConfigProvider
  locale={zhCN}
  theme={{
    algorithm: theme.darkAlgorithm,
    token: {
      colorBgBase: '#0a0e17',
      colorBgContainer: '#0d1117',
      colorBgElevated: '#0d1117',
      colorBgLayout: '#0a0e17',
      colorBorder: '#1e293b',
      colorBorderSecondary: '#1e293b',
      colorTextBase: '#e2e8f0',
      colorTextSecondary: '#94a3b8',
      colorPrimary: '#7dd3fc',
      colorPrimaryHover: '#93c5fd',
      colorLink: '#7dd3fc',
      colorSplit: '#1e293b',
    },
    components: {
      Layout: {
        siderBg: '#0d1117',
        headerBg: '#0d1117',
        bodyBg: '#0a0e17',
        triggerBg: '#1e293b',
      },
      Menu: {
        darkItemBg: '#0d1117',
        darkSubMenuItemBg: '#0a0e17',
        darkItemSelectedBg: 'rgba(125,211,252,0.12)',
        darkItemSelectedColor: '#7dd3fc',
        darkItemColor: '#cbd5e1',
      },
    },
  }}
>
```

- [ ] **Step 2: 验证前端可启动**

```bash
cd <repo>/frontend
npm run dev
```

预期：Vite 启动成功，无 TypeScript 错误。打开 http://localhost:3000 验证整体变为深色。

- [ ] **Step 3: Commit**

```bash
cd <repo>
git add frontend/src/App.tsx
git commit -m "feat: 应用 Ant Design 全局深色主题"
```

---

## Task 3: Layout 深色主题 + 手风琴侧边栏

**Files:**
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: 重写 Layout.tsx**

用以下内容完整替换 `frontend/src/components/Layout.tsx`：

```tsx
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
```

- [ ] **Step 2: 验证渲染正常**

启动前端，检查：侧边栏深色，Logo 显示 `⬡ AI案件分析`，点击分组只展开一组。

- [ ] **Step 3: Commit**

```bash
cd <repo>
git add frontend/src/components/Layout.tsx
git commit -m "feat: Layout 深色主题 + 手风琴侧边栏"
```

---

## Task 4: LeafletMap 核心组件

**Files:**
- Create: `frontend/src/components/Map/LeafletMap.tsx`

- [ ] **Step 1: 创建目录（若不存在）**

```bash
mkdir -p <repo>/frontend/src/components/Map
```

- [ ] **Step 2: 创建 LeafletMap.tsx**

创建 `frontend/src/components/Map/LeafletMap.tsx`：

```tsx
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// 修复 Leaflet 默认图标路径问题
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
})

export interface CaseMarker {
  id: number
  lat: number
  lng: number
  title: string
  caseNumber: string
  caseType?: string
  riskLevel?: 'high' | 'medium' | 'low'
  occurredTime?: string
  modus?: string
}

export interface SerialGroup {
  caseIds: number[]
  color?: string
}

interface LeafletMapProps {
  markers?: CaseMarker[]
  serialGroups?: SerialGroup[]
  height?: number | string
  center?: [number, number]
  zoom?: number
  onMarkerClick?: (marker: CaseMarker) => void
}

const RISK_COLORS: Record<string, string> = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
  default: '#7dd3fc',
}

function makeCircleIcon(color: string, count = 1): L.DivIcon {
  const size = count > 1 ? 36 : 14
  return L.divIcon({
    className: '',
    html: count > 1
      ? `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color}33;border:2px solid ${color};display:flex;align-items:center;justify-content:center;font-size:11px;color:#fff;font-weight:700">${count}</div>`
      : `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #0d1117;box-shadow:0 0 6px ${color}88"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

const LeafletMap: React.FC<LeafletMapProps> = ({
  markers = [],
  serialGroups = [],
  height = 500,
  center,
  zoom = 11,
  onMarkerClick,
}) => {
  const mapRef = useRef<L.Map | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const layersRef = useRef<L.Layer[]>([])

  // 计算默认中心（取所有 marker 的均值，或大庆市）
  const defaultCenter: [number, number] = (() => {
    if (center) return center
    if (markers.length === 0) return [46.5977, 125.1034] // 大庆市中心
    const avgLat = markers.reduce((s, m) => s + m.lat, 0) / markers.length
    const avgLng = markers.reduce((s, m) => s + m.lng, 0) / markers.length
    return [avgLat, avgLng]
  })()

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    // 初始化地图
    const map = L.map(containerRef.current, {
      center: defaultCenter,
      zoom,
      zoomControl: true,
    })
    mapRef.current = map

    // CartoDB Dark Matter 底图
    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19,
      }
    ).addTo(map)

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 更新 markers
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // 清除旧图层
    layersRef.current.forEach((l) => map.removeLayer(l))
    layersRef.current = []

    // 绘制串案连线
    serialGroups.forEach((group) => {
      const groupMarkers = markers.filter((m) => group.caseIds.includes(m.id))
      if (groupMarkers.length < 2) return
      const latlngs = groupMarkers.map((m): [number, number] => [m.lat, m.lng])
      const line = L.polyline(latlngs, {
        color: group.color || '#a78bfa',
        weight: 2,
        dashArray: '6 4',
        opacity: 0.8,
      }).addTo(map)
      layersRef.current.push(line)
    })

    // 绘制案件标记
    markers.forEach((marker) => {
      const color = RISK_COLORS[marker.riskLevel || 'default']
      const icon = makeCircleIcon(color)
      const m = L.marker([marker.lat, marker.lng], { icon })
        .addTo(map)
        .bindPopup(
          `<div style="font-size:12px;line-height:1.8;min-width:180px">
            <div style="font-weight:700;margin-bottom:4px">${marker.caseNumber}</div>
            <div>类型：${marker.caseType || '未知'}</div>
            <div>时间：${marker.occurredTime ? marker.occurredTime.slice(0, 10) : '未知'}</div>
            ${marker.modus ? `<div>手法：${marker.modus}</div>` : ''}
          </div>`,
          { maxWidth: 240 }
        )

      if (onMarkerClick) {
        m.on('click', () => onMarkerClick(marker))
      }
      layersRef.current.push(m)
    })

    // 有 markers 时自动调整视野
    if (markers.length > 0) {
      const bounds = L.latLngBounds(markers.map((m) => [m.lat, m.lng]))
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 })
    }
  }, [markers, serialGroups, onMarkerClick])

  return (
    <div
      ref={containerRef}
      style={{
        height,
        width: '100%',
        borderRadius: 6,
        overflow: 'hidden',
        border: '1px solid #1e293b',
      }}
    />
  )
}

export default LeafletMap
```

- [ ] **Step 3: 验证无 TypeScript 错误**

```bash
cd <repo>/frontend
npx tsc --noEmit 2>&1 | head -20
```

预期：无错误或仅有 leaflet-cluster CSS 路径警告（非错误）。

- [ ] **Step 4: Commit**

```bash
cd <repo>
git add frontend/src/components/Map/LeafletMap.tsx
git commit -m "feat: 新增 LeafletMap 核心地图组件（CartoDB Dark 底图）"
```

---

## Task 5: MapPicker 地图拾取器

**Files:**
- Create: `frontend/src/components/Map/MapPicker.tsx`
- Modify: `frontend/src/pages/Cases/Cases.tsx`（在 Task 5 末尾修改，集成 MapPicker）

- [ ] **Step 1: 创建 MapPicker.tsx**

创建 `frontend/src/components/Map/MapPicker.tsx`：

```tsx
import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface MapPickerProps {
  lat?: number | null
  lng?: number | null
  onChange: (lat: number, lng: number) => void
  height?: number
}

const MapPicker: React.FC<MapPickerProps> = ({
  lat,
  lng,
  onChange,
  height = 200,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const initialCenter: [number, number] =
      lat != null && lng != null ? [lat, lng] : [46.5977, 125.1034]

    const map = L.map(containerRef.current, {
      center: initialCenter,
      zoom: 12,
      zoomControl: true,
    })
    mapRef.current = map

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      {
        attribution: '© OpenStreetMap © CARTO',
        subdomains: 'abcd',
        maxZoom: 19,
      }
    ).addTo(map)

    // 若初始值存在，放置标记
    if (lat != null && lng != null) {
      markerRef.current = L.marker([lat, lng], { draggable: true }).addTo(map)
      markerRef.current.on('dragend', (e) => {
        const pos = (e.target as L.Marker).getLatLng()
        onChange(
          Math.round(pos.lat * 1000000) / 1000000,
          Math.round(pos.lng * 1000000) / 1000000
        )
      })
    }

    // 点击地图放置/移动标记
    map.on('click', (e: L.LeafletMouseEvent) => {
      const newLat = Math.round(e.latlng.lat * 1000000) / 1000000
      const newLng = Math.round(e.latlng.lng * 1000000) / 1000000

      if (markerRef.current) {
        markerRef.current.setLatLng([newLat, newLng])
      } else {
        markerRef.current = L.marker([newLat, newLng], { draggable: true }).addTo(map)
        markerRef.current.on('dragend', (ev) => {
          const pos = (ev.target as L.Marker).getLatLng()
          onChange(
            Math.round(pos.lat * 1000000) / 1000000,
            Math.round(pos.lng * 1000000) / 1000000
          )
        })
      }
      onChange(newLat, newLng)
    })

    return () => {
      map.remove()
      mapRef.current = null
      markerRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // 外部值变化时同步标记位置
  useEffect(() => {
    const map = mapRef.current
    if (!map || lat == null || lng == null) return
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng])
    } else {
      markerRef.current = L.marker([lat, lng], { draggable: true }).addTo(map)
    }
    map.setView([lat, lng])
  }, [lat, lng])

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 12,
          color: '#94a3b8',
          marginBottom: 4,
        }}
      >
        点击地图选点，或拖动标记调整位置
      </div>
      <div
        ref={containerRef}
        style={{
          height,
          width: '100%',
          borderRadius: 6,
          overflow: 'hidden',
          border: '1px solid #1e293b',
        }}
      />
    </div>
  )
}

export default MapPicker
```

- [ ] **Step 2: 在 Cases.tsx 中引入 MapPicker**

在 `frontend/src/pages/Cases/Cases.tsx` 顶部 import 区域添加：

```tsx
import MapPicker from '../../components/Map/MapPicker'
```

- [ ] **Step 3: 在 Cases.tsx 表单中添加 MapPicker**

找到以下代码（经纬度输入框结束的 `</Form.Item>` 之后，`case_type` 字段之前）：

```tsx
            </div>
          </Form.Item>

          <Form.Item name="case_type" label="类型（可选）">
```

在这两者之间插入：

```tsx
            </div>
          </Form.Item>

          <Form.Item label="地图选点（可选）">
            <MapPicker
              lat={form.getFieldValue('latitude')}
              lng={form.getFieldValue('longitude')}
              onChange={(lat, lng) => {
                form.setFieldsValue({ latitude: lat, longitude: lng })
              }}
            />
          </Form.Item>

          <Form.Item name="case_type" label="类型（可选）">
```

- [ ] **Step 4: 验证表单弹窗中地图正常显示**

启动前端，打开案件管理，点击「新建案件」，弹窗中应出现深色小地图，点击地图后经纬度字段自动填充。

- [ ] **Step 5: Commit**

```bash
cd <repo>
git add frontend/src/components/Map/MapPicker.tsx frontend/src/pages/Cases/Cases.tsx
git commit -m "feat: 新增案件表单地图拾取器（MapPicker）"
```

---

## Task 6: CasesMap 页面替换为 Leaflet

**Files:**
- Modify: `frontend/src/pages/Cases/CasesMap.tsx`

- [ ] **Step 1: 重写 CasesMap.tsx**

用以下内容完整替换 `frontend/src/pages/Cases/CasesMap.tsx`：

```tsx
import { useState } from 'react'
import { Card, Row, Col, List, Tag, Button, Spin, Space, Typography, Switch, Divider } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { EnvironmentOutlined, FireOutlined, LinkOutlined, FieldTimeOutlined } from '@ant-design/icons'
import { caseApi } from '../../services/cases'
import LeafletMap from '../../components/Map/LeafletMap'
import type { CaseMarker, SerialGroup } from '../../components/Map/LeafletMap'
import type { Case } from '../../types'

const { Text } = Typography

const RISK_COLOR: Record<string, string> = {
  high: '#ef4444',
  medium: '#f59e0b',
  low: '#22c55e',
}

const cardStyle = {
  background: '#0d1117',
  border: '1px solid #1e293b',
  borderRadius: 6,
}

const CasesMap: React.FC = () => {
  const navigate = useNavigate()
  const [showSerial, setShowSerial] = useState(true)
  const [selectedCase, setSelectedCase] = useState<Case | null>(null)

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  const { data: hotspots } = useQuery({
    queryKey: ['hotspots'],
    queryFn: () => caseApi.getHotspots(),
  })

  const { data: serialCases } = useQuery({
    queryKey: ['serialCases'],
    queryFn: () => caseApi.getSerialCases(),
  })

  const { data: geoAnalysis } = useQuery({
    queryKey: ['geoAnalysis'],
    queryFn: () => caseApi.getGeographicAnalysis(),
  })

  // 有坐标的案件 → LeafletMap markers
  const markers: CaseMarker[] = (cases || [])
    .filter((c) => c.latitude != null && c.longitude != null)
    .map((c) => ({
      id: c.id,
      lat: c.latitude!,
      lng: c.longitude!,
      title: c.case_number,
      caseNumber: c.case_number,
      caseType: c.case_type,
      riskLevel: 'medium' as const,
      occurredTime: c.occurred_time,
      modus: c.modus_operandi,
    }))

  // 串案组
  const serialGroups: SerialGroup[] = showSerial
    ? (serialCases || []).map((group: { case_ids?: number[]; cases?: { id: number }[] }, i: number) => ({
        caseIds: group.case_ids || (group.cases || []).map((c: { id: number }) => c.id),
        color: ['#a78bfa', '#f472b6', '#34d399', '#fb923c'][i % 4],
      }))
    : []

  // 热点列表（取前5）
  const topHotspots = (hotspots || []).slice(0, 5)

  // AI 巡逻建议（从 geoAnalysis 取）
  const patrolSuggestions =
    (geoAnalysis as { patrol_suggestions?: { location: string; timing?: string; reason?: string }[] } | null)
      ?.patrol_suggestions?.slice(0, 3) || []

  return (
    <div style={{ height: 'calc(100vh - 80px)', display: 'flex', gap: 12 }}>
      {/* 左侧控制面板 */}
      <div style={{ width: 200, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>图层控制</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <Text style={{ color: '#cbd5e1', fontSize: 12 }}>串案连线</Text>
              <Switch
                size="small"
                checked={showSerial}
                onChange={setShowSerial}
                style={{ '--ant-color-primary': '#7dd3fc' } as React.CSSProperties}
              />
            </div>
          </div>
        </Card>

        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>热点区域</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {topHotspots.length === 0 ? (
              <Text style={{ color: '#475569', fontSize: 11 }}>暂无热点数据</Text>
            ) : (
              topHotspots.map(
                (
                  h: { area_name?: string; cluster_center?: string; case_count?: number; risk_level?: string },
                  i: number
                ) => (
                  <div
                    key={i}
                    style={{
                      background: '#1e293b',
                      borderRadius: 4,
                      padding: '5px 8px',
                      borderLeft: `2px solid ${RISK_COLOR[h.risk_level || 'medium']}`,
                    }}
                  >
                    <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 600 }}>
                      {h.area_name || h.cluster_center || `热点 ${i + 1}`}
                    </div>
                    <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 2 }}>
                      {h.case_count || 0}起
                    </div>
                  </div>
                )
              )
            )}
          </div>
        </Card>

        <Button
          icon={<FieldTimeOutlined />}
          style={{
            background: 'rgba(125,211,252,0.1)',
            border: '1px solid #7dd3fc',
            color: '#7dd3fc',
            width: '100%',
          }}
          onClick={() => navigate('/cases/spacetime')}
        >
          时空研判
        </Button>
      </div>

      {/* 地图主体 */}
      <div style={{ flex: 1 }}>
        {isLoading ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spin tip="加载地图数据..." />
          </div>
        ) : (
          <LeafletMap
            markers={markers}
            serialGroups={serialGroups}
            height="100%"
            onMarkerClick={(m) => {
              const found = (cases || []).find((c) => c.id === m.id)
              if (found) setSelectedCase(found)
            }}
          />
        )}
      </div>

      {/* 右侧 AI 分析面板 */}
      <div style={{ width: 200, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
        {/* 选中案件详情 */}
        {selectedCase && (
          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#7dd3fc', fontSize: 11, fontWeight: 600 }}>选中案件</Text>
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#e2e8f0', fontSize: 11, fontWeight: 600 }}>{selectedCase.case_number}</div>
              <div style={{ color: '#94a3b8', fontSize: 10, marginTop: 2 }}>{selectedCase.case_type || '未分类'}</div>
              <div style={{ color: '#64748b', fontSize: 10 }}>
                {selectedCase.occurred_time?.slice(0, 10)}
              </div>
            </div>
            <Divider style={{ borderColor: '#1e293b', margin: '8px 0' }} />
            <Button
              size="small"
              type="link"
              style={{ color: '#7dd3fc', padding: 0, fontSize: 11 }}
              onClick={() => navigate(`/cases/map?caseId=${selectedCase.id}`)}
            >
              查看详情 →
            </Button>
          </Card>
        )}

        {/* AI 巡逻建议 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Space style={{ marginBottom: 8 }}>
            <FireOutlined style={{ color: '#f59e0b' }} />
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>AI巡逻建议</Text>
          </Space>
          {patrolSuggestions.length === 0 ? (
            <Text style={{ color: '#475569', fontSize: 11 }}>暂无建议，请先运行区域分析</Text>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {patrolSuggestions.map(
                (
                  s: { location: string; timing?: string; reason?: string },
                  i: number
                ) => (
                  <div
                    key={i}
                    style={{
                      background: '#1e293b',
                      borderRadius: 4,
                      padding: '5px 8px',
                      borderLeft: `2px solid ${i === 0 ? '#ef4444' : '#f59e0b'}`,
                    }}
                  >
                    <div style={{ color: i === 0 ? '#fca5a5' : '#fde68a', fontSize: 10, fontWeight: 600 }}>
                      优先级 {i + 1}
                    </div>
                    <div style={{ color: '#cbd5e1', fontSize: 10, marginTop: 2 }}>{s.location}</div>
                    {s.timing && (
                      <div style={{ color: '#64748b', fontSize: 9, marginTop: 1 }}>{s.timing}</div>
                    )}
                  </div>
                )
              )}
            </div>
          )}
        </Card>

        {/* 串案分析 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Space style={{ marginBottom: 8 }}>
            <LinkOutlined style={{ color: '#a78bfa' }} />
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>串案关联</Text>
          </Space>
          {(serialCases || []).length === 0 ? (
            <Text style={{ color: '#475569', fontSize: 11 }}>未发现串案</Text>
          ) : (
            <div style={{ color: '#7dd3fc', fontSize: 11 }}>
              发现 {(serialCases || []).length} 组串案
              <List
                size="small"
                dataSource={(serialCases || []).slice(0, 2)}
                renderItem={(group: { case_ids?: number[]; cases?: { id: number }[]; similarity_score?: number }, i: number) => (
                  <List.Item style={{ padding: '4px 0', borderBottom: '1px solid #1e293b' }}>
                    <Text style={{ color: '#94a3b8', fontSize: 10 }}>
                      组 {i + 1}：{(group.case_ids || (group.cases || []).map((c: { id: number }) => c.id)).length} 起案件
                    </Text>
                  </List.Item>
                )}
              />
            </div>
          )}
        </Card>

        {/* 图例 */}
        <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
          <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>图例</Text>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 5 }}>
            {Object.entries({ '高风险': '#ef4444', '中风险': '#f59e0b', '低风险': '#22c55e', '案件点': '#7dd3fc' }).map(([label, color]) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
                <Text style={{ color: '#94a3b8', fontSize: 11 }}>{label}</Text>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 16, height: 2, background: 'repeating-linear-gradient(90deg,#a78bfa,#a78bfa 4px,transparent 4px,transparent 7px)' }} />
              <Text style={{ color: '#94a3b8', fontSize: 11 }}>串案连线</Text>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}

export default CasesMap
```

- [ ] **Step 2: 验证地图页面正常加载**

访问 http://localhost:3000/cases/map，地图应显示深色底图，有坐标的案件显示为彩色圆点。

- [ ] **Step 3: Commit**

```bash
cd <repo>
git add frontend/src/pages/Cases/CasesMap.tsx
git commit -m "feat: 案件地图替换为 Leaflet（深色底图 + 热点 + 串案连线）"
```

---

## Task 7: 时空研判页面

**Files:**
- Create: `frontend/src/pages/Cases/SpaceTimeAnalysis.tsx`
- Modify: `frontend/src/App.tsx`（添加路由）

- [ ] **Step 1: 创建 SpaceTimeAnalysis.tsx**

创建 `frontend/src/pages/Cases/SpaceTimeAnalysis.tsx`：

```tsx
import { useState, useMemo } from 'react'
import { Card, DatePicker, Button, Row, Col, Spin, Typography, Space, Tag, Slider } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import dayjs, { Dayjs } from 'dayjs'
import { caseApi } from '../../services/cases'
import LeafletMap from '../../components/Map/LeafletMap'
import type { CaseMarker } from '../../components/Map/LeafletMap'
import type { Case } from '../../types'

const { RangePicker } = DatePicker
const { Text, Title } = Typography

const cardStyle = {
  background: '#0d1117',
  border: '1px solid #1e293b',
  borderRadius: 6,
}

const SpaceTimeAnalysis: React.FC = () => {
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(180, 'day'),
    dayjs(),
  ])
  const [isPlaying, setIsPlaying] = useState(false)
  const [playIndex, setPlayIndex] = useState(0)
  const [playSpeed] = useState(1000) // ms per step

  const { data: cases, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => caseApi.getCases(),
  })

  // 按日期范围筛选有坐标的案件，按时间排序
  const filteredCases = useMemo(() => {
    const [start, end] = dateRange
    return (cases || [])
      .filter(
        (c) =>
          c.latitude != null &&
          c.longitude != null &&
          c.occurred_time &&
          dayjs(c.occurred_time).isAfter(start) &&
          dayjs(c.occurred_time).isBefore(end)
      )
      .sort((a, b) => dayjs(a.occurred_time).valueOf() - dayjs(b.occurred_time).valueOf())
  }, [cases, dateRange])

  // 回放：显示到 playIndex 为止的案件
  const visibleMarkers: CaseMarker[] = useMemo(() => {
    const slice = isPlaying ? filteredCases.slice(0, playIndex + 1) : filteredCases
    return slice.map((c) => ({
      id: c.id,
      lat: c.latitude!,
      lng: c.longitude!,
      title: c.case_number,
      caseNumber: c.case_number,
      caseType: c.case_type,
      occurredTime: c.occurred_time,
      modus: c.modus_operandi,
    }))
  }, [filteredCases, isPlaying, playIndex])

  // 24 小时发案分布（ECharts 柱状图）
  const hourlyData = useMemo(() => {
    const counts = new Array(24).fill(0)
    filteredCases.forEach((c) => {
      if (c.occurred_time) {
        const hour = dayjs(c.occurred_time).hour()
        counts[hour]++
      }
    })
    return counts
  }, [filteredCases])

  // 周发案分布
  const weeklyData = useMemo(() => {
    const labels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
    const counts = new Array(7).fill(0)
    filteredCases.forEach((c) => {
      if (c.occurred_time) {
        counts[dayjs(c.occurred_time).day()]++
      }
    })
    return { labels, counts }
  }, [filteredCases])

  // 月度趋势
  const monthlyData = useMemo(() => {
    const monthMap: Record<string, number> = {}
    filteredCases.forEach((c) => {
      if (c.occurred_time) {
        const month = dayjs(c.occurred_time).format('YYYY-MM')
        monthMap[month] = (monthMap[month] || 0) + 1
      }
    })
    const sorted = Object.entries(monthMap).sort(([a], [b]) => a.localeCompare(b))
    return { months: sorted.map(([m]) => m), counts: sorted.map(([, c]) => c) }
  }, [filteredCases])

  // 回放控制
  const handlePlay = () => {
    if (filteredCases.length === 0) return
    setPlayIndex(0)
    setIsPlaying(true)
    const interval = setInterval(() => {
      setPlayIndex((prev) => {
        if (prev >= filteredCases.length - 1) {
          clearInterval(interval)
          setIsPlaying(false)
          return prev
        }
        return prev + 1
      })
    }, playSpeed)
  }

  const handleReset = () => {
    setIsPlaying(false)
    setPlayIndex(0)
  }

  const echartsTheme = {
    backgroundColor: 'transparent',
    textStyle: { color: '#94a3b8' },
  }

  const hourlyOption = {
    ...echartsTheme,
    grid: { top: 20, bottom: 30, left: 30, right: 10 },
    xAxis: {
      type: 'category',
      data: Array.from({ length: 24 }, (_, i) => `${i}时`),
      axisLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 9 },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#1e293b' } },
      splitLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 9 },
    },
    series: [
      {
        type: 'bar',
        data: hourlyData,
        itemStyle: {
          color: (params: { dataIndex: number }) =>
            hourlyData[params.dataIndex] === Math.max(...hourlyData) ? '#ef4444' : '#7dd3fc',
          borderRadius: [2, 2, 0, 0],
        },
      },
    ],
    tooltip: { trigger: 'axis', backgroundColor: '#0d1117', borderColor: '#1e293b', textStyle: { color: '#e2e8f0' } },
  }

  const weeklyOption = {
    ...echartsTheme,
    grid: { top: 20, bottom: 30, left: 30, right: 10 },
    xAxis: {
      type: 'category',
      data: weeklyData.labels,
      axisLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#1e293b' } },
      splitLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 9 },
    },
    series: [
      {
        type: 'bar',
        data: weeklyData.counts,
        itemStyle: { color: '#f59e0b', borderRadius: [2, 2, 0, 0] },
      },
    ],
    tooltip: { trigger: 'axis', backgroundColor: '#0d1117', borderColor: '#1e293b', textStyle: { color: '#e2e8f0' } },
  }

  const monthlyOption = {
    ...echartsTheme,
    grid: { top: 20, bottom: 30, left: 30, right: 10 },
    xAxis: {
      type: 'category',
      data: monthlyData.months,
      axisLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 9 },
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#1e293b' } },
      splitLine: { lineStyle: { color: '#1e293b' } },
      axisLabel: { color: '#64748b', fontSize: 9 },
    },
    series: [
      {
        type: 'line',
        data: monthlyData.counts,
        smooth: true,
        lineStyle: { color: '#22c55e', width: 2 },
        itemStyle: { color: '#22c55e' },
        areaStyle: { color: 'rgba(34,197,94,0.1)' },
      },
    ],
    tooltip: { trigger: 'axis', backgroundColor: '#0d1117', borderColor: '#1e293b', textStyle: { color: '#e2e8f0' } },
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: 'calc(100vh - 80px)' }}>
      {/* 顶部时间轴筛选器 */}
      <Card size="small" style={cardStyle} styles={{ body: { padding: '10px 14px' } }}>
        <Space size={16} wrap>
          <Text style={{ color: '#94a3b8', fontSize: 12 }}>时间范围：</Text>
          <RangePicker
            value={dateRange}
            onChange={(vals) => {
              if (vals && vals[0] && vals[1]) setDateRange([vals[0], vals[1]])
            }}
            style={{ background: '#1e293b', border: '1px solid #334155' }}
          />
          <Tag style={{ background: 'rgba(125,211,252,0.1)', border: '1px solid #7dd3fc', color: '#7dd3fc' }}>
            {filteredCases.length} 起案件
          </Tag>
          <Space>
            <Button
              size="small"
              icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={isPlaying ? () => setIsPlaying(false) : handlePlay}
              disabled={filteredCases.length === 0}
              style={{ background: 'rgba(125,211,252,0.1)', border: '1px solid #7dd3fc', color: '#7dd3fc' }}
            >
              {isPlaying ? '暂停' : '时间回放'}
            </Button>
            <Button
              size="small"
              icon={<StepBackwardOutlined />}
              onClick={handleReset}
              style={{ border: '1px solid #334155', color: '#94a3b8' }}
            >
              重置
            </Button>
          </Space>
          {isPlaying && filteredCases.length > 0 && (
            <Text style={{ color: '#fcd34d', fontSize: 12 }}>
              ▶ {filteredCases[playIndex]?.occurred_time?.slice(0, 10)} —— {filteredCases[playIndex]?.case_number}
            </Text>
          )}
        </Space>
      </Card>

      {/* 主体：地图 + 统计 */}
      <div style={{ flex: 1, display: 'flex', gap: 12, minHeight: 0 }}>
        {/* 地图（60%） */}
        <div style={{ flex: 3 }}>
          {isLoading ? (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Spin tip="加载数据..." />
            </div>
          ) : (
            <LeafletMap markers={visibleMarkers} height="100%" />
          )}
        </div>

        {/* 统计面板（40%） */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto' }}>
          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>24小时发案分布</Text>
            <ReactECharts option={hourlyOption} style={{ height: 120 }} />
          </Card>

          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>周发案规律</Text>
            <ReactECharts option={weeklyOption} style={{ height: 120 }} />
          </Card>

          <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
            <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>月度趋势</Text>
            <ReactECharts option={monthlyOption} style={{ height: 120 }} />
          </Card>

          {/* 简单规律摘要 */}
          {filteredCases.length > 0 && (
            <Card size="small" style={cardStyle} styles={{ body: { padding: 12 } }}>
              <Text style={{ color: '#94a3b8', fontSize: 11, letterSpacing: '0.8px' }}>规律摘要</Text>
              <div style={{ marginTop: 8 }}>
                {(() => {
                  const peakHour = hourlyData.indexOf(Math.max(...hourlyData))
                  const peakDay = weeklyData.counts.indexOf(Math.max(...weeklyData.counts))
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                        发案高峰时段：<span style={{ color: '#fcd34d' }}>{peakHour}:00 — {(peakHour + 1) % 24}:00</span>
                      </div>
                      <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                        高发星期：<span style={{ color: '#fcd34d' }}>{weeklyData.labels[peakDay]}</span>
                      </div>
                      <div style={{ color: '#cbd5e1', fontSize: 11 }}>
                        有坐标案件：<span style={{ color: '#7dd3fc' }}>{filteredCases.length} 起</span>
                      </div>
                    </div>
                  )
                })()}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

export default SpaceTimeAnalysis
```

- [ ] **Step 2: 在 App.tsx 中注册路由**

在 `frontend/src/App.tsx` 顶部 import 中添加：

```tsx
import SpaceTimeAnalysis from './pages/Cases/SpaceTimeAnalysis'
```

在 Routes 内（`/cases/features` 路由之后）添加：

```tsx
<Route path="/cases/spacetime" element={<SpaceTimeAnalysis />} />
```

- [ ] **Step 3: 验证页面加载**

访问 http://localhost:3000/cases/spacetime，应看到顶部时间筛选、左侧地图、右侧三个 ECharts 图表。

- [ ] **Step 4: Commit**

```bash
cd <repo>
git add frontend/src/pages/Cases/SpaceTimeAnalysis.tsx frontend/src/App.tsx
git commit -m "feat: 新增时空研判页面（轨迹回放 + 时间统计图表）"
```

---

## Task 8: Home 首页深色卡片

**Files:**
- Modify: `frontend/src/pages/Home/Home.tsx`

- [ ] **Step 1: 找到统计卡片区域**

在 `Home.tsx` 中找到渲染统计数据的 `<Row>` / `<Col>` / `<Card>` / `<Statistic>` 区域。

- [ ] **Step 2: 为每个统计卡片加彩色顶边**

将统计卡片的 Card 组件替换为带 `borderTop` 的深色版本。例如将：

```tsx
<Card>
  <Statistic title="案件总数" value={stats?.total_cases || 0} />
</Card>
```

替换为：

```tsx
<Card
  style={{
    background: '#0d1117',
    border: '1px solid #1e293b',
    borderTop: '2px solid #22c55e',
    borderRadius: 6,
  }}
>
  <Statistic
    title={<span style={{ color: '#94a3b8', fontSize: 12 }}>案件总数</span>}
    value={stats?.total_cases || 0}
    valueStyle={{ color: '#4ade80', fontSize: 24, fontWeight: 700 }}
  />
</Card>
```

对所有统计卡片按如下颜色对应：
- 案件总数 → `borderTop: '2px solid #22c55e'`，`valueStyle.color: '#4ade80'`
- 完成会议 → `borderTop: '2px solid #f87171'`，`valueStyle.color: '#fca5a5'`
- AI模型 → `borderTop: '2px solid #7dd3fc'`，`valueStyle.color: '#7dd3fc'`
- 分析报告 → `borderTop: '2px solid #f59e0b'`，`valueStyle.color: '#fde68a'`

- [ ] **Step 3: 验证首页卡片显示正确**

刷新 http://localhost:3000，卡片应显示深色背景 + 彩色顶边线。

- [ ] **Step 4: Commit**

```bash
cd <repo>
git add frontend/src/pages/Home/Home.tsx
git commit -m "feat: 首页统计卡片深色主题 + 彩色顶边线"
```

---

## Task 9: 后端 Prompt 优化（analyst.py）

**Files:**
- Modify: `backend/app/ai/agents/analyst.py`
- Test: `backend/tests/test_analyst_prompts.py`（新建）

- [ ] **Step 1: 新建 prompt 测试文件**

创建 `backend/tests/test_analyst_prompts.py`：

```python
"""验证 analyst prompt 包含涉油专业化内容"""
import pytest
from unittest.mock import MagicMock
from app.ai.agents.analyst import AnalystAgent


def make_agent(specialty: str | None = None) -> AnalystAgent:
    model = MagicMock()
    model.config = {"specialty": specialty}
    llm = MagicMock()
    return AnalystAgent(model, llm, specialty=specialty)


def test_spatial_prompt_mentions_pipeline():
    agent = make_agent("spatial")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "管线" in prompt or "输油" in prompt


def test_modus_prompt_mentions_oil_theft_methods():
    agent = make_agent("modus")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "打孔" in prompt or "盗油" in prompt


def test_prevention_prompt_mentions_pipeline_company():
    agent = make_agent("prevention")
    prompt = agent._build_analysis_prompt("测试案件信息")
    assert "管道" in prompt or "油田" in prompt or "保卫" in prompt


def test_all_specialties_produce_nonempty_prompt():
    for specialty in ["temporal", "spatial", "modus", "prevention", None]:
        agent = make_agent(specialty)
        prompt = agent._build_analysis_prompt("案件信息")
        assert len(prompt) > 100
```

- [ ] **Step 2: 运行测试，确认当前失败**

```bash
cd <repo>/backend
source venv/bin/activate
pytest tests/test_analyst_prompts.py -v 2>&1 | head -30
```

预期：`test_spatial_prompt_mentions_pipeline` 等失败（FAILED）。

- [ ] **Step 3: 更新 analyst.py 空间专家 prompt**

在 `backend/app/ai/agents/analyst.py` 中，找到 `elif self.specialty == "spatial":` 的 `role_desc` 字符串，在「区域聚集特征」下面补充：

```python
elif self.specialty == "spatial":
    role_desc = """
你是一名【区域聚集分析专家】。
请从空间维度分析这些已破获案件/事件，重点识别：

1. **区域聚集特征**：
   - 哪些村屯/区域事件密集？
   - 事件是否沿特定道路/输油管线（干线/集输支线）分布？
   - 哪些输油设施（油库、储油罐区、加油站）周边案件集中？
   - 是否存在明显的"热点区域"？

2. **上下游关联**：
   - 囤油点与盗油点的空间关系如何？
   - 查获罐车地点与管线盗油点的关联？
   - 是否能推断出作案团伙的活动范围（管线沿线半径内）？

3. **巡逻路线建议**：
   - 应重点巡逻哪些管线路口/路段？
   - 高风险输油设施周边5公里范围内还有哪些值得关注的点位？
   - 是否需要在特定村屯或管线阀室增设巡逻点？
"""
```

- [ ] **Step 4: 更新 analyst.py 手法专家 prompt**

找到 `elif self.specialty == "modus":` 的 `role_desc`，更新作案模板提炼部分：

```python
elif self.specialty == "modus":
    role_desc = """
你是一名【作案手法分析专家】。
请从作案手法维度分析这些已破获案件/事件，重点提炼：

1. **作案模板提炼**：
   常见涉油作案手法包括（请结合实际案件识别）：
   - 打孔盗油：在输油管线上钻孔，使用软管和泵抽取油品
   - 切割管线：截断管段直接取油
   - 偷接管线：非法接驳分支管道长期盗取
   - 罐车过驳：用罐车在隐蔽地点装载盗取油品
   - 混入合法装运：伪造运输单据掩盖非法油品
   - 常用作案工具：电钻、割管机、手摇泵、储油桶、罐车

2. **团伙特征识别**：
   - 多起事件是否可能属于同一团伙？（车牌相同/手法一致/区域重叠）
   - 专业化程度：惯犯（工具专业、路线固定）还是临时起意？
   - 是否存在"师傅带徒弟"的模仿作案或团伙分工？

3. **防范经验提炼**：
   - 针对打孔/偷接等常见手法，巡逻时应关注哪些可疑特征？
   - 哪些类型的设施（阀室/弯管/偏僻管线段）最易被作案？
   - 罐车查扣时应重点核查哪些信息（运输单据、油品来源证明）？
"""
```

- [ ] **Step 5: 更新 analyst.py 防控专家 prompt**

找到 `elif self.specialty == "prevention":` 的 `role_desc`，在联防联控部分补充管道公司：

```python
elif self.specialty == "prevention":
    role_desc = """
你是一名【防控建议专家】。
请综合所有信息，提出切实可行的巡逻防控建议：

1. **重点区域排查建议**：
   - 基于已有事件，哪些区域应优先排查？
   - 在高风险村屯周边及管线沿线，应重点寻找什么？
     （隐蔽囤油点/可疑罐车/打孔痕迹/临时接管设施）
   - 是否需要对特定管线段进行地毯式排查？

2. **巡逻策略优化**：
   - 现有巡逻路线是否覆盖高风险管线段和油库周边？
   - 应在哪些时段/路口增加巡逻频次（重点关注夜间罐车动向）？
   - 建议采用何种巡逻方式（车巡/步巡/管线徒步检查/无人机巡检）？

3. **联防联控建议**：
   - 应与哪些单位加强配合？
     · 公安机关（交警查扣过路罐车）
     · 管道公司/油田保卫部门（共享管线告警数据）
     · 周边加油站（核查可疑购油行为）
   - 是否需要发动群众线索举报（油品异味/可疑车辆/地面油污）？
   - 是否建议暂时提升该管线段的巡检频次？
"""
```

- [ ] **Step 6: 运行测试，确认通过**

```bash
cd <repo>/backend
pytest tests/test_analyst_prompts.py -v
```

预期：4 个测试全部 PASSED。

- [ ] **Step 7: Commit**

```bash
cd <repo>
git add backend/app/ai/agents/analyst.py backend/tests/test_analyst_prompts.py
git commit -m "feat: analyst prompt 涉油专业化（管线、作案手法、联防联控）"
```

---

## Task 10: 后端 Prompt 优化（moderator.py）

**Files:**
- Modify: `backend/app/ai/agents/moderator.py`
- Test: `backend/tests/test_moderator_prompts.py`（新建）

- [ ] **Step 1: 新建测试文件**

创建 `backend/tests/test_moderator_prompts.py`：

```python
"""验证 moderator 报告 schema 包含新增字段"""
from app.ai.agents.moderator import ModeratorAgent
from unittest.mock import MagicMock


def make_moderator() -> ModeratorAgent:
    model = MagicMock()
    llm = MagicMock()
    return ModeratorAgent(model, llm)


def test_final_report_prompt_contains_risk_trend():
    agent = make_moderator()
    # 通过访问 generate_final_report 的 prompt 字符串验证
    # 直接检查源码级别：prompt 中包含 risk_trend 字段
    import inspect
    source = inspect.getsource(agent.generate_final_report)
    assert "risk_trend" in source


def test_final_report_prompt_contains_infrastructure_risks():
    agent = make_moderator()
    import inspect
    source = inspect.getsource(agent.generate_final_report)
    assert "infrastructure_risks" in source
```

- [ ] **Step 2: 运行测试，确认当前失败**

```bash
cd <repo>/backend
pytest tests/test_moderator_prompts.py -v
```

预期：2 个测试 FAILED。

- [ ] **Step 3: 更新 moderator.py generate_final_report prompt**

在 `backend/app/ai/agents/moderator.py` 的 `generate_final_report` 方法中，找到 JSON schema 的 prompt 字符串（`"next_steps": [...]` 之后，`}}` 闭合之前），添加两个新字段：

```python
    "risk_trend": {{
        "direction": "increasing/stable/decreasing",
        "description": "近期发案趋势描述（如：近3个月呈上升趋势，集中在冬季）"
    }},

    "infrastructure_risks": [
        {{
            "facility_type": "设施类型（输油管线/油库/加油站/储油罐区）",
            "risk_level": "high/medium/low",
            "description": "该类设施的具体风险描述"
        }}
    ],
```

完整替换 prompt 中的 `"next_steps"` 段落，使其变为：

```python
    "next_steps": [
        "后续工作建议1",
        "后续工作建议2"
    ],

    "risk_trend": {{
        "direction": "increasing/stable/decreasing",
        "description": "近期发案趋势描述"
    }},

    "infrastructure_risks": [
        {{
            "facility_type": "设施类型（输油管线/油库/加油站）",
            "risk_level": "high/medium/low",
            "description": "该类设施的具体风险描述"
        }}
    ]
}}
```

同时更新 `generate_final_report` 的异常回退 dict，添加两个新键：

```python
result = {
    "summary": content,
    "patterns_consensus": [],
    "area_risk_assessment": [],
    "key_correlations": [],
    "patrol_action_plan": [],
    "search_priorities": [],
    "experience_extraction": [],
    "expert_contributions": {},
    "next_steps": [],
    "risk_trend": {"direction": "stable", "description": ""},
    "infrastructure_risks": [],
    "parse_error": str(e)
}
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd <repo>/backend
pytest tests/test_moderator_prompts.py -v
```

预期：2 个测试 PASSED。

- [ ] **Step 5: 运行全部后端测试**

```bash
cd <repo>/backend
pytest tests/ -v 2>&1 | tail -20
```

预期：所有测试通过，无回归。

- [ ] **Step 6: Commit**

```bash
cd <repo>
git add backend/app/ai/agents/moderator.py backend/tests/test_moderator_prompts.py
git commit -m "feat: moderator 报告新增 risk_trend 和 infrastructure_risks 字段"
```

---

## 完成验收

全部 Task 完成后，验证以下核查项：

- [ ] 整体 UI 为深色主题，无白色区域遗漏
- [ ] 侧边栏手风琴，点击分组只展开一个
- [ ] `/cases/map` 显示 CartoDB Dark 底图和案件圆点
- [ ] 新建案件弹窗中，经纬度输入框下方有迷你地图
- [ ] `/cases/spacetime` 时间回放正常，三个 ECharts 图有数据
- [ ] 后端 pytest 全部通过：`pytest backend/tests/ -v`
- [ ] 前端无 TypeScript 编译错误：`cd frontend && npx tsc --noEmit`
