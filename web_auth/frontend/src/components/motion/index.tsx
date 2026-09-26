import * as React from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { cn } from '@/lib/utils'

/* ============================================================
   动效原语
   统一入场 / 滚动揭示 / 交错动画，全部遵循 prefers-reduced-motion

   鲁棒性约定（重要）：
     所有「入场即隐藏」的动效都带一个安全兜底——若动画在 1.2s 内未启动
     或渲染环境不支持（如无头浏览器、动画被阻断），元素会自动回到可见
     状态。绝不允许出现「JS 没跑完 → 页面一片空白」的失效模式。
   ============================================================ */

const EASE = [0.22, 1, 0.36, 1] as const

/**
 * 安全兜底：超时后强制可见。
 *
 * 设计约束（踩过坑，务必保留）：
 *   入场动效的「隐藏态」是靠 framer-motion 下发 `initial` 实现的。如果动画因为
 *   任何原因没跑完（无头渲染、标签页后台节流、异常中断），元素会永久停在
 *   opacity:0，页面看起来就是空白。所以每个动效原语都必须**自己**持有兜底开关，
 *   不能依赖父级 variants 传播——父级重渲染时子级可能收不到新的 variant 变更，
 *   从而永远卡在 hidden。
 */
function useVisibilityFallback(delayMs = 1200) {
  const [forced, setForced] = React.useState(false)
  React.useEffect(() => {
    const id = window.setTimeout(() => setForced(true), delayMs)
    return () => window.clearTimeout(id)
  }, [delayMs])
  return forced
}

const StaggerItemContext = React.createContext<{
  delay: number
  stagger: number
  index: number
}>({ delay: 0, stagger: 0, index: 0 })

/** 交错容器：只负责节奏，不向下传播 variants（子项自行控制显隐） */
export function StaggerGroup({
  children,
  className,
  delay = 0,
  stagger = 0.08,
  as = 'div',
}: {
  children: React.ReactNode
  className?: string
  delay?: number
  stagger?: number
  as?: 'div' | 'section' | 'ul'
}) {
  const Comp = motion[as] as typeof motion.div
  const reduce = useReducedMotion()

  // 通过 context 把「第几个子项」传下去，子项据此计算自己的延迟。
  // 这样彻底摆脱 variants 传播：每个子项都是独立的、自洽的动画单元，
  // 父级重渲染不会让子项卡在 hidden。
  const base = React.useMemo(
    () => ({ delay: reduce ? 0 : delay, stagger: reduce ? 0 : stagger }),
    [delay, stagger, reduce]
  )

  const items = React.Children.map(children, (child, i) => {
    if (!React.isValidElement(child)) return child
    return (
      <StaggerItemContext.Provider value={{ ...base, index: i }}>
        {child}
      </StaggerItemContext.Provider>
    )
  })

  return <Comp className={className}>{items}</Comp>
}

/** 交错子项：自带 initial/animate，不依赖父级 variants */
export function StaggerItem({
  children,
  className,
  y = 18,
  as = 'div',
}: {
  children: React.ReactNode
  className?: string
  y?: number
  as?: 'div' | 'li' | 'section'
}) {
  const Comp = motion[as] as typeof motion.div
  const reduce = useReducedMotion()
  const forced = useVisibilityFallback(1000)
  const { delay, stagger, index } = React.useContext(StaggerItemContext)
  const instant = reduce || forced

  return (
    <Comp
      className={className}
      initial={{ opacity: 0, y: instant ? 0 : y }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        instant
          ? { duration: 0 }
          : { duration: 0.55, delay: delay + index * stagger, ease: EASE }
      }
    >
      {children}
    </Comp>
  )
}

/**
 * 滚动进入视口时揭示。
 *
 * 兜底策略与入场动画不同：视口外的元素**本就应该**保持隐藏，所以不能无条件
 * 定时强制显示（否则滚动揭示效果会被破坏）。这里只在元素已经进入视口、
 * 但动画迟迟没完成时才兜底，保证「滚到了却看不见」这种失效不会发生。
 */
