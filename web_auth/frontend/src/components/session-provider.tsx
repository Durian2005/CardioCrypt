import * as React from 'react'
import { session as sessionApi, type SessionInfo } from '@/lib/api'

interface SessionCtx {
  info: SessionInfo
  loading: boolean
  refresh: () => Promise<void>
}

const Ctx = React.createContext<SessionCtx>({
  info: { authenticated: false, username: null, isAdmin: false, pendingLogin: null },
  loading: true,
  refresh: async () => {},
})

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [info, setInfo] = React.useState<SessionInfo>({
    authenticated: false,
    username: null,
    isAdmin: false,
    pendingLogin: null,
  })
  const [loading, setLoading] = React.useState(true)

  const refresh = React.useCallback(async () => {
    try {
      const data = await sessionApi.info()
      setInfo(data)
    } catch {
      setInfo({
        authenticated: false,
        username: null,
        isAdmin: false,
        pendingLogin: null,
      })
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
