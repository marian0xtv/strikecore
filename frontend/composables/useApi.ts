/**
 * Centralized API client for StrikeCore C2 backend.
 * All endpoints consumed from the existing Flask API on port 5000.
 */

async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  // Same origin — Flask serves both UI and API on port 5000
  const res = await fetch(path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...opts.headers,
    },
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`)
  return res.json()
}

// ── Dashboard / Investigations ──

export function useInvestigations() {
  return useAsyncData('investigations', () => api('/api/findings/_list').catch(() => []))
}

export function useFindings(tid: string) {
  return useAsyncData(`findings-${tid}`, () => api(`/api/findings/${tid}`))
}

export function useGraph(tid: string) {
  return useAsyncData(`graph-${tid}`, () => api(`/api/graph/${tid}`))
}

export function usePhotos(tid: string) {
  return useAsyncData(`photos-${tid}`, () => api(`/api/photos/${tid}`))
}

// ── Tracking ──

export function useTrackingHits(tid: string) {
  return useAsyncData(`tracking-${tid}`, () => api(`/api/tracking/hits/${tid}`), {
    server: false,
  })
}

export async function createTracker(label: string, destination: string) {
  return api('/api/tracking/create', {
    method: 'POST',
    body: JSON.stringify({ label, destination }),
  })
}

// ── Tunnel ──

export function useTunnelStatus() {
  return useAsyncData('tunnel', () => api('/api/tunnel/status'), { server: false })
}

export async function tunnelStart() {
  return api('/api/tunnel/start', { method: 'POST' })
}

export async function tunnelStop() {
  return api('/api/tunnel/stop', { method: 'POST' })
}

export async function tunnelRestart() {
  return api('/api/tunnel/restart', { method: 'POST' })
}

// ── Gateway Telefonico ──

export function usePhonebook() {
  return useAsyncData('phonebook', () => api('/api/gateway/phonebook'), { server: false })
}

export function useGatewayStatus() {
  return useAsyncData('gw-status', () => api('/api/gateway/status'), { server: false })
}

export async function gatewayCall(number: string, method: string) {
  return api('/api/gateway/call', {
    method: 'POST',
    body: JSON.stringify({ number, method }),
  })
}

export async function gatewayWaCheck(number: string) {
  return api('/api/gateway/wa-check', {
    method: 'POST',
    body: JSON.stringify({ number }),
  })
}

// ── Email Tracker ──

export async function generateEmailTracker(email: string, subject: string, template: string) {
  return api('/api/email-tracker/generate', {
    method: 'POST',
    body: JSON.stringify({ email, subject, template }),
  })
}

// ── GEOINT ──

export function useGeoint(lat: number, lon: number) {
  return useAsyncData(`geoint-${lat}-${lon}`, () =>
    api(`/api/geoint?lat=${lat}&lon=${lon}`)
  )
}

export async function geocode(query: string) {
  return api(`/api/geocode?q=${encodeURIComponent(query)}`)
}

// ── Exec ──

export async function execCommand(command: string) {
  return api('/api/exec', {
    method: 'POST',
    body: JSON.stringify({ command }),
  })
}

// ── Raw fetch for pages that need HTML scraping (dashboard index, etc.) ──

export async function fetchDashboardData() {
  // The Flask / route returns HTML with embedded data — we parse what we need
  // For a cleaner solution, we'll fetch individual API endpoints
  const [phonebook, gwStatus, tunnel] = await Promise.all([
    api('/api/gateway/phonebook').catch(() => ({ count: 0, phones: [] })),
    api('/api/gateway/status').catch(() => ({})),
    api('/api/tunnel/status').catch(() => ({ running: false })),
  ])
  return { phonebook, gwStatus, tunnel }
}

// ── Polling helper ──

export function usePoll<T>(path: string, intervalMs = 3000) {
  const data = ref<T | null>(null)
  const error = ref<string | null>(null)

  let timer: ReturnType<typeof setInterval>

  const poll = async () => {
    try {
      data.value = await api<T>(path)
      error.value = null
    } catch (e: any) {
      error.value = e.message
    }
  }

  onMounted(() => {
    poll()
    timer = setInterval(poll, intervalMs)
  })

  onUnmounted(() => clearInterval(timer))

  return { data, error, refresh: poll }
}
