import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * 心电波形可视化
 *
 * 生成一条符合 PQRST 形态的波形路径，并用滚动方式呈现"实时监测"感。
 * 纯 SVG + requestAnimationFrame，不引第三方图表库。
 */

const SAMPLES = 400

/** 生成一段带 PQRST 特征的心电信号（归一化到 -1..1） */
function beatWave(phase: number): number {
  const p = phase % 1
  let v = 0

  // P 波
  if (p > 0.04 && p < 0.16) {
    v += 0.14 * Math.sin(((p - 0.04) / 0.12) * Math.PI)
  }
  // Q 波
  if (p >= 0.18 && p < 0.22) {
    v -= 0.18 * Math.sin(((p - 0.18) / 0.04) * Math.PI)
  }
  // R 波（主峰）
  if (p >= 0.22 && p < 0.28) {
    v += 1.0 * Math.sin(((p - 0.22) / 0.06) * Math.PI)
  }
  // S 波
  if (p >= 0.28 && p < 0.34) {
    v -= 0.26 * Math.sin(((p - 0.28) / 0.06) * Math.PI)
  }
  // T 波
  if (p > 0.42 && p < 0.62) {
    v += 0.3 * Math.sin(((p - 0.42) / 0.2) * Math.PI)
  }
  return v
}

/** 依据相位偏移构造完整路径 */
function buildPath(offset: number, width: number, height: number): string {
  const mid = height / 2
  const amp = height * 0.36
  const beats = 5
  const pts: string[] = []

  for (let i = 0; i <= SAMPLES; i++) {
    const t = i / SAMPLES
    const phase = t * beats + offset
    const raw = beatWave(phase)
    // 轻微基线漂移 + 高频噪声，贴近真实信号观感
    const drift = Math.sin(t * Math.PI * 2 + offset) * 0.02
    const noise = (Math.sin(i * 12.9898 + offset * 40) * 43758.5453) % 0.012

    const x = t * width
    const y = mid - (raw + drift + noise) * amp
    pts.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`)
  }
  return pts.join(' ')
}

export function EcgWave({
  className,
  animated = true,
  strokeClass = 'text-[hsl(var(--primary))]',
}: {
  className?: string
  animated?: boolean
  strokeClass?: string
}) {
  const [offset, setOffset] = useState(0)
  const rafRef = useRef<number>(0)
  const lastRef = useRef<number>(0)

  useEffect(() => {
    if (!animated) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) return

    const loop = (now: number) => {
      if (now - lastRef.current > 33) {
        // ~30fps 足够，避免过度消耗
        lastRef.current = now
        setOffset((o) => (o + 0.035) % 1)
      }
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafRef.current)
  }, [animated])

  const W = 1000
  const H = 200
  const path = buildPath(offset, W, H)

  return (
    <div className={cn('relative', className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className={cn('h-full w-full', strokeClass)}
        aria-label="心电波形"
        role="img"
      >
        {/* 基线网格 */}
        <defs>
          <linearGradient id="ecgFade" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0" />
            <stop offset="12%" stopColor="currentColor" stopOpacity="1" />
            <stop offset="88%" stopColor="currentColor" stopOpacity="1" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
          <filter id="ecgGlow" x="-20%" y="-60%" width="140%" height="220%">
            <feGaussianBlur stdDeviation="3.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* 中轴虚线 */}
        <line
          x1="0"
          y1={H / 2}
          x2={W}
          y2={H / 2}
          stroke="currentColor"
          strokeOpacity="0.14"
          strokeWidth="1"
          strokeDasharray="3 7"
        />

        {/* 光晕层 */}
        <path
          d={path}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.28"
          strokeWidth="6"
          strokeLinejoin="round"
          strokeLinecap="round"
          filter="url(#ecgGlow)"
        />
        {/* 主线 */}
        <path
          d={path}
          fill="none"
          stroke="url(#ecgFade)"
          strokeWidth="2.2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  )
}

/** 迷你静态波形（用于卡片点缀，不跑动画以省性能） */
export function EcgSpark({ className }: { className?: string }) {
  const W = 300
  const H = 60
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={cn('text-[hsl(var(--primary))]', className)}
      aria-hidden
    >
      <path
        d={buildPath(0.2, W, H)}
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.55"
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
