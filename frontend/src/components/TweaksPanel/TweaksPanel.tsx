import { useState, useEffect, useCallback } from 'react'
import './TweaksPanel.css'

type Density  = 'comfortable' | 'compact'
type Telemetry = 'on' | 'off'
type Animation = 'normal' | 'subtle' | 'off'

interface TweaksState {
  accentHue:  number
  density:    Density
  telemetry:  Telemetry
  animation:  Animation
}

const DEFAULTS: TweaksState = {
  accentHue: 45,
  density:   'comfortable',
  telemetry: 'on',
  animation: 'normal',
}

const STORAGE_KEY = 'aic-tweaks'

function loadTweaks(): TweaksState {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return { ...DEFAULTS, ...JSON.parse(saved) }
  } catch { /* ignore */ }
  return { ...DEFAULTS }
}

function applyTweaks(s: TweaksState) {
  document.documentElement.style.setProperty('--accent-hue', String(s.accentHue))
  document.body.dataset.density   = s.density
  document.body.dataset.telemetry = s.telemetry
  document.body.dataset.animation = s.animation
}

// ── Segmented button helper ────────────────────────────────────────────────

interface SegProps<T extends string> {
  value: T
  options: { v: T; label: string }[]
  onChange: (v: T) => void
}

function Seg<T extends string>({ value, options, onChange }: SegProps<T>) {
  return (
    <div className="tw-seg">
      {options.map(o => (
        <button
          key={o.v}
          className={value === o.v ? 'on' : ''}
          onClick={() => onChange(o.v)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ── TweaksPanel ────────────────────────────────────────────────────────────

const TweaksPanel: React.FC = () => {
  const [open, setOpen] = useState(false)
  const [s, setS] = useState<TweaksState>(loadTweaks)

  // Apply whenever state changes + persist
  useEffect(() => {
    applyTweaks(s)
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)) } catch { /* ignore */ }
  }, [s])

  // Apply on mount (initial load from localStorage)
  useEffect(() => { applyTweaks(loadTweaks()) }, [])

  const set = useCallback(<K extends keyof TweaksState>(key: K, val: TweaksState[K]) => {
    setS(prev => ({ ...prev, [key]: val }))
  }, [])

  return (
    <>
      {/* ── Toggle button ── */}
      <button className="tweak-toggle" onClick={() => setOpen(o => !o)}>
        <span className="d" />
        调节
      </button>

      {/* ── Panel ── */}
      {open && (
        <div className="tweaks-panel">
          <div className="tw-head">
            <span>界面调节</span>
            <button className="tw-close" onClick={() => setOpen(false)}>×</button>
          </div>

          {/* 强调色 HUE */}
          <div className="tw-row">
            <label>
              强调色 HUE
              <span className="tw-val">{s.accentHue}°</span>
            </label>
            {/* hue preview strip */}
            <div className="tw-hue-strip" />
            <input
              type="range"
              min={0} max={360} step={5}
              value={s.accentHue}
              onChange={e => set('accentHue', +e.target.value)}
            />
          </div>

          {/* 密度 */}
          <div className="tw-row">
            <label>密度</label>
            <Seg<Density>
              value={s.density}
              options={[
                { v: 'comfortable', label: '宽松' },
                { v: 'compact',     label: '紧凑' },
              ]}
              onChange={v => set('density', v)}
            />
          </div>

          {/* 状态栏 */}
          <div className="tw-row">
            <label>状态栏</label>
            <Seg<Telemetry>
              value={s.telemetry}
              options={[
                { v: 'on',  label: '显示' },
                { v: 'off', label: '收起' },
              ]}
              onChange={v => set('telemetry', v)}
            />
          </div>

          {/* 动效 */}
          <div className="tw-row">
            <label>动效</label>
            <Seg<Animation>
              value={s.animation}
              options={[
                { v: 'normal', label: '正常' },
                { v: 'subtle', label: '轻微' },
                { v: 'off',    label: '关闭' },
              ]}
              onChange={v => set('animation', v)}
            />
          </div>

          {/* Reset */}
          <button
            className="tw-reset"
            onClick={() => setS({ ...DEFAULTS })}
          >
            恢复默认
          </button>
        </div>
      )}
    </>
  )
}

export default TweaksPanel
