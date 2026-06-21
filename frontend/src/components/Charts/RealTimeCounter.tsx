/**
 * 实时计数器组件
 * 带滚动数字动画的计数器
 */
import { useEffect, useState, useRef } from 'react'
import './RealTimeCounter.css'

export interface RealTimeCounterProps {
  /** 目标值 */
  value: number
  /** 动画时长（毫秒） */
  duration?: number
  /** 前缀 */
  prefix?: string
  /** 后缀 */
  suffix?: string
  /** 小数位数 */
  decimals?: number
  /** 主题 */
  theme?: 'light' | 'dark'
  /** 颜色 */
  color?: string
  /** 字体大小 */
  fontSize?: number | string
  /** 是否使用千分位分隔符 */
  useGrouping?: boolean
}

const RealTimeCounter: React.FC<RealTimeCounterProps> = ({
  value,
  duration = 1000,
  prefix = '',
  suffix = '',
  decimals = 0,
  theme = 'light',
  color,
  fontSize = 32,
  useGrouping = true,
}) => {
  const [displayValue, setDisplayValue] = useState(0)
  const previousValue = useRef(0)
  const animationRef = useRef<number>()

  useEffect(() => {
    const startValue = previousValue.current
    const endValue = value
    const startTime = performance.now()

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)

      // easeOutExpo 缓动函数
      const easeProgress = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)

      const currentValue = startValue + (endValue - startValue) * easeProgress
      setDisplayValue(currentValue)

      if (progress < 1) {
        animationRef.current = requestAnimationFrame(animate)
      } else {
        previousValue.current = endValue
      }
    }

    animationRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [value, duration])

  const formattedValue = displayValue.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping,
  })

  const defaultColor = theme === 'dark' ? '#00d4ff' : '#1890ff'
  const displayColor = color || defaultColor

  return (
    <span
      className={`realtime-counter realtime-counter--${theme}`}
      style={{
        color: displayColor,
        fontSize: typeof fontSize === 'number' ? `${fontSize}px` : fontSize,
      }}
    >
      {prefix && <span className="realtime-counter__prefix">{prefix}</span>}
      <span className="realtime-counter__value">{formattedValue}</span>
      {suffix && <span className="realtime-counter__suffix">{suffix}</span>}
    </span>
  )
}

export default RealTimeCounter
