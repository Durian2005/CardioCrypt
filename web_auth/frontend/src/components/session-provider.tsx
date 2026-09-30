import * as React from 'react'
import { session as sessionApi, type SessionInfo } from '@/lib/api'

interface SessionCtx {
  info: SessionInfo
  loading: boolean
  refresh: () => Promise<void>
}

/** 未登录 / 请求失败时的默认投影。demoMode 保守取 false（不误报演示态）。 */
const DEFAULT_SESSION: SessionInfo = {
  authenticated: false,
  username: null,
  isAdmin: false,
  pendingLogin: null,
  demoMode: false,
}

const Ctx = React.createContext<SessionCtx>({
  info: DEFAULT_SESSION,
  loading: true,
  refresh: async () => {},
})

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = React.useState<SessionInfo>(DEFAULT_SESSION)
  const [loading, setLoading] = React.useState(true)

  const refresh = React.useCallback(async () => {
    try {
      const data = await sessionApi.info()
      setInfo(data)
    } catch {
      setInfo(DEFAULT_SESSION)
    } finally {
      setLoading(false)
    }
  }, [])

  React.useEffect(() => {
    void refresh()
  }, [refresh])

  const value = React.useMemo(
    () => ({ info, loading, refresh }),
    [info, loading, refresh]
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession() {
  return React.useContext(Ctx)
}
