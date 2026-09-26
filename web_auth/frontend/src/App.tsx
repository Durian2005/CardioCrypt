import { useEffect } from 'react'
import { Toaster } from 'sonner'
import {
  BrowserRouter,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom'
import { AmbientBackground } from '@/components/layout/ambient-background'
import { Navbar, Footer } from '@/components/layout/navbar'
import { ThemeProvider } from '@/components/theme-provider'
import { SessionProvider } from '@/components/session-provider'
import { RequireAuth, RequireAdmin } from '@/components/route-guards'

import HomePage from '@/pages/home'
import LoginPage from '@/pages/login'
import RegisterPage from '@/pages/register'
import CollectDataPage from '@/pages/collect-data'
import VerifyPage from '@/pages/verify'
import DashboardPage from '@/pages/dashboard'
import AdminLoginPage from '@/pages/admin-login'
import AdminDashboardPage from '@/pages/admin-dashboard'
import NotFoundPage from '@/pages/not-found'

/** 路由切换时回到顶部 */
function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
  }, [pathname])
  return null
}

function Shell() {
  const { pathname } = useLocation()
  // 沉浸式页面：采集/验证流程隐藏页脚，减少干扰
  const immersive = pathname.startsWith('/collect_data') || pathname === '/verify'

  return (
    <div className="noise-overlay relative flex min-h-screen flex-col">
      <AmbientBackground />
      <div className="relative z-10 flex min-h-screen flex-col">
        <Navbar />
        <main className="flex-1">
          <ScrollToTop />
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/collect_data/:username" element={<CollectDataPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            <Route
              path="/dashboard"
              element={
                <RequireAuth>
                  <DashboardPage />
                </RequireAuth>
              }
            />
            <Route path="/manage/login" element={<AdminLoginPage />} />
            <Route
              path="/manage/dashboard"
              element={
                <RequireAdmin>
                  <AdminDashboardPage />
                </RequireAdmin>
              }
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>
        {!immersive && <Footer />}
      </div>

      <Toaster
        position="top-center"
        theme="dark"
        toastOptions={{
          style: {
            background: 'hsl(var(--glass-bg) / 0.92)',
            backdropFilter: 'blur(16px)',
            border: '1px solid hsl(var(--glass-border) / 0.6)',
            color: 'hsl(var(--foreground))',
          },
        }}
      />
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <SessionProvider>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </SessionProvider>
    </ThemeProvider>
  )
}
