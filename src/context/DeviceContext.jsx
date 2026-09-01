import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { supabase, isDemoMode } from '../lib/supabaseClient'
import { createDemoEvent, demoDevice, demoEvents, demoStatus, sceneSpeakText } from '../lib/demoData'
import { signalGuidance, speakGuidance } from '../services/sensoryFeedback'
import { sendNearbyCommand, sendNearbyDescribe, sendNearbyRead } from '../services/localDeviceLink'
import { connectLocalSocket, disconnectLocalSocket, isLocalSocketConnected, sendLocalCommand } from '../services/localSocketLink'
import { describeForGlasses } from '../services/glassesVision'
import { loadObstacleHistory, saveObstacleHistoryItem } from '../services/obstacleHistory'
import { startBackgroundGuardian, stopBackgroundGuardian } from '../services/backgroundGuardian'
import { startWakeListener, stopWakeListener } from '../services/wakeListener'
import { isNavigatingActive } from '../navigation/navActiveFlag'

const DeviceContext = createContext(undefined)
const PAIRING_CODE_KEY = 'divya-drishti-pairing-code'
const LAST_PHONE_ALERT_KEY = 'divyadrishti-last-phone-alert-id'

/**
 * Send a companion command over the push socket when it's open (instant,
 * no per-call HTTP round trip); otherwise fall back to the existing HTTP
 * link. The Pi answers both transports from the same handler, so the
 * response shape is identical either way.
 */
async function withLocalSocket(command, httpFallback) {
  if (isLocalSocketConnected()) {
    try {
      return await sendLocalCommand(command)
    } catch {
      // Socket call failed in flight — fall back to HTTP below.
    }
  }
  return httpFallback()
}

/**
 * Short two-tone cue before an auto-describe speaks. This speech was not
 * requested by tapping anything, so the cue tells the person "the glasses
 * noticed something on their own" before the description starts, distinct
 * from an obstacle alert's buzz/beep.
 */
function playAutoDescribeCue() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return Promise.resolve()
    const ctx = new Ctx()
    const now = ctx.currentTime
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0.001, now)
    gain.gain.exponentialRampToValueAtTime(0.2, now + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.22)
    gain.connect(ctx.destination)

    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(880, now)
    osc.frequency.setValueAtTime(1320, now + 0.11)
    osc.connect(gain)
    osc.start(now)
    osc.stop(now + 0.24)

    return new Promise((resolve) => {
      osc.onended = () => {
        ctx.close().catch(() => {})
        resolve()
      }
      window.setTimeout(resolve, 300)
    })
  } catch {
    return Promise.resolve()
  }
}

