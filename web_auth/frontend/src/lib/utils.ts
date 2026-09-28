import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** 合并 className，后者覆盖前者的 Tailwind 冲突项 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 格式化时间戳为 HH:mm:ss */
export function formatTime(value: string | number | Date) {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '--:--:--'
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

/** 格式化日期为 YYYY-MM-DD HH:mm */
export function formatDateTime(value: string | number | Date) {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '--'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`
}

/** 数值夹取 */
export function clamp(v: number, min: number, max: number) {
  return Math.min(Math.max(v, min), max)
}
