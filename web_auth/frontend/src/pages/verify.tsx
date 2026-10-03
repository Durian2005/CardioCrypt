import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Bluetooth,
  Cable,
  CheckCircle2,
  ChevronRight,
  Fingerprint,
  Loader2,
  Radio,
  RefreshCw,
  ScanFace,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { FadeUp } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'
import { device, errorText, verification, type DeviceItem } from '@/lib/api'
import { useSession } from '@/components/session-provider'
import { cn } from '@/lib/utils'

type Phase = 'scan' | 'verifying' | 'success' | 'failed'

export default function VerifyPage() {
  const navigate = useNavigate()
  const { info, refresh } = useSession()

  /** 后端开启演示模式时，本次采集可能改用合成数据 —— 必须显式告知用户 */
  const demoMode = info.demoMode === true

  const [phase, setPhase] = useState<Phase>('scan')
  const [deviceType, setDeviceType] = useState<'all' | 'ble' | 'serial'>('all')
  const [scanning, setScanning] = useState(false)
  const [devices, setDevices] = useState<DeviceItem[]>([])
  const [activeName, setActiveName] = useState('')
  const [statusText, setStatusText] = useState('正在比对心电特征…')
  /** 本次判定是否基于合成信号（由后端在结果里带回来） */
  const [demoResult, setDemoResult] = useState(false)
  /** 判定未通过时的具体原因（未采集到数据 / 模型不可用 / 算法层不可用） */
  const [failReason, setFailReason] = useState<string | null>(null)

  const pollRef = useRef<number | null>(null)

  const stopPoll = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => stopPoll, [])

  /* ---------- 扫描 ---------- */
  const onScan = async () => {
    setScanning(true)
    setDevices([])
    try {
      const res = await device.scan(deviceType)
      if (res.success) {
        const list = res.devices ?? []
        setDevices(list)
        if (list.length === 0) {
          toast.info('未发现设备，请检查设备状态')
        } else {
          toast.success(`发现 ${list.length} 个设备`)
        }
      } else {
        toast.error(res.error || '扫描失败')
      }
    } catch (err) {
      // 超时与「后端拒绝」要给不同的提示，所以照实显示封装里的原因
      toast.error(errorText(err, '扫描请求失败'))
    } finally {
      setScanning(false)
    }
  }

  /* ---------- 选设备并开始验证 ---------- */
  const onPick = async (d: DeviceItem) => {
    const addr = (d.address || d.device || d.port || '') as string
    if (!addr) {
      toast.error('该设备缺少地址信息')
      return
    }

    const t = toast.loading('正在连接设备…')
    try {
      const c = await device.connect({
        address: addr,
        type: d.type || (deviceType === 'serial' ? 'serial' : 'ble'),
      })
      if (!c.success) {
        toast.error(c.error || '设备连接失败', { id: t })
        return
      }
      setActiveName((d.name || addr) as string)
      toast.success('设备已连接，开始身份验证', { id: t })
    } catch (err) {
      toast.error(errorText(err, '连接请求失败'), { id: t })
      return
    }

    setPhase('verifying')
    startPoll()
  }

  /* ---------- 触发验证 ---------- */
  const startPoll = useCallback(() => {
    void verification.start().catch(() => {
      /* 忽略启动阶段的网络抖动 */
    })

    stopPoll()
    pollRef.current = window.setInterval(async () => {
      try {
        const res = await verification.status()
        if (!res.success) return

        if (res.status === 'completed') {
          stopPoll()
          setPhase('success')
          setDemoResult(res.demo === true)
          await refresh()
          toast.success('身份验证通过')
          setTimeout(() => navigate('/dashboard'), 1500)
        } else if (res.status === 'failed') {
          stopPoll()
          setPhase('failed')
          setFailReason(res.reason ?? null)
          toast.error('身份验证未通过')
        } else {
          setStatusText('正在比对心电特征…')
        }
      } catch {
        /* 轮询容错 */
      }
    }, 1500)
  }, [navigate, refresh])

  const retry = () => {
    setPhase('scan')
    setDevices([])
    setActiveName('')
    setDemoResult(false)
    setFailReason(null)
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      {/* 演示模式：在流程开始前就告知，避免把合成数据的结果当成真实比对 */}
      {demoMode && (
        <FadeUp>
          <div
            role="alert"
            className="mb-8 flex items-start gap-3 rounded-[var(--radius-md)] border border-amber-500/45 bg-amber-500/10 p-4"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <div className="text-sm leading-relaxed">
              <p className="font-medium text-amber-500">演示模式已开启</p>
              <p className="mt-1 text-[hsl(var(--muted-foreground))]">
                采集不到真实设备信号时，系统会改用合成数据完成流程。此模式下的判定结果
                <span className="font-medium text-amber-500">
                  不代表真实生物特征比对
                </span>
                ，仅用于功能演示。
              </p>
            </div>
          </div>
        </FadeUp>
      )}

      <FadeUp>
        <header className="mb-10 text-center">
          <Badge variant="default" className="mb-4">
            <ShieldCheck className="size-3" />
            身份验证
          </Badge>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            用心跳确认你的身份
          </h1>
          <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
            连接采集设备后，系统将读取实时心电信号并与你的模型比对。
          </p>
        </header>
      </FadeUp>

      <FadeUp delay={0.1}>
        <AnimatePresence mode="wait">
          <motion.div
            key={phase}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* ===== 扫描阶段 ===== */}
            {phase === 'scan' && (
              <Card>
                <CardContent className="p-6 pt-6 sm:p-8 sm:pt-8">
                  <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold">选择采集设备</h2>
                      <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                        选择你的心电手环或串口设备以开始验证
                      </p>
                    </div>
                    <div className="flex gap-1.5 rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.5)] p-1">
                      {(
                        [
                          { k: 'all', label: '全部', icon: Radio },
                          { k: 'ble', label: '蓝牙', icon: Bluetooth },
                          { k: 'serial', label: '串口', icon: Cable },
                        ] as const
                      ).map((o) => (
                        <button
                          key={o.k}
                          type="button"
                          onClick={() => setDeviceType(o.k)}
                          className={cn(
                            'flex items-center gap-1.5 rounded-[var(--radius-sm)] px-3 py-1.5 text-xs font-medium transition-all duration-250',
                            deviceType === o.k
                              ? 'bg-[hsl(var(--primary)/0.16)] text-[hsl(var(--primary))]'
                              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
                          )}
                        >
                          <o.icon className="size-3.5" />
                          {o.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <Button
                    onClick={onScan}
                    disabled={scanning}
                    variant="brand"
                    size="lg"
                    className="w-full"
                  >
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

                  {/* 演示模式专用入口：跳过设备扫描与连接，直接发起验证。
                      后端在演示模式下会以合成信号补足，且结果带 demo 标记。 */}
                  {demoMode && (
                    <Button
                      variant="outline"
                      size="lg"
                      className="mt-3 w-full border-amber-500/45 text-amber-500 hover:bg-amber-500/10 hover:text-amber-500"
                      onClick={() => {
                        setActiveName('演示模式 · 合成信号')
                        setPhase('verifying')
                        startPoll()
                      }}
                    >
                      <AlertTriangle className="size-5" />
                      演示模式：跳过设备，使用合成数据
                    </Button>
                  )}

                  {scanning && (
                    <div className="mt-6 space-y-2.5">
                      {[0, 1].map((i) => (
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
                  )}

                  {!scanning && devices.length > 0 && (
                    <div className="mt-6 space-y-2.5">
                      {devices.map((d, i) => {
                        const name = (d.name || d.device || '未知设备') as string
                        const addr = (d.address || d.port || '-') as string
                        const type = (d.type || '') as string
                        return (
                          <motion.button
                            key={addr + i}
                            type="button"
                            onClick={() => onPick(d)}
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            whileHover={{ scale: 1.01 }}
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
                              <div className="truncate text-sm font-medium">
                                {name}
                              </div>
                              <div className="truncate font-mono text-xs text-[hsl(var(--muted-foreground))]">
                                {addr}
                              </div>
                            </div>
                            <ChevronRight className="size-4 shrink-0 text-[hsl(var(--muted-foreground))]" />
                          </motion.button>
                        )
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {/* ===== 验证中 ===== */}
            {phase === 'verifying' && (
              <Card>
                <CardContent className="p-8 pt-8 text-center sm:p-12 sm:pt-12">
                  <div className="relative mx-auto mb-7 flex size-20 items-center justify-center">
                    <span className="pulse-ring absolute inset-0" />
                    <span className="relative flex size-20 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.14)] ring-1 ring-[hsl(var(--primary)/0.3)]">
                      <Fingerprint className="size-9 text-[hsl(var(--primary))]" />
                    </span>
                  </div>

                  <h2 className="text-lg font-semibold tracking-tight">
                    正在验证身份
                  </h2>
                  <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
                    {activeName} · {statusText}
                  </p>

                  <div className="mx-auto mt-8 max-w-sm overflow-hidden rounded-[var(--radius-lg)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--surface-1)/0.6)] p-4">
                    <EcgWave className="h-20 w-full" />
                  </div>

                  <div className="mx-auto mt-7 flex max-w-xs items-center gap-2.5 text-left">
                    {['读取实时信号', '提取特征向量', '与模型比对'].map((s, i) => (
                      <motion.div
                        key={s}
                        initial={{ opacity: 0.35 }}
                        animate={{ opacity: [0.35, 1, 0.35] }}
                        transition={{
                          duration: 2.2,
                          repeat: Infinity,
                          delay: i * 0.55,
                          ease: 'easeInOut',
                        }}
                        className="flex-1 text-center"
                      >
                        <div className="mx-auto mb-1.5 h-1 rounded-full bg-[hsl(var(--primary))]" />
                        <span className="text-[0.68rem] text-[hsl(var(--muted-foreground))]">
                          {s}
                        </span>
                      </motion.div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* ===== 成功 ===== */}
            {phase === 'success' && (
              <Card>
                <CardContent className="flex flex-col items-center p-8 pt-8 text-center sm:p-12 sm:pt-12">
                  <motion.div
                    initial={{ scale: 0.6, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', stiffness: 220, damping: 16 }}
                    className="mb-6 flex size-20 items-center justify-center rounded-full bg-[hsl(var(--accent)/0.14)] ring-1 ring-[hsl(var(--accent)/0.4)]"
                  >
                    <CheckCircle2 className="size-10 text-[hsl(var(--accent))]" />
                  </motion.div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    身份验证通过
                  </h2>
                  <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
                    {demoResult
                      ? '本次为演示模式：判定基于合成数据，非真实采集。'
                      : '心电特征匹配成功，正在进入仪表盘…'}
                  </p>
                  {demoResult && (
                    <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-500">
                      <AlertTriangle className="size-3.5" />
                      结果不代表真实生物特征比对
                    </p>
                  )}
                  <Loader2 className="mt-7 size-5 animate-spin text-[hsl(var(--muted-foreground))]" />
                </CardContent>
              </Card>
            )}

            {/* ===== 失败 ===== */}
            {phase === 'failed' && (
              <Card>
                <CardContent className="flex flex-col items-center p-8 pt-8 text-center sm:p-12 sm:pt-12">
                  <motion.div
                    initial={{ scale: 0.6, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', stiffness: 220, damping: 16 }}
                    className="mb-6 flex size-20 items-center justify-center rounded-full bg-[hsl(var(--destructive)/0.14)] ring-1 ring-[hsl(var(--destructive)/0.38)]"
                  >
                    <XCircle className="size-10 text-[hsl(var(--destructive))]" />
                  </motion.div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    验证未通过
                  </h2>
                  <p className="mt-2 max-w-sm text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
                    {failReason ??
                      '信号与注册模型不匹配。请确认佩戴位置正确、保持静止后重试。'}
                  </p>
                  <div className="mt-8 flex flex-wrap justify-center gap-3">
                    <Button variant="brand" size="lg" onClick={retry}>
                      <RefreshCw className="size-5" />
                      重新验证
                    </Button>
                    <Button
                      variant="secondary"
                      size="lg"
                      onClick={() => navigate('/login')}
                    >
                      返回登录
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </motion.div>
        </AnimatePresence>
      </FadeUp>
    </div>
  )
}
