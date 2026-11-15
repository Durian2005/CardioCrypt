import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * `src/lib/api.ts` 的行为契约
 *
 * 只测请求层，不测界面。选择这一层的理由是它曾经真的坏过，而且坏法都是
 * "看起来成功"：
 *
 *  1. 只判断"能不能 JSON.parse"，于是 4xx/5xx 只要带个 JSON body 就被当成成功，
 *     调用方拿到一个没有业务字段的对象 —— 界面空白或一直转圈，而不是报错；
 *  2. 请求没有超时，后端卡住时前端无限等待；
 *  3. 写请求不带 CSRF 令牌，全站写操作 403。
 *
 * 每个用例都对应上面某一条的具体后果，改动这一层时它们应当先红。
 *
 * 关于模块状态：`api.ts` 在模块级缓存 CSRF 令牌，所以每个用例都
 * `resetModules()` 后重新 import，避免用例之间互相污染。
 */

type Call = { url: string; init: RequestInit }

function jsonResponse(
  body: unknown,
  status = 200,
  extra: Partial<Pick<Response, 'redirected' | 'url'>> = {}
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected: extra.redirected ?? false,
    url: extra.url ?? 'http://localhost/',
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response
}

function htmlResponse(
  status = 200,
  extra: Partial<Pick<Response, 'redirected' | 'url'>> = {}
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected: extra.redirected ?? false,
    url: extra.url ?? 'http://localhost/',
    text: async () => '<!doctype html><html><body>login</body></html>',
    json: async () => {
      throw new SyntaxError('Unexpected token <')
    },
  } as unknown as Response
}

/** 记录每次 fetch 调用，便于断言请求头与请求次数 */
function stubFetch(
  handler: (url: string, init: RequestInit, calls: Call[]) => Promise<Response>
): Call[] {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init })
      return handler(url, init, calls)
    })
  )
  return calls
}

/** 永不返回、只在 signal abort 时 reject —— 用来验证超时路径 */
function hangingFetch(_url: string, init: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => {
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    })
  })
}

let api: typeof import('./api')

