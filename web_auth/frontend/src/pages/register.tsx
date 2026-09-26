import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  CheckCircle2,
  Fingerprint,
  Loader2,
  User,
  Waves,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { FadeUp, StaggerGroup, StaggerItem } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'

/**
 * 注册页
 *
 * 后端 /register POST 语义：
 *  - 用户名已存在 → 重定向回 /register（flash 报错）
 *  - 成功 → 重定向到 /collect_data/<username>
 * 前端据最终 URL 判断走向。
 */
export default function RegisterPage() {
  const [username, setUsername] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = username.trim()

    if (!name) {
      toast.error('请输入用户名')
      return
    }
    if (name.length < 2) {
      toast.error('用户名至少 2 个字符')
      return
    }

    setSubmitting(true)
    try {
      const body = new URLSearchParams({ username: name })
      const res = await fetch('/register', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
        redirect: 'follow',
      })

      const finalUrl = new URL(res.url, window.location.origin)
      const path = finalUrl.pathname

      if (path.startsWith('/collect_data')) {
        toast.success('账号创建成功，开始采集生物特征')
        navigate(path)
      } else {
        toast.error('该用户名已存在，请更换一个')
      }
    } catch {
      toast.error('网络请求失败，请确认后端服务已启动')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-7xl items-center gap-12 px-4 py-12 sm:px-6 lg:grid-cols-2">
      {/* 左侧说明 */}
      <FadeUp className="hidden lg:block">
        <div className="max-w-md">
          <span className="flex size-12 items-center justify-center rounded-[var(--radius-lg)] bg-[hsl(var(--accent)/0.14)] ring-1 ring-[hsl(var(--accent)/0.3)]">
            <Fingerprint className="size-6 text-[hsl(var(--accent))]" />
          </span>
          <h1 className="mt-6 text-3xl font-semibold leading-snug tracking-tight">
            建立你的
            <br />
            心电身份基线
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
            注册过程会引导你连接设备并采集心电数据，
            系统据此训练一份只属于你的认证模型。
          </p>

          <div className="mt-10 space-y-3">
            {[
              { t: '创建账号', d: '仅需一个用户名' },
              { t: '连接设备', d: '蓝牙手环或串口设备' },
              { t: '采集数据', d: '安静状态下采集多组波形' },
              { t: '生成模型', d: '自动训练并保存特征模型' },
            ].map((s, i) => (
              <motion.div
                key={s.t}
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  delay: 0.25 + i * 0.08,
                  duration: 0.5,
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="flex items-center gap-3.5 rounded-[var(--radius-md)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--secondary)/0.35)] px-4 py-3"
              >
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--accent)/0.14)] font-mono text-[0.65rem] font-medium text-[hsl(var(--accent))]">
                  {i + 1}
                </span>
                <div>
                  <div className="text-sm font-medium">{s.t}</div>
                  <div className="text-xs text-[hsl(var(--muted-foreground))]">
                    {s.d}
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </FadeUp>

      {/* 右侧表单 */}
      <FadeUp delay={0.1} className="w-full">
        <Card className="mx-auto w-full max-w-md">
          <CardContent className="p-7 pt-7 sm:p-8 sm:pt-8">
            <StaggerGroup stagger={0.07}>
              <StaggerItem>
                <div className="mb-7 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-[hsl(var(--accent)/0.12)] ring-1 ring-[hsl(var(--accent)/0.28)]">
                    <Waves className="size-5 text-[hsl(var(--accent))]" />
                  </div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    创建账号
                  </h2>
                  <p className="mt-1.5 text-sm text-[hsl(var(--muted-foreground))]">
                    输入用户名，进入数据采集流程
                  </p>
                </div>
              </StaggerItem>

              <StaggerItem>
                <form onSubmit={onSubmit} className="space-y-5">
                  <div className="space-y-2">
                    <Label htmlFor="username">用户名</Label>
                    <Input
                      id="username"
                      name="username"
                      autoFocus
                      autoComplete="username"
                      placeholder="请输入用户名"
                      icon={<User className="size-4" />}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      disabled={submitting}
                    />
                    <p className="flex items-center gap-1.5 text-xs text-[hsl(var(--muted-foreground))]">
                      <CheckCircle2 className="size-3.5 text-[hsl(var(--accent))]" />
                      用户名将作为你的认证标识，创建后不可更改
                    </p>
                  </div>

                  <motion.div
                    whileHover={{ scale: submitting ? 1 : 1.02 }}
                    transition={{ duration: 0.2 }}
                  >
                    <Button
                      type="submit"
                      variant="brand"
                      size="lg"
                      className="w-full"
                      disabled={submitting}
                    >
                      {submitting ? (
                        <>
                          <Loader2 className="size-5 animate-spin" />
                          正在创建…
                        </>
                      ) : (
                        <>
                          创建并开始采集
                          <Fingerprint className="size-5" />
                        </>
                      )}
                    </Button>
                  </motion.div>

                  <Button
                    type="button"
                    variant="ghost"
                    className="w-full"
                    asChild
                  >
                    <Link to="/">
                      <ArrowLeft className="size-4" />
                      返回首页
                    </Link>
                  </Button>
                </form>
              </StaggerItem>

              <StaggerItem>
                <div className="mt-6 border-t border-[hsl(var(--border)/0.6)] pt-5 text-center text-sm text-[hsl(var(--muted-foreground))]">
                  已有账号？
                  <Link
                    to="/login"
                    className="ml-1 font-medium text-[hsl(var(--primary))] underline-offset-4 transition-colors hover:underline"
                  >
                    直接登录
                  </Link>
                </div>
              </StaggerItem>
            </StaggerGroup>
          </CardContent>
        </Card>
      </FadeUp>
    </div>
  )
}
