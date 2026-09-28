/**
 * 后端接口封装
 *
 * 说明：项目已有后端全部保留，前端只通过 JSON 接口与之交互。
 * 会话基于 Flask session cookie，因此所有请求都带 credentials: 'include'。
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text()
  if (!text) return {} as T
  try {
    return JSON.parse(text) as T
  } catch {
    // 非 JSON（例如被重定向到登录页返回了 HTML）
    throw new Error(`响应不是合法 JSON（HTTP ${res.status}）`)
  }
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
  const res = await fetch('/api/csrf-token', {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
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
    fetch(url, {
      ...init,
      headers: {
        ...(init.headers as Record<string, string>),
        ...(token ? { 'X-CSRFToken': token } : {}),
      },
    })

  let res = await send(await getCsrfToken())
  if (res.status === 403) {
    resetCsrfToken()
    res = await send(await getCsrfToken())
  }
  return res
}

/** GET JSON */
export async function apiGet<T = any>(url: string): Promise<T> {
  const res = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'application/json' },
  })
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
  return fetchWithCsrf(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: encodeForm(form),
    redirect: 'follow',
  })
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
}

export const session = {
  info: () => apiGet<SessionInfo>('/api/session'),
  logout: () => apiGet<{ success: boolean }>('/api/logout_json'),
  adminLogout: () => apiGet<{ success: boolean }>('/api/admin/logout_json'),
}

/* ---------------- 设备与采集 ---------------- */

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
      data_collected?: number
      model_trained?: boolean
      error?: string
      [key: string]: unknown
    }>('/api/start_data_collection', payload),
  status: (username: string) =>
    apiGet<{
      success: boolean
      status: string
      data_count?: number
      verification_count?: number
      verification_success?: number
      model_path?: string
      error?: string
    }>(`/api/registration_status/${encodeURIComponent(username)}`),
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
    }>('/api/verification_status'),
}

/* ---------------- 仪表盘 ---------------- */

export interface DashboardData {
  user_stats: {
    total_logins: number
    successful_auths: number
    failed_auths: number
    avg_response_time: number
  }
  system_stats: {
    uptime: string
    active_users: number
    total_devices: number
    data_integrity: number
  }
  performance_data: {
    success_rate: number
    accuracy_rate: number
    response_time: number
  }
  security_events: { time: string; event: string; status: string }[]
}

export const dashboard = {
  data: () => apiGet<DashboardData>('/api/dashboard_data'),
  realtime: () =>
    apiGet<{ heart_rate?: number; emotion?: string; alert_level?: string; [k: string]: unknown }>(
      '/api/realtime_health_data'
    ),
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
