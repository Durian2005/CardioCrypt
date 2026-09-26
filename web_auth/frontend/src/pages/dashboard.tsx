import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { toast } from 'sonner'
import {
  Activity,
  AlertTriangle,
  HeartPulse,
  RefreshCw,
  Server,
  ShieldCheck,
  Smile,
  Timer,
  Watch,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CardSkeleton, Skeleton } from '@/components/ui/skeleton'
import {
  CountUp,
  FadeUp,
  Reveal,
  StaggerGroup,
  StaggerItem,
} from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'
import { dashboard, type DashboardData } from '@/lib/api'
import { useSession } from '@/components/session-provider'
import { formatTime } from '@/lib/utils'

export default function DashboardPage() {
  const { info } = useSession()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [heartRate, setHeartRate] = useState<number | null>(null)
  const [clock, setClock] = useState(formatTime(new Date()))
  const [refreshing, setRefreshing] = useState(false)

  /* 时钟 */
  useEffect(() => {
    const id = window.setInterval(() => setClock(formatTime(new Date())), 1000)
    return () => window.clearInterval(id)
  }, [])

  /* 加载仪表盘数据 */
  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    try {
      const d = await dashboard.data()
      setData(d)
    } catch {
      if (!silent) toast.error('仪表盘数据加载失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  /* 模拟实时心率 */
  useEffect(() => {
    const tick = () => {
      setHeartRate(68 + Math.round(Math.sin(Date.now() / 4000) * 5 + Math.random() * 3))
    }
    tick()
    const id = window.setInterval(tick, 2200)
    return () => window.clearInterval(id)
  }, [])

  const s = data?.user_stats
  const sys = data?.system_stats
  const perf = data?.performance_data

  const metrics = [
    {
      icon: HeartPulse,
      label: '当前心率',
      value: heartRate ?? 0,
      suffix: ' BPM',
      hint: '实时监测中',
      tone: 'primary' as const,
    },
    {
      icon: Smile,
      label: '情绪状态',
      value: null,
      text: '平静',
      hint: '状态稳定',
      tone: 'accent' as const,
    },
    {
      icon: AlertTriangle,
      label: '预警等级',
      value: null,
      text: '正常',
      hint: '低风险',
      tone: 'success' as const,
    },
    {
      icon: Watch,
      label: '设备状态',
      value: null,
      text: '已连接',
      hint: 'ONLINE',
      tone: 'primary' as const,
      action: true,
    },
  ]

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      {/* 头部 */}
      <FadeUp>
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <Badge variant="accent" className="mb-3">
              <Activity className="size-3" />
              实时监测
            </Badge>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              系统仪表盘
            </h1>
            <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
              欢迎回来，
              <span className="font-medium text-[hsl(var(--foreground))]">
                {info.username ?? '用户'}
              </span>
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden text-right sm:block">
              <div className="text-xs text-[hsl(var(--muted-foreground))]">
                当前时间
              </div>
              <div className="tabular font-mono text-sm font-medium">{clock}</div>
            </div>
            <Button
              variant="secondary"
              onClick={() => load(true)}
              disabled={refreshing}
            >
              <RefreshCw
                className={`size-4 ${refreshing ? 'animate-spin' : ''}`}
              />
              刷新
            </Button>
          </div>
        </header>
      </FadeUp>

      {/* 指标卡 */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <StaggerGroup className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {metrics.map((m) => (
            <StaggerItem key={m.label}>
              <MetricCard {...m} />
            </StaggerItem>
          ))}
        </StaggerGroup>
      )}

      {/* 实时波形 */}
      <Reveal className="mt-6">
        <Card>
          <CardContent className="p-6 pt-6">
            <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span className="flex size-8 items-center justify-center rounded-[var(--radius-sm)] bg-[hsl(var(--primary)/0.12)]">
                  <Activity className="size-4 text-[hsl(var(--primary))]" />
                </span>
                <div>
                  <h2 className="text-sm font-semibold">实时生理信号监测</h2>
                  <p className="text-xs text-[hsl(var(--muted-foreground))]">
                    ECG · 100 Hz
                  </p>
                </div>
              </div>
              <Badge variant="success">
                <span className="relative flex size-1.5">
                  <span className="absolute inline-flex size-full animate-ping rounded-full bg-[hsl(var(--success))] opacity-75" />
                  <span className="relative inline-flex size-1.5 rounded-full bg-[hsl(var(--success))]" />
                </span>
                信号正常
              </Badge>
            </div>

            <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--surface-1)/0.6)] p-5">
              <EcgWave className="h-40 w-full sm:h-52" />
            </div>
          </CardContent>
        </Card>
      </Reveal>

      {/* 统计 + 事件 */}
      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        {/* 性能指标 */}
        <Reveal className="lg:col-span-1">
          <Card className="h-full">
            <CardContent className="p-6 pt-6">
              <h2 className="mb-5 text-sm font-semibold">系统性能</h2>
              {loading ? (
                <div className="space-y-4">
                  {[0, 1, 2].map((i) => (
                    <div key={i} className="space-y-2">
                      <Skeleton className="h-3 w-20" />
                      <Skeleton className="h-2 w-full" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-5">
                  <ProgressRow
                    label="认证成功率"
                    value={perf?.success_rate ?? 0}
                    tone="accent"
                  />
                  <ProgressRow
                    label="模型准确率"
                    value={perf?.accuracy_rate ?? 0}
                    tone="primary"
                  />
                  <div className="flex items-center justify-between border-t border-[hsl(var(--border)/0.6)] pt-4">
                    <span className="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
                      <Timer className="size-4" />
                      平均响应
                    </span>
                    <span className="tabular text-sm font-medium">
                      {perf?.response_time ?? 0} ms
                    </span>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </Reveal>

        {/* 系统状态 */}
        <Reveal delay={0.08} className="lg:col-span-1">
          <Card className="h-full">
            <CardContent className="p-6 pt-6">
              <h2 className="mb-5 text-sm font-semibold">运行状态</h2>
              {loading ? (
                <div className="space-y-3">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-11 w-full" />
                  ))}
                </div>
              ) : (
                <div className="space-y-2.5">
                  <StatusRow
                    icon={Server}
                    label="系统运行时长"
                    value={sys?.uptime ?? '--'}
                  />
                  <StatusRow
                    icon={Zap}
                    label="数据完整性"
                    value={`${sys?.data_integrity ?? 0}%`}
                  />
                  <StatusRow
                    icon={Activity}
                    label="累计认证"
                    value={`${s?.successful_auths ?? 0} 次`}
                  />
                  <StatusRow
                    icon={ShieldCheck}
                    label="失败拦截"
                    value={`${s?.failed_auths ?? 0} 次`}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        </Reveal>

        {/* 安全事件 */}
        <Reveal delay={0.16} className="lg:col-span-1">
          <Card className="h-full">
            <CardContent className="p-6 pt-6">
              <h2 className="mb-5 text-sm font-semibold">安全事件</h2>
              {loading ? (
                <div className="space-y-3">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <Skeleton key={i} className="h-9 w-full" />
                  ))}
                </div>
              ) : (
                <ul className="space-y-1.5">
                  {(data?.security_events ?? []).map((e, i) => (
                    <motion.li
                      key={`${e.time}-${i}`}
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.06, duration: 0.4 }}
                      className="flex items-center gap-3 rounded-[var(--radius-sm)] px-2 py-2 transition-colors duration-200 hover:bg-[hsl(var(--secondary)/0.5)]"
                    >
                      <span
                        className={`size-1.5 shrink-0 rounded-full ${
                          e.status === 'success'
                            ? 'bg-[hsl(var(--success))]'
                            : 'bg-[hsl(var(--warning))]'
                        }`}
                      />
                      <span className="flex-1 truncate text-sm">{e.event}</span>
                      <span className="tabular shrink-0 font-mono text-xs text-[hsl(var(--muted-foreground))]">
                        {e.time}
                      </span>
                    </motion.li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </Reveal>
      </div>
    </div>
  )
}

/* ---------------- 局部组件 ---------------- */

function MetricCard({
  icon: Icon,
  label,
  value,
  suffix,
  text,
  hint,
  tone,
  action,
}: {
  icon: LucideIcon
  label: string
  value: number | null
  suffix?: string
  text?: string
  hint: string
  tone: 'primary' | 'accent' | 'success'
  action?: boolean
}) {
  const toneCls = {
    primary: 'text-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.12)]',
    accent: 'text-[hsl(var(--accent))] bg-[hsl(var(--accent)/0.12)]',
    success: 'text-[hsl(var(--success))] bg-[hsl(var(--success)/0.12)]',
  }[tone]

  return (
    <Card className="h-full">
      <CardContent className="p-6 pt-6">
        <div className="mb-4 flex items-center justify-between">
          <span
            className={`flex size-9 items-center justify-center rounded-[var(--radius-sm)] ${toneCls}`}
          >
            <Icon className="size-4.5" />
          </span>
          <span className="text-xs text-[hsl(var(--muted-foreground))]">
            {label}
          </span>
        </div>

        <div className="text-2xl font-semibold tracking-tight">
          {value !== null ? (
            <>
              <CountUp value={value} />
              <span className="text-sm font-normal text-[hsl(var(--muted-foreground))]">
                {suffix}
              </span>
            </>
          ) : (
            <span className="tick-up">{text}</span>
          )}
        </div>

        <div className="mt-3 flex items-center gap-2 text-xs text-[hsl(var(--muted-foreground))]">
          <span className="size-1.5 rounded-full bg-[hsl(var(--accent))]" />
          {hint}
        </div>
      </CardContent>
    </Card>
  )
}

function ProgressRow({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: 'primary' | 'accent'
}) {
  const color =
    tone === 'primary' ? 'hsl(var(--primary))' : 'hsl(var(--accent))'
  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="text-[hsl(var(--muted-foreground))]">{label}</span>
        <span className="tabular font-medium">{value}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-[hsl(var(--secondary))]">
        <motion.div
          className="h-full rounded-full"
          style={{ background: color }}
          initial={{ width: 0 }}
          animate={{ width: `${value}%` }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
    </div>
  )
}

function StatusRow({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="flex items-center justify-between rounded-[var(--radius-sm)] border border-[hsl(var(--border)/0.5)] bg-[hsl(var(--secondary)/0.3)] px-3.5 py-2.5 transition-colors duration-250 hover:border-[hsl(var(--border))]">
      <span className="flex items-center gap-2.5 text-sm text-[hsl(var(--muted-foreground))]">
        <Icon className="size-4" />
        {label}
      </span>
      <span className="tabular text-sm font-medium">{value}</span>
    </div>
  )
}
