import { clearNearbyDeviceUrlCache, getLocalDeviceHost } from './localDeviceLink'

const WS_LINK_PORT = 8766
const REQUEST_TIMEOUT_MS = 20_000
const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 10_000]

let socket = null
let reconnectAttempt = 0
let reconnectTimer = null
let closedByCaller = true
let currentPairingCode = null
let currentHandlers = null
let nextRequestId = 1
const pendingRequests = new Map()

function clearReconnectTimer() {
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

function scheduleReconnect() {
  if (closedByCaller) return
  clearReconnectTimer()
  const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)]
  reconnectAttempt += 1
  reconnectTimer = window.setTimeout(openSocket, delay)
}

function rejectAllPending(reason) {
  for (const { reject } of pendingRequests.values()) reject(new Error(reason))
  pendingRequests.clear()
}

async function openSocket() {
  if (closedByCaller || !currentPairingCode) return

  let host
  try {
    host = await getLocalDeviceHost()
  } catch {
    clearNearbyDeviceUrlCache()
    scheduleReconnect()
    return
  }
  if (closedByCaller) return

  const url = `ws://${host}:${WS_LINK_PORT}/v1/stream?code=${encodeURIComponent(currentPairingCode)}`
  const ws = new WebSocket(url)
  socket = ws

  ws.onopen = () => {
    reconnectAttempt = 0
    currentHandlers?.onOpen?.()
  }

  ws.onmessage = (event) => {
    let message
    try {
      message = JSON.parse(event.data)
    } catch {
      return
    }

    // The Pi asking THIS phone to run Gemini on a photo -- not a reply to
    // anything we sent, so it's handled separately from pendingRequests
    // below (which only tracks requests this side originated).
    if (message.type === 'vision_request') {
      const visionRequestId = message.request_id
      const reply = (payload) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'vision_result', request_id: visionRequestId, payload }))
        }
      }
      if (!currentHandlers?.onVisionRequest) {
        reply({ status: 'error', text_hi: '', error: 'Phone has no vision handler registered.' })
        return
      }
      Promise.resolve(currentHandlers.onVisionRequest(message.payload))
        .then(reply)
        .catch((error) => reply({ status: 'error', text_hi: '', error: String(error?.message || error) }))
      return
    }

    const requestId = message.request_id
    if (requestId != null && pendingRequests.has(requestId)) {
      const { resolve, reject } = pendingRequests.get(requestId)
      pendingRequests.delete(requestId)
      if (message.type === 'command_result' && message.status_code >= 400) {
        reject(new Error(message.payload?.error || message.payload?.text_hi || 'Nearby command failed.'))
      } else if (message.type === 'settings_ack' && message.payload?.status === 'error') {
        reject(new Error(message.payload.error || 'Could not apply settings.'))
      } else {
        resolve(message.payload)
      }
    }

    if (message.type === 'status') currentHandlers?.onStatus?.(message.payload)
    else if (message.type === 'alert') currentHandlers?.onAlert?.(message.payload)
    else if (message.type === 'wake_requested') currentHandlers?.onWakeRequested?.()
  }

  ws.onclose = () => {
    if (socket === ws) socket = null
    clearNearbyDeviceUrlCache()
    rejectAllPending('Nearby glasses connection closed.')
    currentHandlers?.onClose?.()
    scheduleReconnect()
  }

  ws.onerror = () => {
    ws.close()
  }
}

/** Open (or re-open) the push link to the nearby glasses. Reconnects on its
 * own with backoff until disconnectLocalSocket() is called. */
export function connectLocalSocket(pairingCode, handlers = {}) {
  closedByCaller = false
  currentPairingCode = pairingCode
  currentHandlers = handlers
  reconnectAttempt = 0
  openSocket()
}

export function disconnectLocalSocket() {
  closedByCaller = true
  clearReconnectTimer()
  rejectAllPending('Nearby glasses link closed.')
  currentHandlers = null
  currentPairingCode = null
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
}

export function isLocalSocketConnected() {
  return !!socket && socket.readyState === WebSocket.OPEN
}

function sendRequest(type, payload) {
  if (!isLocalSocketConnected()) {
    return Promise.reject(new Error('Nearby glasses socket is not connected.'))
  }
  const requestId = nextRequestId++
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      pendingRequests.delete(requestId)
      reject(new Error('Nearby glasses did not respond in time.'))
    }, REQUEST_TIMEOUT_MS)
    pendingRequests.set(requestId, {
      resolve: (value) => { window.clearTimeout(timeout); resolve(value) },
      reject: (error) => { window.clearTimeout(timeout); reject(error) },
    })
    socket.send(JSON.stringify({ type, request_id: requestId, payload }))
  })
}

export function sendLocalCommand(command) {
  return sendRequest('command', { command })
}

/** Push settings to nearby glasses immediately over the socket. Cloud ack
 * (Supabase) remains the separate, authoritative confirmation. */
export function sendLocalSettings(values) {
  return sendRequest('update_settings', {
    sensitivity_mm: values.sensitivity_mm,
    feedback_mode: values.feedback_mode,
    volume: values.volume,
    vibration_intensity: values.vibration_intensity,
    request_id: values.request_id || undefined,
  })
}
