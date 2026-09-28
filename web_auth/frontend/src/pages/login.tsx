import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { motion } from 'framer-motion'
import { Activity, ArrowLeft, Loader2, User, Waves } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { FadeUp, StaggerGroup, StaggerItem } from '@/components/motion'
import { EcgWave } from '@/components/visuals/ecg-wave'
import { postFormRaw } from '@/lib/api'

/**
 * 登录页
 *
 * 后端 /login 是「表单 + 重定向」语义：POST 成功后重定向到 /verify，
 * 失败则重定向回 /login 并 flash 一条消息。
 * 前端用 fetch 提交表单，读回最终 URL 判断走向。
 */
export default function LoginPage() {
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

    setSubmitting(true)
    try {
      // 走统一封装：自动附带 CSRF 令牌
      const res = await postFormRaw('/login', { username: name })

      const finalUrl = new URL(res.url, window.location.origin)
      const path = finalUrl.pathname

      if (path.startsWith('/verify')) {
        toast.success('身份信息已提交，开始采集验证')
        navigate('/verify')
      } else if (path.startsWith('/collect_data')) {
        // 该用户尚未采集数据，引导至采集流程
        toast.info('该用户尚未采集生物特征，请先完成数据采集')
        navigate(path)
      } else {
        // 停留在 /login 视为失败
        toast.error('未找到该用户，请检查用户名或先注册')
      }
    } catch {
      toast.error('网络请求失败，请确认后端服务已启动')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] max-w-7xl items-center gap-12 px-4 py-12 sm:px-6 lg:grid-cols-2">
      {/* 左侧：品牌陈述 */}
      <FadeUp className="hidden lg:block">
        <div className="max-w-md">
          <span className="flex size-12 items-center justify-center rounded-[var(--radius-lg)] bg-[hsl(var(--primary)/0.14)] ring-1 ring-[hsl(var(--primary)/0.3)]">
            <Waves className="size-6 text-[hsl(var(--primary))]" />
          </span>
          <h1 className="mt-6 text-3xl font-semibold leading-snug tracking-tight">
            用心跳证明
            <br />
            你是你
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-[hsl(var(--muted-foreground))]">
            输入用户名后，系统将连接采集设备读取你的心电特征，
            与注册时建立的模型进行比对。
          </p>

          <div className="mt-10 overflow-hidden rounded-[var(--radius-lg)] border border-[hsl(var(--border)/0.6)] bg-[hsl(var(--surface-1)/0.5)] p-4">
            <EcgWave className="h-24 w-full" />
          </div>

          <ul className="mt-8 space-y-2.5 text-sm text-[hsl(var(--muted-foreground))]">
            {['无需输入密码', '活体信号校验，无法远程伪造', '整个认证过程约 3 秒'].map(
              (t) => (
                <li key={t} className="flex items-center gap-2.5">
                  <span className="size-1.5 shrink-0 rounded-full bg-[hsl(var(--accent))]" />
                  {t}
                </li>
              )
            )}
          </ul>
        </div>
      </FadeUp>

      {/* 右侧：表单 */}
      <FadeUp delay={0.1} className="w-full">
        <Card className="mx-auto w-full max-w-md">
          <CardContent className="p-7 pt-7 sm:p-8 sm:pt-8">
            <StaggerGroup stagger={0.07}>
              <StaggerItem>
                <div className="mb-7 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.12)] ring-1 ring-[hsl(var(--primary)/0.28)]">
                    <Activity className="size-5 text-[hsl(var(--primary))]" />
                  </div>
                  <h2 className="text-xl font-semibold tracking-tight">
                    用户登录
                  </h2>
                  <p className="mt-1.5 text-sm text-[hsl(var(--muted-foreground))]">
                    输入用户名以开始身份认证
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
                          正在提交…
                        </>
                      ) : (
                        <>
                          开始身份认证
                          <Activity className="size-5" />
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
                  还没有账号？
                  <Link
                    to="/register"
                    className="ml-1 font-medium text-[hsl(var(--primary))] underline-offset-4 transition-colors hover:underline"
                  >
                    立即注册
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
