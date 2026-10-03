import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Bluetooth,
  Cable,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Plug,
  Radio,
  RefreshCw,
  Search,
  Waves,
  XCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { FadeUp } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'
import { device, registration, type DeviceItem } from '@/lib/api'
import { useSession } from '@/components/session-provider'
import { cn } from '@/lib/utils'

/* ---------------- 步骤定义 ---------------- */

const STEPS = [
  { key: 'scan', label: '扫描设备', icon: Search },
  { key: 'connect', label: '连接设备', icon: Plug },
  { key: 'collect', label: '数据采集', icon: Waves },
  { key: 'done', label: '完成注册', icon: CheckCircle2 },
] as const

type StepKey = (typeof STEPS)[number]['key']

/* ---------------- 轮询约定 ---------------- */

/**
 * 后端注册流程中「仍在推进」的状态；**不在**这里的一律视为已终止。
 *
 * 刻意用白名单，而不是逐个罗列失败态（failed / error / device_error）：后端每新增
 * 一个终态，黑名单写法都会静默漏掉它 —— 表现为界面永远停在「正在采集」，既不
 * 出结果也不报错。白名单天然免疫这种情况。
 * 空串是为「响应里没有 status 字段」留的，此时继续轮询。
 */
const ACTIVE_REGISTRATION_STATES = new Set([
  'collecting',
  'training',
  'verifying',
  'pending',
  '',
])

/** 轮询总时长上限：采集约 1 分钟 + 训练数分钟，超出说明后端线程已异常。 */
const POLL_TIMEOUT_MS = 15 * 60 * 1000

/* ---------------- 页面 ---------------- */

