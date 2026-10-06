import {
  AlertTriangle,
  Bluetooth,
  Cable,
  ChevronRight,
  Radio,
  RefreshCw,
  Search,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { FadeUp } from '@/components/motion'
import { cn } from '@/lib/utils'
import { DEVICE_TYPE_OPTIONS, deviceAddress, type DeviceType } from '@/hooks/useDeviceScan'
import type { DeviceItem } from '@/lib/api'

/** 设备类型分段控件（全部 / 蓝牙 / 串口） */
export function DeviceTypeTabs({
  value,
  onChange,
}: {
  value: DeviceType
  onChange: (v: DeviceType) => void
}) {
  return (
    <div className="flex gap-1.5 rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.5)] p-1">
      {DEVICE_TYPE_OPTIONS.map((o) => (
        <button
          key={o.k}
          type="button"
          onClick={() => onChange(o.k)}
          className={cn(
            'flex items-center gap-1.5 rounded-[var(--radius-sm)] px-3 py-1.5 text-xs font-medium transition-all duration-250',
            value === o.k
              ? 'bg-[hsl(var(--primary)/0.16)] text-[hsl(var(--primary))]'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          )}
        >
          {o.k === 'all' && <Radio size={12} />}
          {o.k === 'ble' && <Bluetooth className="size-3.5" />}
          {o.k === 'serial' && <Cable className="size-3.5" />}
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** 演示模式提示条 —— 措辞按「验证 / 注册」区分，样式与结构共用 */
export function DemoModeBanner({ variant }: { variant: 'verify' | 'register' }) {
  const isVerify = variant === 'verify'
  return (
    <FadeUp>
      <div
        role="alert"
        className="mb-8 flex items-start gap-3 rounded-[var(--radius-md)] border border-amber-500/45 bg-amber-500/10 p-4"
      >
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
        <div className="text-sm leading-relaxed">
          <p className="font-medium text-amber-500">演示模式已开启</p>
          <p className="mt-1 text-[hsl(var(--muted-foreground))]">
            {isVerify ? (
              <>
                采集不到真实设备信号时，系统会改用合成数据完成流程。此模式下的判定结果
                <span className="font-medium text-amber-500">
                  不代表真实生物特征比对
                </span>
                ，仅用于功能演示。
              </>
            ) : (
              <>
                采集不到真实设备信号时，系统会改用合成数据训练模型。以此注册的账户
                <span className="font-medium text-amber-500">
                  不具备真实生物特征依据
                </span>
                ，仅用于功能演示。
              </>
            )}
          </p>
        </div>
      </div>
    </FadeUp>
  )
}

/** 演示模式：跳过设备扫描与连接，直接进入采集/验证 */
export function DemoSkipButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      variant="outline"
      size="lg"
      className="mt-3 w-full border-amber-500/45 text-amber-500 hover:bg-amber-500/10 hover:text-amber-500"
      onClick={onClick}
    >
      <AlertTriangle className="size-5" />
      演示模式：跳过设备，使用合成数据
    </Button>
  )
}

/** 扫描按钮：扫描中显示旋转图标 */
export function ScanButton({
  scanning,
  onScan,
}: {
  scanning: boolean
  onScan: () => void
}) {
  return (
    <Button onClick={onScan} disabled={scanning} variant="brand" size="lg" className="w-full">
      {scanning ? (
        <>
          <RefreshCw className="size-5 animate-spin" />
          正在扫描…
        </>
      ) : (
        <>
          <Search className="size-5" />
          扫描设备
        </>
      )}
    </Button>
  )
}

/** 扫描进行中的骨架屏 */
export function DeviceListSkeleton({ rows = 2 }: { rows?: number }) {
  return (
    <div className="mt-6 space-y-2.5">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.5)] p-4"
        >
          <Skeleton className="size-9 rounded-[var(--radius-sm)]" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-36" />
            <Skeleton className="h-3 w-24" />
          </div>
        </div>
      ))}
    </div>
  )
}

/** 设备列表行（点击后连接该设备） */
export function DeviceRow({
  device,
  onConnect,
}: {
  device: DeviceItem
  onConnect: () => void
}) {
  const name = (device.name || device.device || '未知设备') as string
  const addr = deviceAddress(device) || '-'
  const type = (device.type || '-') as string
  const rssi = device.rssi as number | undefined

  return (
    <motion.button
      type="button"
      onClick={onConnect}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.01 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="flex w-full items-center gap-4 rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.35)] p-4 text-left transition-colors duration-250 hover:border-[hsl(var(--primary)/0.5)] hover:bg-[hsl(var(--secondary)/0.6)]"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[hsl(var(--primary)/0.12)]">
        {type === 'serial' ? (
          <Cable className="size-4 text-[hsl(var(--primary))]" />
        ) : (
          <Bluetooth className="size-4 text-[hsl(var(--primary))]" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{name}</div>
        <div className="truncate font-mono text-xs text-[hsl(var(--muted-foreground))]">
          {addr}
        </div>
      </div>
      {typeof rssi === 'number' && (
        <Badge variant="muted" className="tabular shrink-0">
          {rssi} dBm
        </Badge>
      )}
      <ChevronRight className="size-4 shrink-0 text-[hsl(var(--muted-foreground))]" />
    </motion.button>
  )
}
