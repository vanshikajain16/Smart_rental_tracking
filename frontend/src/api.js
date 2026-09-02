// All calls go to the FastAPI backend (backend/api/main.py). CORS is open there
// for local dev, so a plain cross-origin fetch from the Vite dev server works.
export const BASE =
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

// --- token storage ---------------------------------------------------- //
const TOKEN_KEY = 'rental_tracker_token'
const CUSTOMER_ID_KEY = 'rental_tracker_customer_id'

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function getCustomerId() {
  try {
    return localStorage.getItem(CUSTOMER_ID_KEY)
  } catch {
    return null
  }
}

function storeSession(token, customerId) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(CUSTOMER_ID_KEY, customerId)
  } catch {
    /* private mode / storage disabled - session just won't survive a reload */
  }
}

export function logout() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(CUSTOMER_ID_KEY)
  } catch {
    /* ignore */
  }
}

// App registers this so a rejected token (expired etc.) bounces to the login.
let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

function describeError(payload, fallback) {
  const detail = payload && payload.detail
  if (!detail) return fallback
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  }
  return typeof detail === 'string' ? detail : JSON.stringify(detail)
}

async function request(path, { method = 'GET', body, withAuth = false } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (withAuth) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

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

  if (res.status === 401 && withAuth) {
    logout()
    onUnauthorized()
  }

  let data = null
  try {
    data = await res.json()
  } catch {
    /* no / non-JSON body */
  }

  if (!res.ok) {
    throw new Error(describeError(data, `${res.status} ${res.statusText}`))
  }
  return data
}

// --- auth ----------------------------------------------------------- //
// POST /auth/login -> { access_token, token_type, customer_id }
// Stores the JWT + customer_id in localStorage and returns the body.
export async function login(email, password) {
  const data = await request('/auth/login', {
    method: 'POST',
    body: { email, password },
  })
  storeSession(data.access_token, data.customer_id)
  return data
}

// POST /auth/signup -> { message: "account created" }
// Does NOT log in - the user signs in as a separate step.
export async function signup(email, password, customerId) {
  return request('/auth/signup', {
    method: 'POST',
    body: { email, password, customer_id: customerId },
  })
}

// GET /auth/check-email -> { exists: bool }. UX hint only (see backend note):
// used after a failed login to tell "no account yet" from "wrong password".
export async function checkEmail(email) {
  return request(`/auth/check-email?email=${encodeURIComponent(email)}`)
}

export const api = {
  login,
  signup,
  checkEmail,
  logout,

  assetTypes: () => request('/config/asset-types'),

  // customer (bearer token required, own data only)
  customerAssets: (id) => request(`/customer/${id}/assets`, { withAuth: true }),
  customerAlerts: (id) => request(`/customer/${id}/alerts`, { withAuth: true }),
  customerSmsReminders: (id) =>
    request(`/customer/${id}/sms-reminders`, { withAuth: true }),

  // connected operators — per-asset contacts (bearer token, own asset only)
  assetContacts: (customerId, equipmentId) =>
    request(`/customer/${customerId}/assets/${equipmentId}/contacts`, {
      withAuth: true,
    }),
  addAssetContact: (customerId, equipmentId, body) =>
    request(`/customer/${customerId}/assets/${equipmentId}/contacts`, {
      method: 'POST',
      body,
      withAuth: true,
    }),
  removeAssetContact: (customerId, equipmentId, contactId) =>
    request(
      `/customer/${customerId}/assets/${equipmentId}/contacts/${contactId}`,
      { method: 'DELETE', withAuth: true }
    ),

  // dealer (no auth)
  dealerCustomers: () => request('/dealer/customers'),
  dealerRenewalRisk: () => request('/dealer/renewal-risk'),
  dealerCustomerDetail: (id) =>
    request(`/dealer/customers/${encodeURIComponent(id)}`),
  // same per-asset shape as /customer/{id}/assets, dealer side (no auth)
  dealerCustomerAssets: (id) =>
    request(`/dealer/customer/${encodeURIComponent(id)}/assets`),
  dealerSummary: () => request('/dealer/summary'),
  // retroactive feed, newest first, top 50 (no server-side filter)
  dealerActivityFeed: () => request('/dealer/activity-feed'),
}