export function Reveal({
  children,
  className,
  delay = 0,
  y = 26,
  once = true,
}: {
  children: React.ReactNode
  className?: string
  delay?: number
  y?: number
  once?: boolean
}) {
  const reduce = useReducedMotion()
  const ref = React.useRef<HTMLDivElement>(null)
  const [inView, setInView] = React.useState(false)
  const [failed, setFailed] = React.useState(false)

  React.useEffect(() => {
    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setInView(true)
            if (once) io.disconnect()
          } else if (!once) {
            setInView(false)
          }
        }
      },
      { rootMargin: '-72px' }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [once])

  // 已进入视口但 900ms 内仍未完成动画 → 判定动画失效，直接给终态
  React.useEffect(() => {
    if (!inView) return
    const id = window.setTimeout(() => setFailed(true), 900)
    return () => window.clearTimeout(id)
  }, [inView])

  const shouldShow = inView
  const instant = failed || reduce

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: instant ? 0 : y }}
      animate={
        shouldShow
          ? { opacity: 1, y: 0 }
          : { opacity: 0, y: instant ? 0 : y }
      }
      transition={
        shouldShow && !instant
          ? { duration: 0.6, delay, ease: EASE }
          : { duration: 0 }
      }
    >
      {children}
    </motion.div>
  )
}

/** 单个元素上浮淡入（页面级） */
export function FadeUp({
  children,
  className,
  delay = 0,
  y = 16,
  as = 'div',
}: {
  children: React.ReactNode
  className?: string
  delay?: number
  y?: number
  as?: 'div' | 'section' | 'header'
}) {
  const reduce = useReducedMotion()
  const Comp = motion[as] as typeof motion.div
  const instant = reduce

  return (
    <Comp
      className={className}
      initial={{ opacity: 0, y: instant ? 0 : y }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        instant ? { duration: 0.01 } : { duration: 0.5, delay, ease: EASE }
      }
    >
      {children}
    </Comp>
  )
}

/**
 * 磁性按钮容器：鼠标靠近时光标吸附，离开复位
 * 用 springs 做插值，幅度克制（不喧宾夺主）
 */
export function Magnetic({
  children,
  className,
  strength = 0.28,
}: {
  children: React.ReactNode
  className?: string
  strength?: number
}) {
  const reduce = useReducedMotion()
  const ref = React.useRef<HTMLDivElement>(null)
  const [pos, setPos] = React.useState({ x: 0, y: 0 })

  if (reduce) return <div className={className}>{children}</div>

  const onMove = (e: React.MouseEvent) => {
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = e.clientX - (rect.left + rect.width / 2)
    const y = e.clientY - (rect.top + rect.height / 2)
    setPos({ x: x * strength, y: y * strength })
  }

  return (
    <motion.div
      ref={ref}
      className={cn('inline-block', className)}
      onMouseMove={onMove}
      onMouseLeave={() => setPos({ x: 0, y: 0 })}
      animate={{ x: pos.x, y: pos.y }}
      transition={{ type: 'spring', stiffness: 260, damping: 20, mass: 0.5 }}
    >
      {children}
    </motion.div>
  )
}

/** 数字滚动动画 */
export function CountUp({
  value,
  className,
  decimals = 0,
  suffix = '',
}: {
  value: number
  className?: string
  decimals?: number
  suffix?: string
}) {
  const reduce = useReducedMotion()
  const [display, setDisplay] = React.useState(reduce ? value : 0)

  React.useEffect(() => {
    if (reduce) {
      setDisplay(value)
      return
    }
    let raf = 0
    const start = performance.now()
    const from = 0
    const duration = 700
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      setDisplay(from + (value - from) * eased)
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, reduce])

  return (
    <span className={cn('tabular', className)}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  )
}
