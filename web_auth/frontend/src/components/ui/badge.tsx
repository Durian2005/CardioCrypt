import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ' +
    'transition-colors duration-200 whitespace-nowrap',
  {
    variants: {
      variant: {
        default:
          'border-[hsl(var(--primary)/0.35)] bg-[hsl(var(--primary)/0.14)] text-[hsl(var(--primary))]',
        accent:
          'border-[hsl(var(--accent)/0.35)] bg-[hsl(var(--accent)/0.14)] text-[hsl(var(--accent))]',
        success:
          'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.14)] text-[hsl(var(--success))]',
        warning:
          'border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning))]',
        danger:
          'border-[hsl(var(--destructive)/0.38)] bg-[hsl(var(--destructive)/0.14)] text-[hsl(var(--destructive))]',
        muted:
          'border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.7)] text-[hsl(var(--muted-foreground))]',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}
