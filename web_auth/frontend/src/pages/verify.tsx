import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  CheckCircle2,
  Fingerprint,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { FadeUp } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'
import {
  DemoModeBanner,
  DemoSkipButton,
  DeviceListSkeleton,
  DeviceRow,
  DeviceTypeTabs,
  ScanButton,
} from '@/components/device'
import { useDeviceScan, deviceAddress } from '@/hooks/useDeviceScan'
import { usePoll } from '@/hooks/usePoll'
import { device, errorText, verification, type DeviceItem } from '@/lib/api'
import { useSession } from '@/components/session-provider'

type Phase = 'scan' | 'verifying' | 'success' | 'failed'

/** 轮询间隔 */
const POLL_INTERVAL_MS = 1500

/**
 * 轮询总时长上限。
 *
 * 后端状态若因线程异常退出而永远停在 `verifying`，界面会无限转圈 ——
 * 既不失败也不超时，用户没有重试入口。验证流程正常应在 1 分钟内出结论，
 * 给到 5 分钟足以覆盖慢速设备。
 */
const POLL_MAX_MS = 5 * 60 * 1000

export default function VerifyPage() {
  const navigate = useNavigate()
  const { info, refresh } = useSession()

  /** 后端开启演示模式时，本次采集可能改用合成数据 —— 必须显式告知用户 */
  const demoMode = info.demoMode === true

  const [phase, setPhase] = useState<Phase>('scan')
  const { deviceType, setDeviceType, scanning, devices, onScan, reset: resetScan } =
    useDeviceScan('未发现设备，请检查设备状态')
  const [activeName, setActiveName] = useState('')
  const [statusText, setStatusText] = useState('正在比对心电特征…')
  /** 本次判定是否基于合成信号（由后端在结果里带回来） */
  const [demoResult, setDemoResult] = useState(false)
  /** 判定未通过时的具体原因（未采集到数据 / 模型不可用 / 算法层不可用） */
  const [failReason, setFailReason] = useState<string | null>(null)

  /** 验证通过后延迟跳转的定时器：卸载时必须清掉，否则会在离开后仍跳转 */
  const redirectTimerRef = useRef<number | null>(null)

  const clearRedirectTimer = () => {
    if (redirectTimerRef.current) {
      window.clearTimeout(redirectTimerRef.current)
      redirectTimerRef.current = null
    }
  }

  useEffect(() => clearRedirectTimer, [])

  /* ---------- 轮询验证状态 ---------- */
  // 停止由 hook 负责：onTick 返回 false 即终止（见 usePoll 的约定），
  // 回调内部不必再手动清 interval —— 那属于重复，且容易在两处不同步。
  const poll = usePoll({
    intervalMs: POLL_INTERVAL_MS,
    maxMs: POLL_MAX_MS,
    onTick: async () => {
      const res = await verification.status()
      if (!res.success) return true

      if (res.status === 'completed') {
        setPhase('success')
        setDemoResult(res.demo === true)
        await refresh()
        toast.success('身份验证通过')
        clearRedirectTimer()
        redirectTimerRef.current = window.setTimeout(
          () => navigate('/dashboard'),
          1500
        )
        return false
      }
      if (res.status === 'failed') {
        setPhase('failed')
        setFailReason(res.reason ?? null)
        toast.error('身份验证未通过')
        return false
      }
      setStatusText('正在比对心电特征…')
      return true
    },
    onTimeout: () => {
      setPhase('failed')
      setFailReason('长时间未收到验证结果，请重试或查看后端日志')
      toast.error('验证流程超时')
    },
  })

  /* ---------- 选设备并开始验证 ---------- */
  const onPick = async (d: DeviceItem) => {
    const addr = deviceAddress(d)
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
    startVerify()
  }

  /* ---------- 触发验证 ---------- */
  const startVerify = useCallback(() => {
    void verification.start().catch(() => {
      /* 忽略启动阶段的网络抖动 */
    })
    poll.start()
  }, [poll])

  const retry = () => {
    clearRedirectTimer()
    setPhase('scan')
    resetScan()
    setActiveName('')
    setDemoResult(false)
    setFailReason(null)
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-14 sm:px-6">
      {/* 演示模式：在流程开始前就告知，避免把合成数据的结果当成真实比对 */}
      {demoMode && <DemoModeBanner variant="verify" />}

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
                    <DeviceTypeTabs value={deviceType} onChange={setDeviceType} />
                  </div>

                  <ScanButton scanning={scanning} onScan={onScan} />

                  {/* 演示模式专用入口：跳过设备扫描与连接，直接发起验证。
                      后端在演示模式下会以合成信号补足，且结果带 demo 标记。 */}
                  {demoMode && (
                    <DemoSkipButton
                      onClick={() => {
                        setActiveName('演示模式 · 合成信号')
                        setPhase('verifying')
                        startVerify()
                      }}
                    />
                  )}

                  {scanning && <DeviceListSkeleton />}

                  {!scanning && devices.length > 0 && (
                    <div className="mt-6 space-y-2.5">
                      {devices.map((d, i) => (
                        <DeviceRow
                          key={deviceAddress(d) || i}
                          device={d}
                          onConnect={() => onPick(d)}
                        />
                      ))}
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