export function DeviceProvider({ children }) {
  const [device, setDevice] = useState(null)
  const [status, setStatus] = useState(null)
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [nearbyLink, setNearbyLink] = useState({ state: 'idle', status: null })
  const [dataError, setDataError] = useState(null)
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null)
  const [obstacleHistory, setObstacleHistory] = useState(() => loadObstacleHistory())
  const [wakeRequestedAt, setWakeRequestedAt] = useState(0)
  const speakingAlertRef = useRef(false)

  /**
   * Speak one alert on this phone. A stuck TTS call must never latch the guard,
   * or every later obstacle goes silent for the rest of the walk.
   */
  const speakAlertOnce = useCallback(async (text) => {
    if (!text || speakingAlertRef.current) return
    speakingAlertRef.current = true
    const release = window.setTimeout(() => {
      speakingAlertRef.current = false
    }, 10_000)
    try {
      console.log('[tts] speaking alert:', text)
      await speakGuidance(text, 1, { fast: true })
      console.log('[tts] alert spoken')
    } catch (error) {
      console.warn('[tts] alert failed', error)
    } finally {
      window.clearTimeout(release)
      speakingAlertRef.current = false
    }
  }, [])

  const loadDevice = useCallback(async ({ background = false } = {}) => {
    if (isDemoMode) {
      setDevice(demoDevice)
      setStatus(demoStatus)
      setEvents(demoEvents)
      setDataError(null)
      setLastRefreshedAt(new Date().toISOString())
      setLoading(false)
      return
    }

    const pairingCode = window.localStorage.getItem(PAIRING_CODE_KEY)
    if (!pairingCode) {
      setDevice(null)
      setStatus(null)
      setEvents([])
      setDataError(null)
      setLoading(false)
      return
    }
    // Never flip global loading on background polls — that remounts pages
    // (History tabs reset to Obstacles, full-screen flicker every ~15s).
    if (!background) setLoading(true)

    try {
      const { data: activeDevice, error: deviceError } = await supabase
        .from('devices')
        .select('*')
        .eq('pairing_code', pairingCode)
        .maybeSingle()

      if (deviceError) throw deviceError
      setDevice(activeDevice ?? null)

      if (!activeDevice) {
        setStatus(null)
        setEvents([])
        setDataError('This paired device could not be found. Pair it again to reconnect.')
        return
      }

      const [{ data: statusRow, error: statusError }, { data: eventRows, error: eventsError }] = await Promise.all([
        supabase.from('device_status').select('*').eq('device_id', activeDevice.id).maybeSingle(),
        supabase
          .from('device_events')
          .select('*')
          .eq('device_id', activeDevice.id)
          .order('created_at', { ascending: false })
          .limit(50),
      ])
      if (statusError) throw statusError
      if (eventsError) throw eventsError

      setStatus(statusRow ?? null)
      setEvents(eventRows ?? [])
      setDataError(null)
      setLastRefreshedAt(new Date().toISOString())
    } catch {
      setDataError('The app could not refresh device information. Showing the last known status.')
    } finally {
      if (!background) setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDevice()
  }, [loadDevice])

  // Re-check the source of truth even if a Realtime subscription drops.
  useEffect(() => {
    if (isDemoMode || !device) return undefined
    const interval = window.setInterval(() => loadDevice({ background: true }), 15_000)
    return () => window.clearInterval(interval)
  }, [device, loadDevice])

  const playPreviewScene = useCallback((scene) => {
    if (!isDemoMode) return
    const event = createDemoEvent(scene)
    setDevice((current) => ({ ...(current ?? demoDevice), last_seen_at: event.created_at }))
    setStatus((current) => ({
      ...(current ?? demoStatus),
      current_alert: scene.event_type,
      mode: scene.id === 'ground' ? 'camera_fallback' : 'tof',
      updated_at: event.created_at,
    }))
    setEvents((current) => [event, ...current].slice(0, 200))
    signalGuidance({
      text: sceneSpeakText(scene),
      isHazard: scene.event_type !== 'path_clear',
    })
  }, [])

  // Live updates: device_status changes + new device_events rows
  useEffect(() => {
    if (isDemoMode || !device) return undefined

    const channel = supabase
      .channel(`device-${device.id}`)
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'device_status', filter: `device_id=eq.${device.id}` },
        (payload) => setStatus(payload.new)
      )
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'device_events', filter: `device_id=eq.${device.id}` },
        (payload) => setEvents((prev) => [payload.new, ...prev].slice(0, 200))
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [device])

  // Prefer a nearby Wi-Fi link for immediate connection feedback. Cloud
  // Realtime remains the history and away-from-home fallback.
  // Poll often enough to pick up Gemini phone_alert payloads after obstacles.
  useEffect(() => {
    const nearbyPairingCode = isDemoMode
      ? import.meta.env.VITE_LOCAL_PAIRING_CODE
      : device?.pairing_code

    if (!nearbyPairingCode) {
      setNearbyLink({ state: 'idle', status: null })
      return undefined
    }

    let active = true
    // Hold the CPU and Wi-Fi awake for as long as this device stays paired.
    startBackgroundGuardian()
    // Lets the glasses button wake the mic even with the app closed and the
    // phone locked -- press the button, no need to open the phone at all.
    // Permission is requested separately (Dashboard's wake-listener toggle);
    // this call is a no-op on native if RECORD_AUDIO was never granted.
    startWakeListener(nearbyPairingCode)

    const handlePhoneAlert = async (alert) => {
      if (!alert?.alert_id) return
      const processedKey = 'divyadrishti-processed-alert-ids'
      let processed = []
      try {
        processed = JSON.parse(window.localStorage.getItem(processedKey) || '[]')
      } catch {
        processed = []
      }
      if (!Array.isArray(processed)) processed = []

      // Use created_at+id so Pi reboot (alert ids restart at 1) cannot skip fresh photos.
      const alertKey = `${alert.created_at || ''}:${alert.alert_id}`
      const isAutoDescribe = alert.kind === 'auto_describe'
      const isDescribe = alert.kind === 'describe' || alert.kind === 'read' || isAutoDescribe
      const isSnapshotOnly = alert.kind === 'obstacle_snapshot' || alert.speak === false
      const speakText = alert.speak_hi || alert.text_hi || ''
      const historyId = alert.replaces_alert_id
        ? `alert-${alert.replaces_alert_id}`
        : `alert-${alert.alert_id}`
      const incomingImage = isDescribe ? (alert.image_jpeg_b64 || '') : ''
      const existing = loadObstacleHistory().find((row) => row.id === historyId)
      const alreadyProcessed =
        processed.includes(alertKey) || processed.includes(Number(alert.alert_id))
      if (alreadyProcessed) return

      processed = [...processed.filter((v) => v !== Number(alert.alert_id)), alertKey].slice(-80)
      window.localStorage.setItem(processedKey, JSON.stringify(processed))
      window.localStorage.setItem(LAST_PHONE_ALERT_KEY, String(alert.alert_id))

      // Obstacle photos are not sent to the phone — still speak and keep text history.
      if (isSnapshotOnly && !speakText && !existing) return

      // Glasses speech routed to this phone: say it, but keep it out of the photo list.
      const isAnnouncement = alert.kind === 'announcement' || alert.source === 'glasses_voice'
      if (isAnnouncement) {
        await speakAlertOnce(speakText)
        return
      }

      const history = saveObstacleHistoryItem({
        id: historyId,
        created_at: alert.created_at || existing?.created_at || new Date().toISOString(),
        event_type: alert.event_type || (isDescribe ? 'voice_command' : 'obstacle_ahead'),
        direction: alert.direction,
        distance_mm: alert.distance_mm,
        speak_hi: speakText || existing?.speak_hi || '',
        image_jpeg_b64: isDescribe ? (incomingImage || existing?.image_jpeg_b64 || '') : '',
        source: alert.source || alert.kind,
      })
      setObstacleHistory(history)

      // Glasses speaker is unreliable — guide on the phone when the app is open.
      // Speak new obstacles + Read/Gemini; skip silent live photo refreshes (tof_live).
      const isLiveRefresh = alert.source === 'tof_live'
      // Passive/ambient narration only -- the glasses' own beep+vibration
      // still fires regardless (that's motor hardware on the Pi, independent
      // of this phone) -- explicit taps (plain describe/read) still speak
      // even mid-route, since the user asked for those on purpose.
      const isAmbientObstacleNarration =
        alert.speak === true || alert.source === 'tof_snapshot' || alert.kind === 'obstacle' || isAutoDescribe
      const shouldSpeak =
        Boolean(speakText)
        && !isLiveRefresh
        && !(isAmbientObstacleNarration && isNavigatingActive())
        && (
          isDescribe
          || alert.speak === true
          || alert.source === 'tof_snapshot'
          || alert.kind === 'obstacle'
          || alert.kind === 'read'
          || alert.kind === 'describe'
        )
      if (!shouldSpeak) return

      // Avoid repeating the same direction/distance while standing in place.
      const speakBucket = `${alert.direction || 'ahead'}:${Math.round((alert.distance_mm || 0) / 150)}:${speakText}`
      const lastSpeakKey = 'divyadrishti-last-obstacle-speak'
      try {
        const prev = JSON.parse(window.sessionStorage.getItem(lastSpeakKey) || 'null')
        if (
          prev?.bucket === speakBucket
          && Date.now() - (prev?.at || 0) < (isDescribe ? 0 : 8_000)
        ) {
          return
        }
        window.sessionStorage.setItem(lastSpeakKey, JSON.stringify({ bucket: speakBucket, at: Date.now() }))
      } catch {
        // ignore
      }

      // This speech wasn't requested by tapping anything — cue it first so
      // it's clearly the glasses noticing something, not an obstacle alert.
      if (isAutoDescribe) await playAutoDescribeCue()
      await speakAlertOnce(speakText)
      if (device?.pairing_code) {
        await withLocalSocket('unmute_haptics', () => sendNearbyCommand(device.pairing_code, 'unmute_haptics')).catch(() => {})
      }
    }

    // The Pi pushes a fresh status the instant it changes, and pushes each
    // obstacle/describe/read alert separately as it's queued — no polling.
    const onNearbyStatus = (localStatus) => {
      if (!active) return
      setNearbyLink({ state: 'connected', status: localStatus })
      const alerts = Array.isArray(localStatus?.phone_alerts) && localStatus.phone_alerts.length
        ? localStatus.phone_alerts
        : (localStatus?.phone_alert ? [localStatus.phone_alert] : [])
      for (const alert of alerts) {
        handlePhoneAlert(alert)
      }
    }
    const onNearbyAlert = (alert) => {
      if (active) handlePhoneAlert(alert)
    }
    const onNearbyClose = () => {
      if (active) setNearbyLink({ state: 'away', status: null })
    }
    // The Pi has no Gemini key of its own — this phone always runs it, via
    // glassesVision.js. The Pi never speaks either, so this is also the
    // only place that speaks the answer for a button-triggered or ambient
    // (obstacle/auto-describe) request; the phone's own UI/voice-triggered
    // describe/read already gets its text back through the normal
    // command round trip and must not speak it a second time here.
    const onVisionRequest = async (payload) => {
      const result = await describeForGlasses(nearbyPairingCode, payload)
      if (active && result?.text_hi) await speakAlertOnce(result.text_hi)
      return result
    }
    const onWakeRequested = () => {
      if (active) setWakeRequestedAt(Date.now())
    }
    connectLocalSocket(nearbyPairingCode, {
      onStatus: onNearbyStatus,
      onAlert: onNearbyAlert,
      onVisionRequest,
      onWakeRequested,
      onClose: onNearbyClose,
    })
    return () => {
      active = false
      disconnectLocalSocket()
      stopBackgroundGuardian()
      stopWakeListener()
    }
    // Depend on the pairing code, not the device object -- loadDevice's 15s
    // background poll returns a fresh object every time even when nothing
    // changed, which was tearing down and rebuilding this whole socket +
    // GuardianService link every 15s. Harmless in the foreground (each
    // restart gets re-allowed), but the moment the app backgrounds, Android
    // denies the next restart outright and the link never comes back.
  }, [device?.pairing_code, speakAlertOnce])

  const pairDevice = async (pairingCode) => {
    if (isDemoMode) {
      window.localStorage.setItem(PAIRING_CODE_KEY, pairingCode || 'DEMO01')
      return { ...demoDevice, pairing_code: pairingCode || 'DEMO01' }
    }

    const { data, error } = await supabase
      .rpc('claim_device_public', { pairing_code_input: pairingCode })
      .maybeSingle()

    if (error) throw error
    if (!data) throw new Error('That pairing code was not found or is already linked to a device.')

    window.localStorage.setItem(PAIRING_CODE_KEY, pairingCode)
    await loadDevice()
    return data
  }

  /** Fires the same effect a real "wake" command produces (see
   * onWakeRequested above) without a Pi round trip -- used by the in-app
   * floating wake button as its demo-mode/offline fallback so it still
   * responds instantly when the nearby link isn't connected. */
  const triggerWakeLocally = () => setWakeRequestedAt(Date.now())

  const sendNearbyDeviceCommand = async (command) => {
    if (!device?.pairing_code) throw new Error('Pair your glasses before sending a nearby command.')
    const localStatus = await withLocalSocket(command, () => sendNearbyCommand(device.pairing_code, command))
    setNearbyLink({ state: 'connected', status: localStatus })
    return localStatus
  }

  const describeNearbySurroundings = async (mode = 'describe') => {
    const kind = mode === 'read' ? 'read' : 'describe'
    if (isDemoMode) {
      return {
        status: 'ok',
        text_hi: kind === 'read'
          ? 'बोर्ड पर लिखा है EXIT। नीचे लेबल पर Gate 2 लिखा है।'
          : 'सामने कुर्सी है। दाईं ओर एक व्यक्ति खड़ा है।',
        image_jpeg_b64: '',
        source: kind,
        mode: kind,
      }
    }
    if (!device?.pairing_code) throw new Error('Pair your glasses before asking them to look ahead.')
    const result = await withLocalSocket(kind, () => (
      kind === 'read' ? sendNearbyRead(device.pairing_code) : sendNearbyDescribe(device.pairing_code)
    ))
    setNearbyLink((prev) => ({ ...prev, state: 'connected' }))
    if (result?.status === 'ok' && result?.text_hi) {
      const history = saveObstacleHistoryItem({
        id: `${kind}-${Date.now()}`,
        event_type: 'voice_command',
        speak_hi: result.text_hi,
        image_jpeg_b64: result.image_jpeg_b64,
        source: kind,
      })
      setObstacleHistory(history)
    }
    return result
  }

  const value = {
    device, status, events, loading, nearbyLink, dataError, lastRefreshedAt, obstacleHistory, wakeRequestedAt,
    pairDevice, playPreviewScene, sendNearbyDeviceCommand, describeNearbySurroundings, refresh: loadDevice,
    triggerWakeLocally,
  }

  return <DeviceContext.Provider value={value}>{children}</DeviceContext.Provider>
}

export function useDevice() {
  const ctx = useContext(DeviceContext)
  if (ctx === undefined) throw new Error('useDevice must be used within DeviceProvider')
  return ctx
}
