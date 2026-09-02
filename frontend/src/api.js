// All calls go to the FastAPI backend (backend/api/main.py). CORS is open there
// for local dev, so a plain cross-origin fetch from the Vite dev server works.
export const BASE =
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'

async function get(path) {
  let res
  try {
    res = await fetch(BASE + path)
  } catch {
    throw new Error(
      `Can't reach the API at ${BASE}. Is "python backend/api/main.py" running?`
    )
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* body wasn't JSON */
    }
    throw new Error(`${res.status} - ${detail}`)
  }
  return res.json()
}

export const api = {
  assetTypes: () => get('/config/asset-types'),
  customerAssets: (id) => get(`/customer/${id}/assets`),
  customerAlerts: (id) => get(`/customer/${id}/alerts`),
  customerSmsReminders: (id) => get(`/customer/${id}/sms-reminders`),
  dealerCustomers: () => get('/dealer/customers'),
  dealerRenewalRisk: () => get('/dealer/renewal-risk'),
}
