import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { ArrowLeft, Loader2, Lock, ShieldCheck, User } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input, Label } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { FadeUp, Magnetic, StaggerGroup, StaggerItem } from '@/components/motion'
import { useSession } from '@/components/session-provider'

/**
 * 管理员登录
 *
 * 后端 /manage/login 语义：POST 成功后重定向到 /manage/dashboard。
 * 前端提交后依据最终 URL 判定，再刷新会话状态并跳转。
 */
export default function AdminLoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()
  const { refresh } = useSession()

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      toast.error('请填写账号与密码')
      return
    }

    setSubmitting(true)
    try {
      const body = new URLSearchParams({
        username: username.trim(),
        password,
      })
      const res = await fetch('/manage/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
        redirect: 'follow',
      })

      const finalUrl = new URL(res.url, window.location.origin)
      if (finalUrl.pathname.startsWith('/manage/dashboard')) {
        await refresh()
        toast.success('已进入管理后台')
        navigate('/manage/dashboard')
      } else {
        toast.error('账号或密码错误')
      }
    } catch {
      toast.error('网络请求失败，请确认后端服务已启动')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] items-center justify-center px-4 py-12 sm:px-6">
      <FadeUp className="w-full max-w-md">
        <Card>
          <CardContent className="p-7 pt-7 sm:p-8 sm:pt-8">
            <StaggerGroup stagger={0.07}>
              <StaggerItem>
                <div className="mb-7 text-center">
                  <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-[hsl(var(--primary)/0.12)] ring-1 ring-[hsl(var(--primary)/0.28)]">
                    <ShieldCheck className="size-5 text-[hsl(var(--primary))]" />
                  </div>
                  <Badge variant="muted" className="mb-3">
                    管理员入口
                  </Badge>
                  <h2 className="text-xl font-semibold tracking-tight">
                    系统管理后台
                  </h2>
                  <p className="mt-1.5 text-sm text-[hsl(var(--muted-foreground))]">
                    仅授权管理员可访问，请谨慎操作
                  </p>
                </div>
              </StaggerItem>

              <StaggerItem>
                <form onSubmit={onSubmit} className="space-y-5">
                  <div className="space-y-2">
                    <Label htmlFor="admin-username">管理员账号</Label>
                    <Input
                      id="admin-username"
                      autoFocus
                      autoComplete="username"
                      placeholder="请输入管理员账号"
                      icon={<User className="size-4" />}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      disabled={submitting}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="admin-password">密码</Label>
                    <Input
                      id="admin-password"
                      type="password"
                      autoComplete="current-password"
                      placeholder="请输入密码"
                      icon={<Lock className="size-4" />}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={submitting}
                    />
                  </div>

                  <Magnetic className="w-full">
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
                          正在验证…
                        </>
                      ) : (
                        <>
                          <ShieldCheck className="size-5" />
                          进入后台
                        </>
                      )}
                    </Button>
                  </Magnetic>
                </form>
              </StaggerItem>

              <StaggerItem>
                <div className="mt-6 border-t border-[hsl(var(--border)/0.6)] pt-5 text-center">
                  <Link
                    to="/"
                    className="inline-flex items-center gap-1.5 text-sm text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  >
                    <ArrowLeft className="size-4" />
                    返回首页
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
