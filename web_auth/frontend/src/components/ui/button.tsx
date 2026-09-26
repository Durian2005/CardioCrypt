import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-md)] text-sm font-medium ' +
    'transition-all duration-300 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] ' +
    'focus-visible:ring-offset-2 focus-visible:ring-offset-[hsl(var(--background))] ' +
    'disabled:pointer-events-none disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        // 主 CTA：实心强调色，hover 抬升 + 光晕
        default:
          'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))] shadow-[0_4px_16px_-4px_hsl(var(--accent)/0.5)] ' +
          'hover:bg-[hsl(var(--accent-600))] hover:scale-[1.02] hover:shadow-[0_10px_28px_-6px_hsl(var(--accent)/0.6)]',
        // 品牌蓝
        brand:
          'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] shadow-[0_4px_16px_-4px_hsl(var(--primary)/0.5)] ' +
          'hover:bg-[hsl(var(--primary)/0.88)] hover:scale-[1.02] hover:shadow-[0_10px_28px_-6px_hsl(var(--primary)/0.6)]',
        // 玻璃次要按钮
        secondary:
          'glass text-[hsl(var(--foreground))] hover:scale-[1.02] hover:border-[hsl(var(--glass-border))] ' +
          'hover:shadow-[0_14px_32px_-12px_rgb(0_0_0/0.6)]',
        outline:
          'border border-[hsl(var(--border))] bg-transparent text-[hsl(var(--foreground))] ' +
          'hover:border-[hsl(var(--primary)/0.6)] hover:bg-[hsl(var(--primary)/0.08)] hover:scale-[1.02]',
        ghost:
          'bg-transparent text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--secondary))] ' +
          'hover:text-[hsl(var(--foreground))]',
        destructive:
          'bg-[hsl(var(--destructive))] text-[hsl(var(--destructive-foreground))] ' +
          'hover:bg-[hsl(var(--destructive)/0.88)] hover:scale-[1.02] hover:shadow-[0_10px_28px_-8px_hsl(var(--destructive)/0.55)]',
        link: 'text-[hsl(var(--primary))] underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3 text-xs [&_svg]:size-3.5',
        default: 'h-10 px-4 [&_svg]:size-4',
        lg: 'h-12 px-6 text-base [&_svg]:size-5',
        icon: 'size-10 [&_svg]:size-4',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'

export { buttonVariants }
