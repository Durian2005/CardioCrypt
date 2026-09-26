import * as React from 'react'
import * as LabelPrimitive from '@radix-ui/react-label'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * 表单控件基础样式。
 *
 * 这里刻意不使用 Tailwind 的 `pl-*` / `px-*` 工具类，而是用内联 style 写死
 * 水平内边距。原因是这些输入框的左侧留白**必须**精确等于图标的占位宽度，
 * 一旦被其它 padding 规则覆盖（Tailwind v4 下工具类优先级只由生成顺序决定，
 * 不由 className 书写顺序决定），图标就会和 placeholder 叠在一起。
 * 内联 style 优先级最高，可从结构上杜绝这一类覆盖问题。
 */
const CONTROL_BASE =
  'flex w-full rounded-[var(--radius-md)] border text-sm ' +
  'text-[hsl(var(--foreground))] transition-all duration-250 outline-none ' +
  'border-[hsl(var(--border))] bg-[hsl(var(--input)/0.35)] ' +
  'placeholder:text-[hsl(var(--muted-foreground)/0.75)] ' +
  'focus:border-[hsl(var(--primary)/0.7)] focus:bg-[hsl(var(--input)/0.5)] ' +
  'focus:shadow-[0_0_0_3px_hsl(var(--primary)/0.12)] ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

/** 图标尺寸 16px；图标左内边距 14px；文字左内边距 = 14 + 16 + 10 = 40px */
export const ICON_INSET = 14
export const ICON_SIZE = 16
export const ICON_TEXT_GAP = 10
export const ICON_PADDING_LEFT = ICON_INSET + ICON_SIZE + ICON_TEXT_GAP

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  /** 在左侧渲染一个图标，输入框左内边距自动预留，不会与文字重叠 */
  icon?: React.ReactNode
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, icon, style, ...props }, ref) => (
    <div className="relative w-full">
      {icon ? (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 z-10 flex -translate-y-1/2 items-center justify-center text-[hsl(var(--muted-foreground))]"
          style={{
            left: ICON_INSET,
            width: ICON_SIZE,
            height: ICON_SIZE,
          }}
        >
          {icon}
        </span>
      ) : null}
      <input
        ref={ref}
        type={type}
        className={cn(CONTROL_BASE, 'h-11 py-2', className)}
        style={{
          paddingLeft: icon ? ICON_PADDING_LEFT : 14,
          paddingRight: 14,
          ...style,
        }}
        {...props}
      />
    </div>
  )
)
Input.displayName = 'Input'

export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn(
      'text-sm font-medium text-[hsl(var(--foreground)/0.88)] leading-none',
      'peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
      className
    )}
    {...props}
  />
))
Label.displayName = 'Label'

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      'flex min-h-[80px] w-full rounded-[var(--radius-md)] border border-[hsl(var(--border))] ' +
        'bg-[hsl(var(--input)/0.35)] px-3.5 py-2.5 text-sm text-[hsl(var(--foreground))] outline-none ' +
        'placeholder:text-[hsl(var(--muted-foreground)/0.75)] transition-all duration-250 ' +
        'focus:border-[hsl(var(--primary)/0.7)] focus:shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]',
      className
    )}
    {...props}
  />
))
Textarea.displayName = 'Textarea'
