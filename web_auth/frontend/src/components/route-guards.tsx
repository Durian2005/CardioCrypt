import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { Loader } from 'lucide-react'
import { useSession } from '@/components/session-provider'

/** 加载态：轻量骨架，避免闪烁 */
function GuardLoading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Loader className="size-5 animate-spin text-[hsl(var(--muted-foreground))]" />
    </div>
  )
}

/** 需要登录 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { info, loading, refresh } = useSession()
  const location = useLocation()

  // 进受保护路由时补一次会话刷新，避免旧标签页状态过期
  useEffect(() => {
    void refresh()
  }, [refresh])

  if (loading) return <GuardLoading />
  if (!info.authenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />
  }
  return <>{children}</>
}

/** 需要管理员 */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { info, loading, refresh } = useSession()

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (loading) return <GuardLoading />
  if (!info.isAdmin) return <Navigate to="/manage/login" replace />
  return <>{children}</>
}
