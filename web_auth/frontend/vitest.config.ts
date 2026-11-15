import { defineConfig } from 'vitest/config'

/**
 * 前端单元测试配置
 *
 * 刻意与 `vite.config.ts` 分开：构建配置里带 Tailwind 插件与到 Flask 的开发代理，
 * 那些与测试无关；测试只要一个能跑 `fetch` 的 DOM 环境。
 *
 * 用 jsdom 而不是 node 环境，是因为 `src/lib/api.ts` 依赖 `window.setTimeout`
 * 与 `AbortController` —— 它本身就是浏览器侧的请求层。
 */
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // 用例之间共享模块级状态（api.ts 缓存了 CSRF 令牌），隔离必须靠
    // 每个用例自己 resetModules；这里不开全局注入，测试里显式 import。
    globals: false,
  },
})
