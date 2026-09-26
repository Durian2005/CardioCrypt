import { cn } from '@/lib/utils'

/** 骨架屏：用扫光代替 spinner */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'shimmer rounded-[var(--radius-sm)] bg-[hsl(var(--secondary)/0.85)]',
        className
      )}
      {...props}
    />
  )
}

/** 卡片骨架组合 */
export function CardSkeleton() {
  return (
    <div className="glass rounded-[var(--radius-xl)] p-6">
      <Skeleton className="mb-4 h-4 w-24" />
      <Skeleton className="mb-3 h-9 w-32" />
      <Skeleton className="h-3 w-16" />
    </div>
  )
}
