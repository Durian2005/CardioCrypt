import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle,
  Cpu,
  LogOut,
  RefreshCw,
  Save,
  Search,
  Settings2,
  Sliders,
  Trash2,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input, Label } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FadeUp, StaggerGroup, StaggerItem } from '@/components/motion'
import { admin, session as sessionApi, type AdminUser } from '@/lib/api'
import { useSession } from '@/components/session-provider'
import { cn, formatDateTime } from '@/lib/utils'

type Tab = 'params' | 'users'

interface ParamField {
  key: string
  label: string
  hint: string
  step?: string
}

const PARAM_GROUPS: {
  title: string
  icon: LucideIcon
  desc: string
  fields: ParamField[]
}[] = [
  {
    title: '模型参数',
    icon: Cpu,
    desc: '控制认证模型的判定行为',
    fields: [
      { key: 'model_threshold', label: '预测阈值', hint: '0 – 1', step: '0.01' },
      { key: 'alpha', label: '融合系数 α (ECG)', hint: '0 – 1', step: '0.01' },
      { key: 'beta', label: '融合系数 β (PPG)', hint: '0 – 1', step: '0.01' },
    ],
  },
  {
    title: '验证参数',
    icon: Settings2,
    desc: '定义单次认证的尝试规则',
    fields: [
      { key: 'verification_time', label: '验证超时（秒）', hint: '建议 30' },
      {
        key: 'min_verification_success',
        label: '最少成功次数',
        hint: '低于该次数判定失败',
      },
      {
        key: 'total_verification_count',
        label: '总验证次数',
        hint: '单次认证的机会上限',
      },
    ],
  },
  {
    title: '设备参数',
    icon: Sliders,
    desc: '设备发现与连接的等待时间',
    fields: [
      {
        key: 'device_connection_timeout',
        label: '连接超时（秒）',
        hint: '握手最长等待',
        step: '0.5',
      },
      {
        key: 'device_scan_timeout',
        label: '扫描超时（秒）',
        hint: '设备发现窗口',
        step: '0.5',
      },
    ],
  },
  {
    title: '训练参数',
    icon: Settings2,
    desc: '影响模型训练耗时与精度',
    fields: [
      { key: 'training_epochs', label: '训练轮数', hint: '越大越慢、通常更准' },
      {
        key: 'training_learning_rate',
        label: '学习率',
        hint: '通常 0.001',
        step: '0.0001',
      },
      { key: 'training_batch_size', label: '批次大小', hint: '常见 16 / 32' },
    ],
  },
  {
    title: '系统参数',
    icon: Cpu,
    desc: '推理时的硬件与设备选择',
    fields: [
      { key: 'system_cuda_device', label: 'CUDA 设备号', hint: '0 表示第一块 GPU' },
    ],
  },
]

const DEFAULTS: Record<string, string> = {
  model_threshold: '0.8',
  alpha: '0.6',
  beta: '0.4',
  verification_time: '30',
  min_verification_success: '2',
  total_verification_count: '3',
  device_connection_timeout: '10',
  device_scan_timeout: '5',
  training_epochs: '50',
  training_learning_rate: '0.001',
  training_batch_size: '32',
  system_cuda_device: '0',
}

