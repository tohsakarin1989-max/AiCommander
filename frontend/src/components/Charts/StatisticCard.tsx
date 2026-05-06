/**
 * 统计卡片组件
 * 大屏风格的数字展示卡片
 */
import React from 'react'
import './StatisticCard.css'

export interface StatisticCardProps {
  /** 标题 */
  title: string
  /** 数值 */
  value: number | string
  /** 图标 */
  icon?: React.ReactNode
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 颜色类型 */
  type?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  /** 后缀 */
  suffix?: string
  /** 趋势（正数上升，负数下降） */
  trend?: number
  /** 子标题/描述 */
  subtitle?: string
  /** 是否显示动画效果 */
  animated?: boolean
  /** 大小 */
  size?: 'small' | 'medium' | 'large'
}

const StatisticCard: React.FC<StatisticCardProps> = ({
  title,
  value,
  icon,
  theme = 'light',
  type = 'primary',
  suffix,
  trend,
  subtitle,
  animated = true,
  size = 'medium',
}) => {
  const isDark = theme === 'dark'

  const colorMap = {
    primary: isDark ? '#00d4ff' : '#1890ff',
    success: isDark ? '#6bcb77' : '#52c41a',
    warning: isDark ? '#ffd93d' : '#faad14',
    danger: isDark ? '#ff6b6b' : '#ff4d4f',
    info: isDark ? '#a855f7' : '#722ed1',
  }

  const accentColor = colorMap[type]

  const sizeClass = `statistic-card--${size}`
  const themeClass = isDark ? 'statistic-card--dark' : 'statistic-card--light'
  const animatedClass = animated ? 'statistic-card--animated' : ''

  return (
    <div className={`statistic-card ${sizeClass} ${themeClass} ${animatedClass}`}>
      {/* 背景装饰 */}
      <div
        className="statistic-card__glow"
        style={{ background: `radial-gradient(circle, ${accentColor}20 0%, transparent 70%)` }}
      />

      {/* 图标 */}
      {icon && (
        <div className="statistic-card__icon" style={{ color: accentColor }}>
          {icon}
        </div>
      )}

      {/* 内容 */}
      <div className="statistic-card__content">
        <div className="statistic-card__title">{title}</div>
        <div className="statistic-card__value" style={{ color: accentColor }}>
          {typeof value === 'number' ? value.toLocaleString() : value}
          {suffix && <span className="statistic-card__suffix">{suffix}</span>}
        </div>

        {/* 趋势和子标题 */}
        <div className="statistic-card__footer">
          {trend !== undefined && (
            <span
              className={`statistic-card__trend ${trend >= 0 ? 'statistic-card__trend--up' : 'statistic-card__trend--down'}`}
            >
              {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}%
            </span>
          )}
          {subtitle && <span className="statistic-card__subtitle">{subtitle}</span>}
        </div>
      </div>

      {/* 边框光效 */}
      <div className="statistic-card__border" style={{ borderColor: accentColor + '40' }} />
    </div>
  )
}

export default StatisticCard
