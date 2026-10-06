/**
 * 后端接口封装
 *
 * 说明：项目已有后端全部保留，前端只通过 JSON 接口与之交互。
 * 会话基于 Flask session cookie，因此所有请求都带 credentials: 'include'。
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * 读请求 / 写请求的超时上限（毫秒）。
 *
 * 采集与训练类接口在后端是**同步执行**的，会跑上几分钟，因此写请求给到 2 分钟；
 * 读接口超过 15 秒基本可判定后端异常（最慢的 BLE 扫描正常也只需数秒）。
 */
const READ_TIMEOUT_MS = 15_000
const WRITE_TIMEOUT_MS = 120_000

export type ApiErrorKind = 'network' | 'timeout' | 'session' | 'http' | 'parse'

/**
 * 接口错误。
 *
 * `kind` 是给调用方分支用的：网络不通、超时、会话失效、服务端报错、
 * 响应格式异常，这几种要给用户的提示完全不同 —— 全部糊成一句「请求失败」
 * 会让排查变得很难（原先正是如此）。
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status: number

  constructor(kind: ApiErrorKind, message: string, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
  }
}

/**
 * 发出请求并施加超时。
 *
 * 超时用 AbortController 手写，而非 `AbortSignal.timeout()`：后者依赖较新的
 * TS lib 定义，而这里只需要几行，不值得为它引入 lib 版本要求。
 */
async function request(
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch {
    // fetch 只在「网络层失败」与「主动 abort」时抛异常；HTTP 4xx/5xx
    // 属于正常返回，交给调用方的 res.ok 判定，不要在这里吞掉。
    if (controller.signal.aborted) {
      throw new ApiError(
        'timeout',
        `请求超时（${Math.round(timeoutMs / 1000)} 秒），请检查后端服务是否正常`
      )
    }
    throw new ApiError('network', '网络请求失败，请确认后端服务已启动')
  } finally {
    window.clearTimeout(timer)
  }
}

/** 被重定向到登录页 = 会话已失效 */
function isLoginRedirect(res: Response): boolean {
  if (!res.redirected) return false
  try {
    const { pathname } = new URL(res.url)
    return pathname.startsWith('/login') || pathname.startsWith('/manage/login')
  } catch {
    return false
  }
}

/**
 * 把捕获到的异常转成一句能给用户看的话。
 *
 * `ApiError` 里已经带了具体原因（超时了多久、会话是否失效、服务端说了什么），
 * 直接丢掉它换成一句笼统的「请求失败」，会让排查无从下手 —— 原先各处
 * 的 `catch {}` 正是如此。
 */
export function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError && err.message ? err.message : fallback
}

/** 从响应体里尽量取出一句人类可读的失败原因 */
function extractErrorMessage(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null
  const record = payload as Record<string, unknown>
  for (const key of ['error', 'message', 'reason']) {
    const value = record[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

/**
 * 解析响应。
 *
 * 关键在于**先看 `res.ok`**：原先只看「能否 JSON.parse」，于是 4xx/5xx 只要
 * 带个 JSON body 就会被当成成功解析，调用方拿到一个没有业务字段的对象 ——
 * 界面表现为空白或一直转圈，而不是报错。
 */
async function parse<T>(res: Response): Promise<T> {
  const text = await res.text()

  let payload: unknown
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      // 拿到的不是 JSON：多半是被重定向（或反向代理）成了 HTML 页面
      if (isLoginRedirect(res)) {
        throw new ApiError('session', '登录状态已失效，请重新登录', res.status)
      }
      throw new ApiError('parse', `响应不是合法 JSON（HTTP ${res.status}）`, res.status)
    }
  }

  if (!res.ok) {
    throw new ApiError(
      isLoginRedirect(res) ? 'session' : 'http',
      extractErrorMessage(payload) ?? `请求失败（HTTP ${res.status}）`,
      res.status
    )
  }

  return (payload ?? {}) as T
}

/* ---------------- CSRF 令牌 ---------------- */

/**
 * 后端要求所有写请求带上与会话绑定的令牌（请求头 X-CSRFToken）。
 * 令牌存在 httponly 的 session cookie 里，JS 读不到，因此先向
 * /api/csrf-token 取一次并缓存下来；GET 请求不受影响。
 */
let csrfToken: string | null = null
let csrfRequest: Promise<string> | null = null

/** 丢弃已缓存的令牌（会话轮换后调用） */
export function resetCsrfToken(): void {
  csrfToken = null
}

async function requestCsrfToken(): Promise<string> {
  const res = await request(
    '/api/csrf-token',
    {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json' },
    },
    READ_TIMEOUT_MS
  )
  const data = (await res.json().catch(() => null)) as { token?: string } | null
  csrfToken = data?.token ?? ''
  return csrfToken
}

/** 取当前会话的 CSRF 令牌（并发调用共用同一次请求） */
export async function getCsrfToken(): Promise<string> {
  if (csrfToken !== null) return csrfToken
  if (!csrfRequest) {
    csrfRequest = requestCsrfToken().finally(() => {
      csrfRequest = null
    })
  }
  return csrfRequest
}

/**
 * 发起写请求并自动带上 CSRF 令牌。
 *
 * 收到 403 时丢弃缓存令牌重试一次：会话可能已经轮换（cookie 超时、
 * 服务端重启），不重试的话用户会被一个陈旧令牌永久卡住。
 * body 始终是字符串，因此可以安全地重复发送。
 */
async function fetchWithCsrf(url: string, init: RequestInit): Promise<Response> {
  const send = (token: string) =>
    request(
      url,
      {
        ...init,
        headers: {
          ...(init.headers as Record<string, string>),
          ...(token ? { 'X-CSRFToken': token } : {}),
        },
      },
      WRITE_TIMEOUT_MS
    )

  let res = await send(await getCsrfToken())
  if (res.status === 403) {
    resetCsrfToken()
    res = await send(await getCsrfToken())
  }
  return res
}

/** GET JSON */
export async function apiGet<T = any>(url: string): Promise<T> {
  const res = await request(
    url,
    {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'application/json' },
    },
    READ_TIMEOUT_MS
  )
  return parse<T>(res)
}

