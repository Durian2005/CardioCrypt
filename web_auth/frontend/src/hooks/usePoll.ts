import { useCallback, useEffect, useRef } from 'react'

/**
 * 定时轮询，并在卸载时保证清理。
 *
 * 抽出这个 hook 的原因：注册页与验证页各自手写 `pollRef` + `setInterval`
 * + cleanup，两份代码几乎逐字相同，且**都漏了同一件事** —— 总时长上限。
 * 「后端线程异常退出、状态永远停在推进中」时，界面会无限转圈，
 * 既不报错也没有重试入口。
 *
 * 两个刻意的设计：
 *
 * 1. **间隔与总时长上限是两个独立参数**。间隔控制刷新频率，上限控制
 *    「最多等多久就认输」。只设后者不设前者会让失败来得太慢，只设前者
 *    则是原来的 bug。
 * 2. **`onTick` 返回 `false` 表示终止**，不另设 `shouldStop` 标志 ——
 *    后者需要在 hook 外再存一份状态，容易与轮询本身不同步。
 *
 * @param onTick     每次轮询执行的函数；返回 `false` 立即停止轮询
 * @param intervalMs 轮询间隔（毫秒）
 * @param maxMs      轮询总时长上限（毫秒）；到点自动停止并调用 `onTimeout`
 * @param onTimeout  超时回调；不传则静默停止
 */
export function usePoll(options: {
  onTick: () => boolean | void | Promise<boolean | void>
  intervalMs: number
  maxMs: number
  onTimeout?: () => void
}) {
  const { onTick, intervalMs, maxMs, onTimeout } = options

  const timerRef = useRef<number | null>(null)
  const startedAtRef = useRef(0)

  // 回调每次渲染都是新的新函数，放进 ref 才能让下面的 effect 不必
  // 把回调列为依赖 —— 否则调用方内联箭头函数会让 interval 每渲染重建一次。
  const tickRef = useRef(onTick)
  tickRef.current = onTick
  const timeoutRef = useRef(onTimeout)
  timeoutRef.current = onTimeout

  const stop = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const start = useCallback(() => {
    stop()
    startedAtRef.current = Date.now()

    timerRef.current = window.setInterval(async () => {
      // 超时判定放在最前面：到点后即使这次请求能成功，也不再采纳结果，
      // 避免「刚拿到终态却因为超时被忽略」。
      if (Date.now() - startedAtRef.current > maxMs) {
        stop()
        timeoutRef.current?.()
        return
      }

      try {
        const keepGoing = await tickRef.current()
        if (keepGoing === false) stop()
      } catch {
        /* 轮询失败静默重试：单次网络抖动不该终止整个流程 */
      }
    }, intervalMs)
  }, [intervalMs, maxMs, stop])

  // 卸载时清理：用户在轮询期间离开页面，定时器仍会继续发请求
  useEffect(() => stop, [stop])

  return { start, stop }
}