export default function CollectDataPage() {
  const { username = '' } = useParams()
  const navigate = useNavigate()
  const { info } = useSession()

  /** 后端开启演示模式时，采集可能改用合成数据 —— 必须显式告知用户 */
  const demoMode = info.demoMode === true

  const [step, setStep] = useState<StepKey>('scan')
  const [deviceType, setDeviceType] = useState<'all' | 'ble' | 'serial'>('all')
  const [scanning, setScanning] = useState(false)
  const [devices, setDevices] = useState<DeviceItem[]>([])
  const [connected, setConnected] = useState<DeviceItem | null>(null)

  const [collecting, setCollecting] = useState(false)
  const [progress, setProgress] = useState(0)
  const [collectStatus, setCollectStatus] = useState('准备开始数据采集…')
  const [finished, setFinished] = useState(false)
  /** 本次注册是否基于合成数据（由后端在结果里带回来） */
  const [demoResult, setDemoResult] = useState(false)

  const pollRef = useRef<number | null>(null)

  /* ---------- 扫描设备 ---------- */
  const onScan = async () => {
    setScanning(true)
    setDevices([])
    try {
      const res = await device.scan(deviceType)
      if (res.success) {
        const list = res.devices ?? []
        setDevices(list)
        if (list.length === 0) {
          toast.info('未发现可用设备，请确认设备已开启并处于配对模式')
        } else {
          toast.success(`发现 ${list.length} 个设备`)
        }
      } else {
        toast.error(res.error || '设备扫描失败')
      }
    } catch {
      toast.error('扫描请求失败，请确认后端服务可用')
    } finally {
      setScanning(false)
    }
  }

  /* ---------- 连接设备 ---------- */
  const onConnect = async (d: DeviceItem) => {
    const addr = (d.address || d.device || d.port || '') as string
    if (!addr) {
      toast.error('该设备缺少地址信息，无法连接')
      return
    }
    setStep('connect')
    const t = toast.loading(`正在连接 ${d.name || addr}…`)
    try {
      const res = await device.connect({
        address: addr,
        type: d.type || (deviceType === 'serial' ? 'serial' : 'ble'),
      })
      if (res.success) {
        toast.success(res.message || '设备连接成功', { id: t })
        setConnected(d)
        setTimeout(() => {
          setStep('collect')
          void startCollect()
        }, 700)
      } else {
        toast.error(res.error || '设备连接失败', { id: t })
        setStep('scan')
      }
    } catch {
      toast.error('连接请求失败', { id: t })
      setStep('scan')
    }
  }

  /* ---------- 开始采集 ---------- */
  const startCollect = useCallback(async () => {
    setCollecting(true)
    setProgress(6)
    setCollectStatus('正在采集心电信号，请保持安静…')

    try {
      const res = await registration.start({
        username,
        device_type: deviceType === 'serial' ? 'serial' : 'ble',
      })

      if (!res.success) {
        toast.error(res.error || '数据采集失败')
        setCollectStatus(res.error || '采集失败')
        setCollecting(false)
        return
      }

      if (res.model_trained) {
        setProgress(100)
        setCollectStatus('模型训练完成')
        toast.success('数据采集与模型训练已完成')
        setStep('done')
        setFinished(true)
      } else {
        setProgress(72)
        setCollectStatus('数据处理中…')
        pollStatus()
      }
    } catch {
      toast.error('采集请求异常')
      setCollecting(false)
      setCollectStatus('采集异常，请重试')
    }
  }, [username, deviceType])

  /* ---------- 轮询注册状态 ---------- */
  const pollStatus = useCallback(() => {
    if (pollRef.current) window.clearInterval(pollRef.current)

    const startedAt = Date.now()
    const stopPolling = () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }

    pollRef.current = window.setInterval(async () => {
      try {
        const res = await registration.status(username)
        if (!res.success) return

        const s = res.status as unknown as Record<string, unknown>
        const state = String(s.status ?? '')
        const count = Number(s.verification_count ?? 0)
        const total = Number(s.total_count ?? 3)

        if (state === 'completed') {
          setProgress(100)
          setCollectStatus('模型训练完成')
          setDemoResult(s.demo === true)
          setStep('done')
          setFinished(true)
          setCollecting(false)
          stopPolling()
          toast.success('注册流程完成，可以开始使用了')
        } else if (!ACTIVE_REGISTRATION_STATES.has(state)) {
          // 任何「不在推进中」的状态都在此终止：failed / error / device_error，
          // 以及后端将来新增的终态。后端会为失败写明原因（未采到数据 / 算法层不可用 /
          // 设备连接断开等），有就照实显示，没有才退回通用文案。
          const reason = String(s.error_message ?? '')
          setCollectStatus(reason || '采集或训练失败，请重试')
          setCollecting(false)
          stopPolling()
          toast.error(reason || '采集流程失败')
        } else if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
          // 状态一直停在推进中、但早已超出合理时长：多半是后端采集/训练线程异常退出
          // 而没来得及写终态。主动结束，避免无限轮询。
          setCollectStatus('长时间未收到最终结果，已停止等待 —— 请重试，或查看后端日志确认算法层状态')
          setCollecting(false)
          stopPolling()
          toast.error('采集流程超时')
        } else {
          setProgress((p) => Math.min(96, p + 4))
          setCollectStatus(
            count > 0
              ? `已完成 ${count}/${total} 组数据校验…`
              : '正在采集并校验数据…'
          )
        }
      } catch {
        /* 轮询失败静默重试 */
      }
    }, 1500)
  }, [username])

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [])

  useEffect(() => {
    toast.info(`已为「${username}」创建注册会话`, { duration: 3200 })
  }, [username])

  /* ---------- 渲染 ---------- */
  const activeIndex = STEPS.findIndex((s) => s.key === step)

  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6">
      {/* 演示模式：注册同样会降级为合成数据，须在流程开始前就说明 */}
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
                采集不到真实设备信号时，系统会改用合成数据训练模型。以此注册的账户
                <span className="font-medium text-amber-500">
                  不具备真实生物特征依据
                </span>
                ，仅用于功能演示。
              </p>
            </div>
          </div>
        </FadeUp>
      )}

      <FadeUp>
        <header className="mb-10 text-center">
          <Badge variant="accent" className="mb-4">
            数据采集流程
          </Badge>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            为「{username}」采集生物特征
          </h1>
          <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
            依次完成设备扫描、连接与数据采集，系统将自动训练你的专属认证模型。
          </p>
        </header>
      </FadeUp>

      {/* 步骤指示器 */}
      <FadeUp delay={0.08}>
        <StepIndicator activeIndex={activeIndex} />
      </FadeUp>

      {/* 步骤内容 */}
      <FadeUp delay={0.14} className="mt-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            {step === 'scan' && (
              <Card>
                <CardContent className="p-6 pt-6 sm:p-8 sm:pt-8">
                  <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold">第一步 · 扫描可用设备</h2>
                      <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                        请确保心电手环已开机并处于可被发现状态
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

                  {/* 演示模式专用入口：仅在后端开启该开关时出现。
                      后端此时已放行设备检查，直接进入采集即可由合成数据补足。 */}
                  {demoMode && (
                    <Button
                      variant="outline"
                      size="lg"
                      className="mt-3 w-full border-amber-500/45 text-amber-500 hover:bg-amber-500/10 hover:text-amber-500"
                      onClick={() => {
                        setStep('collect')
                        void startCollect()
                      }}
                    >
                      <AlertTriangle className="size-5" />
                      演示模式：跳过设备，使用合成数据
                    </Button>
                  )}

                  {/* 扫描中骨架屏 */}
                  {scanning && (
                    <div className="mt-6 space-y-2.5">
                      {[0, 1, 2].map((i) => (
                        <div
                          key={i}
                          className="flex items-center gap-4 rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.5)] p-4"
                        >
                          <Skeleton className="size-9 rounded-[var(--radius-sm)]" />
                          <div className="flex-1 space-y-2">
                            <Skeleton className="h-3.5 w-40" />
                            <Skeleton className="h-3 w-24" />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 设备列表 */}
                  {!scanning && devices.length > 0 && (
                    <div className="mt-6 space-y-2.5">
                      {devices.map((d, i) => (
                        <DeviceRow
                          key={(d.address as string) || i}
                          device={d}
                          onConnect={() => onConnect(d)}
                        />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}

            {step === 'connect' && (
              <Card>
                <CardContent className="flex flex-col items-center p-8 pt-8 text-center sm:p-12 sm:pt-12">
                  <div className="relative mb-6 flex size-16 items-center justify-center">
                    <span className="pulse-ring absolute inset-0" />
                    <span className="relative flex size-16 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.14)] ring-1 ring-[hsl(var(--primary)/0.3)]">
                      <Plug className="size-7 text-[hsl(var(--primary))]" />
                    </span>
                  </div>
                  <h2 className="text-base font-semibold">正在建立设备连接</h2>
                  <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
                    {connected?.name || '正在握手…'}
                  </p>
                  <div className="mt-8 w-full max-w xs:max-w-sm">
                    <div className="h-1.5 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
                      <motion.div
                        className="h-full rounded-full bg-[hsl(var(--primary))]"
                        initial={{ width: '8%' }}
                        animate={{ width: '88%' }}
                        transition={{ duration: 2.4, ease: 'easeInOut' }}
                      />
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {step === 'collect' && (
              <Card>
                <CardContent className="p-6 pt-6 sm:p-8 sm:pt-8">
                  <div className="mb-6">
                    <h2 className="text-base font-semibold">第三步 · 采集心电数据</h2>
                    <p className="mt-1 text-sm text-[hsl(var(--muted-foreground))]">
                      请保持安静并避免大幅动作，采集通常需要数十秒
                    </p>
                  </div>

                  {/* 波形区 */}
                  <div className="relative overflow-hidden rounded-[var(--radius-lg)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--surface-1)/0.6)] p-5">
                    <div className="mb-3 flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 font-medium text-[hsl(var(--muted-foreground))]">
                        <span className="relative flex size-1.5">
                          <span className="absolute inline-flex size-full animate-ping rounded-full bg-[hsl(var(--accent))] opacity-75" />
                          <span className="relative inline-flex size-1.5 rounded-full bg-[hsl(var(--accent))]" />
                        </span>
                        LIVE
                      </span>
                      <span className="tabular font-mono text-[hsl(var(--muted-foreground))]">
                        {progress}%
                      </span>
                    </div>
                    <EcgWave
                      className="h-28 w-full sm:h-36"
                      animated={collecting}
                    />
                  </div>

                  {/* 进度 */}
                  <div className="mt-6 space-y-3">
                    <div className="h-1.5 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
                      <motion.div
                        className="h-full rounded-full bg-gradient-to-r from-[hsl(var(--primary))] to-[hsl(var(--accent))]"
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.5, ease: 'easeOut' }}
                      />
                    </div>
                    <p className="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
                      <Cpu className="size-4 shrink-0 text-[hsl(var(--primary))]" />
                      {collectStatus}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}

            {step === 'done' && (
              <Card>
                <CardContent className="flex flex-col items-center p-8 pt-8 text-center sm:p-12 sm:pt-12">
                  <motion.div
                    initial={{ scale: 0.7, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ type: 'spring', stiffness: 220, damping: 18 }}
                    className="mb-6 flex size-16 items-center justify-center rounded-full bg-[hsl(var(--accent)/0.14)] ring-1 ring-[hsl(var(--accent)/0.35)]"
                  >
                    <CheckCircle2 className="size-8 text-[hsl(var(--accent))]" />
                  </motion.div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    注册完成
                  </h2>
                  <p className="mt-2 max-w-sm text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
                    已为「{username}」建立心电特征模型。
                    现在可以前往登录页，通过心跳完成身份认证。
                  </p>
                  {demoResult && (
                    <p className="mt-3 flex items-center gap-1.5 text-xs text-amber-500">
                      <AlertTriangle className="size-3.5" />
                      本次模型基于合成数据训练，不具备真实生物特征依据
                    </p>
                  )}
                  <div className="mt-8 flex flex-wrap justify-center gap-3">
                    <Button
                      variant="brand"
                      size="lg"
                      onClick={() => navigate('/login')}
                    >
                      前往登录
                      <ChevronRight className="size-4" />
                    </Button>
                    <Button
                      variant="secondary"
                      size="lg"
                      onClick={() => navigate('/')}
                    >
                      返回首页
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}
          </motion.div>
        </AnimatePresence>
      </FadeUp>

      {/* 采集失败重试 */}
      {finished === false && !collecting && step === 'collect' && (
        <div className="mt-6 text-center">
          <Button variant="outline" onClick={startCollect}>
            <RefreshCw className="size-4" />
            重新采集
          </Button>
        </div>
      )}
    </div>
  )
}

/* ---------------- 局部组件 ---------------- */

function StepIndicator({ activeIndex }: { activeIndex: number }) {
  return (
    <div className="relative">
      {/* 连接线 */}
      <div className="absolute left-0 right-0 top-5 -z-0 mx-auto hidden h-px bg-[hsl(var(--border))] sm:block">
        <motion.div
          className="h-full bg-[hsl(var(--primary))]"
          initial={{ width: 0 }}
          animate={{
            width: `${(activeIndex / (STEPS.length - 1)) * 100}%`,
          }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>

      <div className="relative grid grid-cols-2 gap-4 sm:grid-cols-4">
        {STEPS.map((s, i) => {
          const done = i < activeIndex
          const active = i === activeIndex
          return (
            <div key={s.key} className="flex flex-col items-center gap-2.5">
              <motion.span
                animate={{
                  scale: active ? 1.06 : 1,
                  borderColor: done
                    ? 'hsl(var(--accent) / 0.5)'
                    : active
                      ? 'hsl(var(--primary) / 0.6)'
                      : 'hsl(var(--border))',
                }}
                transition={{ duration: 0.35 }}
                className={cn(
                  'flex size-10 items-center justify-center rounded-full border bg-[hsl(var(--surface-1))]',
                  done && 'bg-[hsl(var(--accent)/0.12)]',
                  active && 'bg-[hsl(var(--primary)/0.14)]'
                )}
              >
                {done ? (
                  <CheckCircle2 className="size-4.5 text-[hsl(var(--accent))]" />
                ) : (
                  <s.icon
                    className={cn(
                      'size-4.5',
                      active
                        ? 'text-[hsl(var(--primary))]'
                        : 'text-[hsl(var(--muted-foreground))]'
                    )}
                  />
                )}
              </motion.span>
              <span
                className={cn(
                  'text-xs font-medium transition-colors duration-250',
                  active
                    ? 'text-[hsl(var(--foreground))]'
                    : 'text-[hsl(var(--muted-foreground))]'
                )}
              >
                {s.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DeviceRow({
  device,
  onConnect,
}: {
  device: DeviceItem
  onConnect: () => void
}) {
  const name = (device.name || device.device || '未知设备') as string
  const addr = (device.address || device.port || '-') as string
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
