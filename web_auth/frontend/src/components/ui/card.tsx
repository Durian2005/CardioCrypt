import * as React from 'react'
import { cn } from '@/lib/utils'

/**
 * 玻璃拟态卡片
 * - glass：玻璃质感（默认）
 * - lift：hover 抬升微交互
 * - hairline：顶部高光描边
 */
export const Card = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & {
    glass?: boolean
    lift?: boolean
    hairline?: boolean
  }
>(({ className, glass = true, lift = true, hairline = true, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      'relative rounded-[var(--radius-xl)]',
      glass && 'glass',
      lift && 'lift',
      hairline && 'hairline-top',
      className
    )}
    {...props}
  />
))
Card.displayName = 'Card'

export const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn('p-6 pt-0', className)} {...props} />
))
CardContent.displayName = 'CardContent'
