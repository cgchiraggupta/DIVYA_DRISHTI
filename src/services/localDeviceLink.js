import { Capacitor, CapacitorHttp, registerPlugin } from '@capacitor/core'

const LOCAL_DEVICE_HOSTS = ['divyadrishti.local', '192.168.1.39']
const LOCAL_DEVICE_PORT = 8765
const LOCAL_DEVICE_CACHE_MS = 15_000
const LOCAL_DEVICE_URL_KEY = 'divyadrishti-local-url'
const LocalDeviceDiscovery = registerPlugin('LocalDeviceDiscovery')
let cachedDeviceUrl = null
let cachedAt = 0

function hostUrl(host) {
  const safeHost = host.includes(':') ? `[${host}]` : host
  return `http://${safeHost}:${LOCAL_DEVICE_PORT}`
}

async function tryRequest(url, path, pairingCode, options) {
  const headers = {
    'X-Divya-Pairing-Code': pairingCode,
    ...options.headers,
  }
  const connectTimeout = options.connectTimeout ?? 2_500
  const readTimeout = options.readTimeout ?? 2_500

  if (Capacitor.isNativePlatform()) {
    const response = await CapacitorHttp.request({
      url: `${url}${path}`,
      method: options.method ?? 'GET',
      headers,
      data: options.body ? JSON.parse(options.body) : undefined,
      connectTimeout,
      readTimeout,
    })
    if (response.status < 200 || response.status >= 300) {
      throw new Error(`Nearby glasses returned ${response.status}`)
    }
    // CapacitorHttp sometimes returns a JSON string instead of an object.
    if (typeof response.data === 'string') {
      try {
        return JSON.parse(response.data)
      } catch {
        return response.data
      }
    }
    return response.data
  }

  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), readTimeout)
  try {
    const response = await fetch(`${url}${path}`, {
      method: options.method,
      headers,
      body: options.body,
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`Nearby glasses returned ${response.status}`)
    return response.json()
  } finally {
    window.clearTimeout(timeout)
  }
}

async function getLocalDeviceUrl() {
  if (!Capacitor.isNativePlatform()) return hostUrl(LOCAL_DEVICE_HOSTS[0])
  if (cachedDeviceUrl && Date.now() - cachedAt < LOCAL_DEVICE_CACHE_MS) return cachedDeviceUrl

  const candidates = []

  try {
    const { host, port } = await LocalDeviceDiscovery.discover()
    candidates.push(`http://${host.includes(':') ? `[${host}]` : host}:${port}`)
  } catch {
    // mDNS often fails on Android; fall through to hostname/IP retries.
  }

  for (const host of LOCAL_DEVICE_HOSTS) candidates.push(hostUrl(host))
  try {
    const saved = window.localStorage.getItem(LOCAL_DEVICE_URL_KEY)
    if (saved) candidates.unshift(saved)
  } catch {
    // ignore storage errors
  }

  let lastError = null
  for (const url of candidates) {
    try {
      await tryRequest(url, '/v1/health', '', { connectTimeout: 1_500, readTimeout: 1_500 })
      cachedDeviceUrl = url
      cachedAt = Date.now()
      try { window.localStorage.setItem(LOCAL_DEVICE_URL_KEY, url) } catch { /* ignore */ }
      return url
    } catch (error) {
      lastError = error
    }
  }

  throw lastError ?? new Error('Could not reach nearby glasses on this Wi-Fi.')
}

async function request(path, pairingCode, options = {}) {
  const url = await getLocalDeviceUrl()
  return tryRequest(url, path, pairingCode, options)
}

export function getNearbyDeviceStatus(pairingCode) {
  return request('/v1/status', pairingCode, {
    connectTimeout: 3_000,
    readTimeout: 8_000,
  })
}

/** Drop cached glasses URL so the next call rediscovers (mDNS/IP). */
export function clearNearbyDeviceUrlCache() {
  cachedDeviceUrl = null
  cachedAt = 0
}

export function sendNearbyCommand(pairingCode, command) {
  return request('/v1/command', pairingCode, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command }),
  })
}

/** On-demand Describe (objects) or Read (OCR). Longer timeout — Gemini may take several seconds. */
export function sendNearbyDescribe(pairingCode, command = 'describe') {
  const safeCommand = command === 'read' ? 'read' : 'describe'
  return request('/v1/command', pairingCode, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: safeCommand }),
    connectTimeout: 5_000,
    readTimeout: 20_000,
  })
}

export function sendNearbyRead(pairingCode) {
  return sendNearbyDescribe(pairingCode, 'read')
}

/** Push settings to nearby glasses immediately (same Wi-Fi). Cloud ack remains separate. */
export function sendNearbySettings(pairingCode, values) {
  return request('/v1/settings', pairingCode, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sensitivity_mm: values.sensitivity_mm,
      feedback_mode: values.feedback_mode,
      volume: values.volume,
      vibration_intensity: values.vibration_intensity,
      request_id: values.request_id || undefined,
    }),
    connectTimeout: 3_000,
    readTimeout: 8_000,
  })
}