export default function AdminDashboardPage() {
  const [tab, setTab] = useState<Tab>('users')
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string[]>([])
  const [form, setForm] = useState<Record<string, string>>({ ...DEFAULTS })
  const [useCuda, setUseCuda] = useState(true)
  const [saving, setSaving] = useState(false)

  const navigate = useNavigate()
  const { refresh } = useSession()

  /* 加载数据 */
  const load = async () => {
    setLoading(true)
    try {
      const [u, c] = await Promise.allSettled([admin.users(), admin.config()])

      if (u.status === 'fulfilled' && u.value.success) {
        setUsers(u.value.users ?? [])
      }

      if (c.status === 'fulfilled' && c.value.success && c.value.config) {
        const cfg = c.value.config
        const next: Record<string, string> = { ...DEFAULTS }
        const map: Record<string, [string, string]> = {
          model_threshold: ['model', 'threshold'],
          alpha: ['model', 'alpha'],
          beta: ['model', 'beta'],
          verification_time: ['verification', 'time'],
          min_verification_success: ['verification', 'min_success'],
          total_verification_count: ['verification', 'total_count'],
          device_connection_timeout: ['device', 'connection_timeout'],
          device_scan_timeout: ['device', 'scan_timeout'],
          training_epochs: ['training', 'epochs'],
          training_learning_rate: ['training', 'learning_rate'],
          training_batch_size: ['training', 'batch_size'],
          system_cuda_device: ['system', 'cuda_device'],
        }
        Object.entries(map).forEach(([key, [sec, k]]) => {
          const v = cfg[sec]?.[k]
          if (v !== undefined && v !== null) next[key] = String(v)
        })
        setForm(next)
        setUseCuda(cfg.system?.use_cuda !== false)
      }
    } catch {
      toast.error('后台数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  /* 保存参数 */
  const onSave = async () => {
    setSaving(true)
    try {
      const payload: Record<string, string | number | boolean> = {
        section: 'model',
        system_use_cuda: useCuda ? 'true' : 'false',
        ...form,
      }
      const res = await admin.updateParams(payload)
      toast.success('系统参数已保存')
      void res
    } catch {
      toast.error('参数保存失败')
    } finally {
      setSaving(false)
    }
  }

  /* 删除 */
  const askDelete = (names: string[]) => {
    if (names.length === 0) return
    if (names.includes('admin')) {
      toast.error('管理员账号不可删除')
      return
    }
    setPendingDelete(names)
    setConfirmOpen(true)
  }

  const confirmDelete = async () => {
    try {
      if (pendingDelete.length === 1) {
        await admin.deleteUser(pendingDelete[0])
      } else {
        await admin.batchDelete(pendingDelete)
      }
      toast.success(`已删除 ${pendingDelete.length} 个用户`)
      setSelected([])
      setConfirmOpen(false)
      setPendingDelete([])
      await load()
    } catch {
      toast.error('删除失败')
    }
  }

  const onAdminLogout = async () => {
    await sessionApi.adminLogout()
    await refresh()
    navigate('/')
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return users
    return users.filter((u) => u.username.toLowerCase().includes(q))
  }, [users, query])

  const allChecked =
    filtered.length > 0 && filtered.every((u) => selected.includes(u.username))

  const toggleAll = () => {
    if (allChecked) {
      setSelected((s) => s.filter((n) => !filtered.some((u) => u.username === n)))
    } else {
      setSelected((s) => [
        ...new Set([...s, ...filtered.map((u) => u.username)]),
      ])
    }
  }

  const toggleOne = (name: string) => {
    setSelected((s) =>
      s.includes(name) ? s.filter((n) => n !== name) : [...s, name]
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      {/* 头部 */}
      <FadeUp>
        <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <Badge variant="warning" className="mb-3">
              <AlertTriangle className="size-3" />
              管理员模式
            </Badge>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              系统管理后台
            </h1>
            <p className="mt-2 text-sm text-[hsl(var(--muted-foreground))]">
              管理注册用户与运行时参数，操作将立即生效
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              onClick={load}
              disabled={loading}
            >
              <RefreshCw className={cn('size-4', loading && 'animate-spin')} />
              刷新
            </Button>
            <Button variant="ghost" onClick={onAdminLogout}>
              <LogOut className="size-4" />
              退出后台
            </Button>
          </div>
        </header>
      </FadeUp>

      {/* Tab 切换 */}
      <FadeUp delay={0.06}>
        <div className="mb-6 inline-flex gap-1.5 rounded-[var(--radius-md)] border border-[hsl(var(--border))] bg-[hsl(var(--secondary)/0.5)] p-1">
          {(
            [
              { k: 'users', label: '用户管理', icon: Users },
              { k: 'params', label: '参数配置', icon: Sliders },
            ] as const
          ).map((t) => (
            <button
              key={t.k}
              type="button"
              onClick={() => setTab(t.k)}
              className={cn(
                'relative flex items-center gap-2 rounded-[var(--radius-sm)] px-4 py-2 text-sm font-medium transition-colors duration-250',
                tab === t.k
                  ? 'text-[hsl(var(--foreground))]'
                  : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
              )}
            >
              {tab === t.k && (
                <motion.span
                  layoutId="admin-tab"
                  className="absolute inset-0 rounded-[var(--radius-sm)] bg-[hsl(var(--primary)/0.14)] ring-1 ring-[hsl(var(--primary)/0.3)]"
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
              <t.icon className="relative size-4" />
              <span className="relative">{t.label}</span>
            </button>
          ))}
        </div>
      </FadeUp>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        >
          {/* ===== 用户管理 ===== */}
          {tab === 'users' && (
            <Card>
              <CardContent className="p-6 pt-6">
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                  <div className="w-full max-w-xs">
                    <Input
                      placeholder="搜索用户名…"
                      icon={<Search className="size-4" />}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <Badge variant="muted">
                      共 {filtered.length} 位用户
                    </Badge>
                    {selected.length > 0 && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => askDelete(selected)}
                      >
                        <Trash2 className="size-3.5" />
                        删除选中（{selected.length}）
                      </Button>
                    )}
                  </div>
                </div>

                {loading ? (
                  <div className="space-y-2.5">
                    {[0, 1, 2, 3, 4].map((i) => (
                      <Skeleton key={i} className="h-14 w-full" />
                    ))}
                  </div>
                ) : filtered.length === 0 ? (
                  <EmptyState
                    title="暂无用户"
                    desc={query ? '没有匹配的用户名' : '还没有用户完成注册'}
                  />
                ) : (
                  <div className="overflow-hidden rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)]">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.5)]">
                          <th className="w-12 px-4 py-3">
                            <input
                              type="checkbox"
                              checked={allChecked}
                              onChange={toggleAll}
                              className="size-4 cursor-pointer accent-[hsl(var(--accent))]"
                              aria-label="全选"
                            />
                          </th>
                          <th className="px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))]">
                            用户名
                          </th>
                          <th className="hidden px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))] md:table-cell">
                            注册时间
                          </th>
                          <th className="hidden px-4 py-3 text-left font-medium text-[hsl(var(--muted-foreground))] lg:table-cell">
                            模型状态
                          </th>
                          <th className="w-20 px-4 py-3 text-right font-medium text-[hsl(var(--muted-foreground))]">
                            操作
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((u, i) => (
                          <motion.tr
                            key={u.username}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: i * 0.03, duration: 0.3 }}
                            className="border-b border-[hsl(var(--border)/0.4)] transition-colors duration-200 last:border-0 hover:bg-[hsl(var(--secondary)/0.45)]"
                          >
                            <td className="px-4 py-3.5">
                              <input
                                type="checkbox"
                                checked={selected.includes(u.username)}
                                onChange={() => toggleOne(u.username)}
                                className="size-4 cursor-pointer accent-[hsl(var(--accent))]"
                                aria-label={`选择 ${u.username}`}
                              />
                            </td>
                            <td className="px-4 py-3.5 font-medium">
                              {u.username}
                            </td>
                            <td className="tabular hidden px-4 py-3.5 text-[hsl(var(--muted-foreground))] md:table-cell">
                              {u.created_at
                                ? formatDateTime(u.created_at)
                                : '—'}
                            </td>
                            <td className="hidden lg:table-cell">
                              {u.model_path ? (
                                <Badge variant="success">已训练</Badge>
                              ) : (
                                <Badge variant="muted">未训练</Badge>
                              )}
                            </td>
                            <td className="px-4 py-3.5 text-right">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => askDelete([u.username])}
                                className="text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.12)]"
                              >
                                <Trash2 className="size-3.5" />
                              </Button>
                            </td>
                          </motion.tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* ===== 参数配置 ===== */}
          {tab === 'params' && (
            <div className="space-y-5">
              <StaggerGroup className="grid gap-5 lg:grid-cols-2" stagger={0.07}>
                {PARAM_GROUPS.map((g) => (
                  <StaggerItem key={g.title}>
                    <Card className="h-full">
                      <CardContent className="p-6 pt-6">
                        <div className="mb-5 flex items-center gap-3">
                          <span className="flex size-9 items-center justify-center rounded-[var(--radius-sm)] bg-[hsl(var(--primary)/0.12)]">
                            <g.icon className="size-4.5 text-[hsl(var(--primary))]" />
                          </span>
                          <div>
                            <h2 className="text-sm font-semibold">{g.title}</h2>
                            <p className="text-xs text-[hsl(var(--muted-foreground))]">
                              {g.desc}
                            </p>
                          </div>
                        </div>

                        <div className="space-y-4">
                          {g.fields.map((f) => (
                            <div key={f.key} className="space-y-2">
                              <div className="flex items-baseline justify-between">
                                <Label htmlFor={f.key}>{f.label}</Label>
                                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                                  {f.hint}
                                </span>
                              </div>
                              <Input
                                id={f.key}
                                type="number"
                                step={f.step ?? '1'}
                                value={form[f.key] ?? ''}
                                onChange={(e) =>
                                  setForm((s) => ({
                                    ...s,
                                    [f.key]: e.target.value,
                                  }))
                                }
                                className="tabular"
                              />
                            </div>
                          ))}
                        </div>
                      </CardContent>
                    </Card>
                  </StaggerItem>
                ))}

                {/* CUDA 开关 */}
                <StaggerItem>
                  <Card className="h-full">
                    <CardContent className="flex h-full flex-col p-6 pt-6">
                      <div className="mb-5 flex items-center gap-3">
                        <span className="flex size-9 items-center justify-center rounded-[var(--radius-sm)] bg-[hsl(var(--accent)/0.12)]">
                          <Cpu className="size-4.5 text-[hsl(var(--accent))]" />
                        </span>
                        <div>
                          <h2 className="text-sm font-semibold">GPU 加速</h2>
                          <p className="text-xs text-[hsl(var(--muted-foreground))]">
                            推理与训练时是否使用 CUDA
                          </p>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => setUseCuda((v) => !v)}
                        className="flex items-center justify-between rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.35)] px-4 py-3.5 transition-colors duration-250 hover:border-[hsl(var(--primary)/0.4)]"
                      >
                        <span className="text-sm">启用 CUDA 加速</span>
                        <span
                          className={cn(
                            'relative h-6 w-11 rounded-full transition-colors duration-300',
                            useCuda
                              ? 'bg-[hsl(var(--accent))]'
                              : 'bg-[hsl(var(--secondary))]'
                          )}
                        >
                          <motion.span
                            layout
                            transition={{
                              type: 'spring',
                              stiffness: 500,
                              damping: 32,
                            }}
                            className={cn(
                              'absolute top-0.5 size-5 rounded-full bg-white shadow-sm',
                              useCuda ? 'left-[1.4rem]' : 'left-0.5'
                            )}
                          />
                        </span>
                      </button>

                      <div className="mt-auto pt-6">
                        <Button
                          variant="brand"
                          size="lg"
                          className="w-full"
                          onClick={onSave}
                          disabled={saving}
                        >
                          {saving ? (
                            <RefreshCw className="size-4 animate-spin" />
                          ) : (
                            <Save className="size-4" />
                          )}
                          保存全部参数
                        </Button>
                        <p className="mt-3 text-center text-xs text-[hsl(var(--muted-foreground))]">
                          保存后立即生效，无需重启服务
                        </p>
                      </div>
                    </CardContent>
                  </Card>
                </StaggerItem>
              </StaggerGroup>
            </div>
          )}
        </motion.div>
      </AnimatePresence>

      {/* 删除确认 */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-full bg-[hsl(var(--destructive)/0.14)]">
                <AlertTriangle className="size-4 text-[hsl(var(--destructive))]" />
              </span>
              确认删除用户
            </DialogTitle>
            <DialogDescription>
              即将删除 {pendingDelete.length} 个用户及其模型文件与认证历史。
              该操作不可撤销。
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-40 overflow-y-auto rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.35)] p-3">
            <ul className="space-y-1 text-sm">
              {pendingDelete.map((n) => (
                <li key={n} className="flex items-center gap-2">
                  <span className="size-1.5 rounded-full bg-[hsl(var(--destructive))]" />
                  {n}
                </li>
              ))}
            </ul>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)}>
              取消
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              <Trash2 className="size-4" />
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function EmptyState({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius-md)] border border-dashed border-[hsl(var(--border))] py-14 text-center">
      <span className="mb-3 flex size-11 items-center justify-center rounded-full bg-[hsl(var(--secondary)/0.8)]">
        <Users className="size-5 text-[hsl(var(--muted-foreground))]" />
      </span>
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">{desc}</p>
    </div>
  )
}
