import { motion } from 'framer-motion'

/**
 * 全局氛围层
 * - 极简网格背景
 * - 两处克制的极光光斑（呼吸式缓慢漂移）
 * - 全局噪点纹理（noise-overlay，由 index.css 提供）
 *
 * 设计原则：质感是"底噪"，不抢内容。光斑透明度很低，只在页边隐约可见。
 */
export function AmbientBackground() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 overflow-hidden"
      style={{ zIndex: 0 }}
    >
      {/* 网格 */}
      <div className="grid-bg absolute inset-0 opacity-[0.55]" />

      {/* 径向遮罩：让网格在边缘自然淡出 */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 90% 65% at 50% 0%, transparent 30%, hsl(var(--background)) 100%)',
        }}
      />

      {/* 极光光斑 · 左上（主色） */}
      <motion.div
        className="aurora"
        style={{
          width: '46rem',
          height: '46rem',
          top: '-18rem',
          left: '-14rem',
          background:
            'radial-gradient(circle, hsl(var(--primary) / 0.16), transparent 70%)',
        }}
        animate={{ x: [0, 42, 0], y: [0, 26, 0] }}
        transition={{ duration: 26, repeat: Infinity, ease: 'easeInOut' }}
      />

      {/* 极光光斑 · 右下（强调色） */}
      <motion.div
        className="aurora"
        style={{
          width: '38rem',
          height: '38rem',
          bottom: '-16rem',
          right: '-12rem',
          background:
            'radial-gradient(circle, hsl(var(--accent) / 0.11), transparent 70%)',
        }}
        animate={{ x: [0, -34, 0], y: [0, -22, 0] }}
        transition={{
          duration: 30,
          repeat: Infinity,
          ease: 'easeInOut',
          delay: 3,
        }}
      />
    </div>
  )
}