/** POST JSON */
export async function apiPost<T = any>(
  url: string,
  body?: unknown
): Promise<T> {
  const res = await fetchWithCsrf(url, {
    method: 'POST',
    credentials: 'include',
    headers: JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return parse<T>(res)
}

/** 把表单对象编码为 application/x-www-form-urlencoded */
function encodeForm(
  form: Record<string, string | number | boolean | string[]>
): string {
  const data = new URLSearchParams()
  Object.entries(form).forEach(([k, v]) => {
    if (Array.isArray(v)) {
      v.forEach((item) => data.append(k, String(item)))
    } else {
      data.append(k, String(v))
    }
  })
  return data.toString()
}

/**
 * POST 表单并返回原始 Response
 *
 * 供需要读取「重定向后的最终地址」的场景使用（例如 /login 成功后跳 /verify），
 * 这类响应本身不是 JSON，只能靠最终 URL 判断结果。
 */
export async function postFormRaw(
  url: string,
  form: Record<string, string | number | boolean | string[]> = {}
): Promise<Response> {
  const res = await fetchWithCsrf(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: encodeForm(form),
    redirect: 'follow',
  })

  // 这里只拦「服务端确实报错」这一种情况。不要顺手把「最终 URL 不是预期」
  // 也当成错误：这类接口是「表单 + 重定向」语义，业务失败会 302 回原页面
  // （仍是 200），调用方要靠最终 URL 区分成功与失败（见 login.tsx）。
  if (!res.ok) {
    throw new ApiError(
      isLoginRedirect(res) ? 'session' : 'http',
      `表单提交失败（HTTP ${res.status}）`,
      res.status
    )
  }
  return res
}

/** POST 表单（Flask 部分接口只读 form 数据） */
export async function apiPostForm<T = any>(
  url: string,
  form: Record<string, string | number | boolean | string[]>
): Promise<T> {
  const res = await postFormRaw(url, form)
  return parse<T>(res)
}

/* ---------------- 会话 ---------------- */

export interface SessionInfo {
  authenticated: boolean
  username: string | null
  isAdmin: boolean
  pendingLogin: string | null
  /** 算法层是否可用；不可用时验证无法进行 */
  systemAvailable?: boolean
  /** 演示模式：开启时采集不到真实信号会改用合成数据，界面需显著提示 */
  demoMode?: boolean
}

export const session = {
  info: () => apiGet<SessionInfo>('/api/session'),
  logout: () => apiGet<{ success: boolean }>('/api/logout_json'),
  adminLogout: () => apiGet<{ success: boolean }>('/api/admin/logout_json'),
}

/* ---------------- 设备与采集 ---------------- */

/**
 * 后端注册流程会写入的状态。
 *
 * 刻意用字面量联合而不是 `string`：前端要靠它做**穷尽判定**——
 * 只有 `ACTIVE_REGISTRATION_STATES`（白名单）里的状态才继续轮询，
 * 其余一律终止并显示原因。后端每新增一个终态，白名单写法都天然覆盖；
 * 但若这里写成 `string`，新增状态在编译期不会有任何提示。
 */
export type RegistrationState =
  | 'pending'
  | 'collecting'
  | 'training'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'error'
  | 'device_error'

/**
 * `/api/registration_status/<username>` 的 `status` 字段。
 *
 * ⚠️ 它是一个**对象**而不是字符串 —— 后端 `registration_status()` 返回的是
 * `{'success': true, 'status': {…状态字典…}}`。原先前端把这里声明成
 * `status: string`，于是消费处只能写 `res.status as unknown as
 * Record<string, unknown>` 双重断言绕过类型检查 —— 类型系统在这里
 * 完全失去保护作用，字段名写错也不会报错。
 */
export interface RegistrationStatus {
  status?: RegistrationState
  /** 自检进度：已完成 / 总数 */
  verification_count?: number
  verification_success?: number
  total_count?: number
  model_path?: string | null
  /** 失败/设备断开时的原因（后端如实写明） */
  error_message?: string
  /** 本次注册基于合成数据（演示模式），界面需显著提示 */
  demo?: boolean
  demo_reasons?: string[]
}

export interface DeviceItem {
  name?: string
  address?: string
  device?: string
  type?: string
  rssi?: number
  port?: string
  description?: string
  [key: string]: unknown
}

export const device = {
  scan: (deviceType: 'all' | 'ble' | 'serial' = 'all') =>
    apiPost<{ success: boolean; devices?: DeviceItem[]; error?: string }>(
      '/api/scan_devices',
      { device_type: deviceType }
    ),
  connect: (payload: Record<string, unknown>) =>
    apiPost<{ success: boolean; message?: string; error?: string }>(
      '/api/connect_device',
      payload
    ),
}

export const registration = {
  /** 开始采集（耗时接口，后端同步执行） */
  start: (payload: {
    username: string
    device_type: string
    [key: string]: unknown
  }) =>
    apiPost<{
      success: boolean
      message?: string
      error?: string
    }>('/api/start_data_collection', payload),
  status: (username: string) =>
    apiGet<{
      success: boolean
      error?: string
    } & RegistrationStatus>(`/api/registration_status/${encodeURIComponent(username)}`),
}

/* ---------------- 身份验证 ---------------- */

export const verification = {
  start: (payload: Record<string, unknown> = {}) =>
    apiPost<{ success: boolean; error?: string }>(
      '/api/start_verification',
      payload
    ),
  status: () =>
    apiGet<{
      success: boolean
      status: 'verifying' | 'completed' | 'failed'
      redirect?: string
      error?: string
      /** 判定未通过时的原因（未采集到数据 / 模型不可用 / 算法层不可用等） */
      reason?: string
      /** 本次结果基于合成信号（演示模式），需向用户明示 */
      demo?: boolean
    }>('/api/verification_status'),
}

/* ---------------- 仪表盘 ---------------- */

export interface DashboardData {
  /** 真实统计：取自 users / auth_history 集合 */
  user_stats: {
    total_logins: number
    successful_auths: number
    failed_auths: number
    avg_response_time: number
    /** false 表示尚无认证记录 —— 上面的次数是「还没有记录」，不是「统计为 0」 */
    has_history: boolean
  }
  /** 真实：运行时长 / 注册用户数 / 已连接设备数；示意：data_integrity */
  system_stats: {
    uptime: string
    active_users: number
    total_devices: number
    data_integrity: number
  }
  /** 示意数据（见 synthetic_fields） */
  performance_data: {
    success_rate: number
    accuracy_rate: number
    response_time: number
  }
  /** 示意数据（见 synthetic_fields） */
  security_events: { time: string; event: string; status: string }[]
  /** 响应中属于「界面示意数据」的字段路径，界面需据此提示用户 */
  synthetic_fields?: string[]
  synthetic_note?: string
}

/** 实时生理数据；后端明确标为合成（`synthetic`），界面必须据此提示 */
export interface RealtimeHealthData {
  heart_rate?: number
  emotion_status?: string
  alert_level?: string
  ecg_signal?: number[]
  ppg_signal?: number[]
  timestamp?: string
  synthetic?: boolean
  synthetic_note?: string
  [k: string]: unknown
}

export const dashboard = {
  data: () => apiGet<DashboardData>('/api/dashboard_data'),
  realtime: () => apiGet<RealtimeHealthData>('/api/realtime_health_data'),
  trends: () => apiGet<Record<string, unknown>>('/api/health_trends'),
}

/* ---------------- 管理后台 ---------------- */

export interface AdminUser {
  username: string
  created_at?: string
  model_path?: string
}

export const admin = {
  users: () => apiGet<{ success: boolean; users?: AdminUser[] }>('/api/admin/users'),
  config: () =>
    apiGet<{ success: boolean; config?: Record<string, Record<string, unknown>> }>(
      '/api/admin/config'
    ),
  /** 更新系统参数（后端只读 form） */
  updateParams: (form: Record<string, string | number | boolean>) =>
    apiPostForm<{ success: boolean; message?: string; error?: string }>(
      '/manage/update_params',
      form
    ),
  deleteUser: (username: string) =>
    apiPostForm(`/manage/delete_user/${encodeURIComponent(username)}`, {}),
  batchDelete: (usernames: string[]) =>
    apiPostForm('/manage/batch_delete_users', { 'usernames[]': usernames }),
}
