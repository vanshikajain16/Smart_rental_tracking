// All calls go to the FastAPI backend (backend/api/main.py). CORS is open there
// for local dev, so a plain cross-origin fetch from the Vite dev server works.
export const BASE =
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

// --- session (bearer token) --------------------------------------------- //
const TOKEN_KEY = 'rental_token'
const CID_KEY = 'rental_customer_id'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getStoredCustomerId() {
  try {
    return localStorage.getItem(CID_KEY)
  } catch {
    return null
  }
}

export function saveSession(token, customerId) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(CID_KEY, customerId)
  } catch {
    /* private mode / storage disabled - token just won't persist a reload */
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(CID_KEY)
  } catch {
    /* ignore */
  }
}

// App registers a callback so an expired/rejected token bounces to the login.
let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

function formatDetail(detail, fallback) {
  if (!detail) return fallback
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  }
  return typeof detail === 'string' ? detail : JSON.stringify(detail)
}

async function request(path, { method = 'GET', body, auth = false } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (auth && token) headers['Authorization'] = `Bearer ${token}`

  let res
  try {
    res = await fetch(BASE + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error(
      `Can't reach the API at ${BASE}. Is "python backend/api/main.py" running?`
    )
  }

  if (res.status === 401 && auth) {
    clearSession()
    onUnauthorized()
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = formatDetail((await res.json()).detail, res.statusText)
    } catch {
      /* body wasn't JSON */
    }
    throw new Error(`${res.status} - ${detail}`)
  }
  return res.json()
}

const get = (path) => request(path)
const authGet = (path) => request(path, { auth: true })

export const api = {
  assetTypes: () => get('/config/asset-types'),

  // auth
  signup: (payload) =>
    request('/auth/signup', { method: 'POST', body: payload }),
  login: (payload) => request('/auth/login', { method: 'POST', body: payload }),
  me: () => authGet('/auth/me'),

  // customer (bearer token required, own data only)
  customerAssets: (id) => authGet(`/customer/${id}/assets`),
  customerAlerts: (id) => authGet(`/customer/${id}/alerts`),
  customerSmsReminders: (id) => authGet(`/customer/${id}/sms-reminders`),

  // dealer (unchanged, no auth)
  dealerCustomers: () => get('/dealer/customers'),
  dealerRenewalRisk: () => get('/dealer/renewal-risk'),
}
