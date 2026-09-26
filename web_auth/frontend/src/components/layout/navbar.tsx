import { NavLink, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Activity,
  LayoutDashboard,
  LogOut,
  Moon,
  Sun,
  ShieldCheck,
  Waves,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/components/theme-provider'
import { useSession } from '@/components/session-provider'
import { session as sessionApi } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * 顶部玻璃导航栏
 * 心电波形作为品牌标识的动效元素
 */
export function Navbar() {
  const { theme, toggle } = useTheme()
  const { info, refresh } = useSession()
  const navigate = useNavigate()

  const onLogout = async () => {
    await sessionApi.logout()
    await refresh()
    navigate('/')
  }

  const linkCls = ({ isActive }: { isActive: boolean }) =>
    cn(
      'relative px-3.5 py-2 text-sm font-medium transition-colors duration-250 rounded-[var(--radius-sm)]',
      isActive
        ? 'text-[hsl(var(--foreground))]'
        : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
    )

  return (
    <header className="glass-bar sticky top-0 z-40">
      <nav className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
        {/* 品牌 */}
        <NavLink to="/" className="flex items-center gap-2.5 group">
          <span className="relative flex size-9 items-center justify-center rounded-[var(--radius-md)] bg-[hsl(var(--primary)/0.14)] ring-1 ring-[hsl(var(--primary)/0.3)]">
            <Waves className="size-4.5 text-[hsl(var(--primary))]" />
          </span>
          <span className="hidden text-[0.95rem] font-semibold tracking-tight sm:block">
            CardioCrypt
          </span>
        </NavLink>

        {/* 主导航 */}
        <div className="ml-4 hidden items-center gap-1 md:flex">
          <NavLink to="/" className={linkCls} end>
            首页
          </NavLink>
          {info.authenticated && (
            <NavLink to="/dashboard" className={linkCls}>
              仪表盘
            </NavLink>
          )}
          {info.isAdmin && (
            <NavLink to="/manage/dashboard" className={linkCls}>
              管理后台
            </NavLink>
          )}
        </div>

        <div className="flex-1" />

        {/* 主题切换 */}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label="切换主题"
          className="shrink-0"
        >
          <motion.span
            key={theme}
            initial={{ rotate: -90, opacity: 0, scale: 0.6 }}
            animate={{ rotate: 0, opacity: 1, scale: 1 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="flex items-center justify-center"
          >
            {theme === 'dark' ? (
              <Moon className="size-4" />
            ) : (
              <Sun className="size-4" />
            )}
          </motion.span>
        </Button>

        {/* 用户区 */}
        {info.authenticated ? (
          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-[hsl(var(--accent)/0.3)] bg-[hsl(var(--accent)/0.1)] px-3 py-1 text-xs font-medium text-[hsl(var(--accent))] sm:flex">
              <ShieldCheck className="size-3.5" />
              {info.username}
            </span>
            <Button variant="ghost" size="sm" onClick={onLogout}>
              <LogOut className="size-4" />
              <span className="hidden sm:inline">退出</span>
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <NavLink to="/register">注册</NavLink>
            </Button>
            <Button variant="brand" size="sm" asChild>
              <NavLink to="/login">
                <Activity className="size-4" />
                身份认证
              </NavLink>
            </Button>
          </div>
        )}
      </nav>
    </header>
  )
}

/** 页脚 */
export function Footer() {
  return (
    <footer className="relative z-10 border-t border-[hsl(var(--border)/0.6)] px-4 py-8 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 text-xs text-[hsl(var(--muted-foreground))] sm:flex-row">
        <p>© {new Date().getFullYear()} CardioCrypt</p>
        <p className="flex items-center gap-1.5">
          <LayoutDashboard className="size-3.5" />
          基于 ECG / PPG 生物特征的无密码认证
        </p>
      </div>
    </footer>
  )
}