beforeEach(async () => {
  vi.resetModules()
  api = await import('./api')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('响应判定', () => {
  it('正常响应返回解析后的 JSON', async () => {
    stubFetch(async () => jsonResponse({ success: true, users: [] }))

    await expect(api.apiGet('/api/admin/users')).resolves.toEqual({
      success: true,
      users: [],
    })
  })

  it('4xx 带 JSON body 时按失败处理，并采用服务端的文案', async () => {
    stubFetch(async () => jsonResponse({ error: '用户名已存在' }, 400))

    await expect(api.apiGet('/api/users/dup')).rejects.toMatchObject({
      kind: 'http',
      status: 400,
      message: '用户名已存在',
    })
  })

  it('4xx 没有可读文案时给出带状态码的兜底', async () => {
    stubFetch(async () => jsonResponse({}, 500))

    await expect(api.apiGet('/api/x')).rejects.toMatchObject({
      kind: 'http',
      status: 500,
      message: '请求失败（HTTP 500）',
    })
  })

  it('200 但正文不是 JSON 时判为 parse 错误', async () => {
    stubFetch(async () => htmlResponse(200))

    await expect(api.apiGet('/api/x')).rejects.toMatchObject({ kind: 'parse' })
  })

  it('被重定向到登录页时判为会话失效而不是解析失败', async () => {
    stubFetch(async () =>
      htmlResponse(200, { redirected: true, url: 'http://localhost:5000/login' })
    )

    await expect(api.apiGet('/api/dashboard_data')).rejects.toMatchObject({
      kind: 'session',
      message: '登录状态已失效，请重新登录',
    })
  })

  it('网络层失败判为 network', async () => {
    stubFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    await expect(api.apiGet('/api/x')).rejects.toMatchObject({ kind: 'network' })
  })

  it('超过读超时判为 timeout', async () => {
    vi.useFakeTimers()
    stubFetch(hangingFetch)

    const pending = api.apiGet('/api/slow')
    // 先让 request() 走到 await fetch，再把计时器推过 15 秒的读超时
    await Promise.resolve()
    vi.advanceTimersByTime(15_001)

    await expect(pending).rejects.toMatchObject({ kind: 'timeout' })
  })
})

describe('CSRF 令牌', () => {
  it('写请求先取令牌，并放进 X-CSRFToken 请求头', async () => {
    const calls = stubFetch(async (url) =>
      url === '/api/csrf-token' ? jsonResponse({ token: 'tok-1' }) : jsonResponse({ success: true })
    )

    await api.apiPost('/api/scan_devices', { device_type: 'ble' })

    expect(calls.map((c) => c.url)).toEqual(['/api/csrf-token', '/api/scan_devices'])
    const headers = calls[1].init.headers as Record<string, string>
    expect(headers['X-CSRFToken']).toBe('tok-1')
    expect(calls[1].init.body).toBe('{"device_type":"ble"}')
  })

  it('令牌被缓存：连续两次写请求只取一次', async () => {
    const calls = stubFetch(async (url) =>
      url === '/api/csrf-token' ? jsonResponse({ token: 'tok-1' }) : jsonResponse({ success: true })
    )

    await api.apiPost('/api/a')
    await api.apiPost('/api/b')

    expect(calls.filter((c) => c.url === '/api/csrf-token')).toHaveLength(1)
  })

  it('收到 403 时丢弃旧令牌并重试一次，重试用新令牌', async () => {
    let tokenSeq = 0
    const calls = stubFetch(async (url, _init, all) => {
      if (url === '/api/csrf-token') {
        tokenSeq += 1
        return jsonResponse({ token: `tok-${tokenSeq}` })
      }
      const business = all.filter((c) => c.url !== '/api/csrf-token').length
      return business === 1 ? jsonResponse({ error: 'csrf' }, 403) : jsonResponse({ success: true })
    })

    await expect(api.apiPost('/api/connect_device')).resolves.toEqual({ success: true })

    const businessCalls = calls.filter((c) => c.url === '/api/connect_device')
    expect(businessCalls).toHaveLength(2)
    const retryHeaders = businessCalls[1].init.headers as Record<string, string>
    expect(retryHeaders['X-CSRFToken']).toBe('tok-2')
  })

  it('resetCsrfToken 之后下一次写请求会重新取令牌', async () => {
    const calls = stubFetch(async (url) =>
      url === '/api/csrf-token' ? jsonResponse({ token: 'tok-1' }) : jsonResponse({ success: true })
    )

    await api.apiPost('/api/a')
    api.resetCsrfToken()
    await api.apiPost('/api/b')

    expect(calls.filter((c) => c.url === '/api/csrf-token')).toHaveLength(2)
  })
})

describe('表单提交', () => {
  it('数组编码为重复键，与后端的表单读取方式一致', async () => {
    const calls = stubFetch(async (url) =>
      url === '/api/csrf-token' ? jsonResponse({ token: 'tok-1' }) : jsonResponse({ success: true })
    )

    await api.apiPostForm('/manage/batch_delete_users', { 'usernames[]': ['a', 'b'] })

    expect(calls[1].init.body).toBe('usernames%5B%5D=a&usernames%5B%5D=b')
  })

  it('postFormRaw 只拦服务端报错，不把业务失败（302 回原页）当成异常', async () => {
    stubFetch(async (url) =>
      url === '/api/csrf-token' ? jsonResponse({ token: 'tok-1' }) : jsonResponse({}, 200)
    )

    const res = await api.postFormRaw('/login', { username: 'someone' })
    expect(res.status).toBe(200)
  })
})

describe('错误文案', () => {
  it('ApiError 保留具体原因，其他异常用调用方给的兜底', () => {
    expect(api.errorText(new api.ApiError('timeout', '请求超时（15 秒）'), '操作失败')).toBe(
      '请求超时（15 秒）'
    )
    expect(api.errorText(new Error('boom'), '操作失败')).toBe('操作失败')
    expect(api.errorText(null, '操作失败')).toBe('操作失败')
  })
})
