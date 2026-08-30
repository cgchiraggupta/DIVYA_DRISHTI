import { useEffect, useState } from 'react'
import { AlertTriangle, BatteryMedium, Check, ChevronRight, Eye, Footprints, LoaderCircle, Mic, MicOff, Pause, Play, Radio, ScanEye, Sparkles, Type, Volume2, Waves } from 'lucide-react'
import Layout from '../components/Layout'
import Card from '../components/Card'
import StatusPulse from '../components/StatusPulse'
import { useDevice } from '../context/DeviceContext'
import { previewScenes } from '../lib/demoData'
import { alertLabel, formatDistanceMeters, isHazardEvent, timeAgo } from '../lib/format'
import { isDemoMode } from '../lib/supabaseClient'
import { useVoiceCommands } from '../hooks/useVoiceCommands'
import { signalGuidance, speakGuidance } from '../services/sensoryFeedback'

const GEMINI_UNAVAILABLE_KEY = 'divyadrishti-gemini-unavailable'

function safetyState(status) {
  const updatedAt = status?.updated_at
  if (!updatedAt) return 'offline'

  const ageMs = Date.now() - new Date(updatedAt).getTime()
  if (Number.isNaN(ageMs) || ageMs > 60_000) return 'offline'
  if (status.mode !== 'tof' || !status.tof_left_ok || !status.tof_right_ok) return 'degraded'
  if (status.current_alert && isHazardEvent(status.current_alert)) return 'alert'
  return 'online'
}

function statusCopy(status, state, sensingPaused) {
  if (sensingPaused) {
    return {
      title: 'Sensing is paused',
      body: 'Obstacle alerts are off. Resume sensing before you start walking.',
      icon: Pause,
    }
  }

  if (state === 'offline') {
    return {
      title: 'Safety status is delayed',
      body: status?.updated_at
        ? `Last sensor update ${timeAgo(status.updated_at)}. Wear the glasses and check their connection.`
        : 'Waiting for the first sensor update from your glasses.',
      icon: AlertTriangle,
    }
  }

  if (state === 'degraded') {
    return {
      title: 'Obstacle sensing needs attention',
      body: status?.mode === 'camera_fallback'
        ? 'Distance sensing is unavailable. Camera guidance can only help when the camera is connected.'
        : 'The glasses are reporting, but both distance sensors are not ready yet.',
      icon: AlertTriangle,
    }
  }

  const type = status?.current_alert ?? 'path_clear'
  if (type === 'path_clear') {
    return {
      title: 'Path ahead is clear',
      body: 'Your glasses are watching for obstacles.',
      speak_hi: 'रास्ता साफ़ है। चश्मा बाधाओं पर नज़र रख रहा है।',
      icon: Check,
    }
  }
  if (type === 'uneven_ground') {
    return {
      title: 'Uneven ground ahead',
      body: 'Take care with your next step.',
      speak_hi: 'आगे जमीन ऊबड़-खाबड़ है। सावधानी से कदम बढ़ाएँ।',
      icon: Footprints,
    }
  }
  return {
    title: alertLabel(type),
    body: 'Your glasses have shared an update.',
    speak_hi: `${alertLabel(type)}। आपके चश्मे ने अपडेट भेजा है।`,
    icon: Eye,
  }
}

function connectionSubtitle(nearbyLink, state, sensingPaused) {
  if (sensingPaused) return 'Sensing paused on nearby glasses'
  if (nearbyLink.state === 'connected' && state === 'online') return 'Nearby Wi-Fi link · safety status is live'
  if (isDemoMode) return 'Preview mode — try the guidance buttons below'
  if (state === 'offline') return 'Showing last known information, not live sensing'
  if (state === 'degraded') return 'Glasses are reporting, but safety coverage is incomplete'
  return 'Safety sensing is live via the glasses Wi-Fi connection'
}

function capabilityRow(label, value, detail, tone = 'neutral') {
  const toneClass = {
    safe: 'text-safe-400',
    alert: 'text-alert-400',
    signal: 'text-signal-400',
    neutral: 'text-mist-300',
  }[tone]

  return (
    <div className="flex items-start justify-between gap-4 border-b border-night-800 py-3 last:border-0">
      <div>
        <p className="text-sm font-medium text-mist-200">{label}</p>
        <p className="mt-0.5 text-xs leading-5 text-mist-500">{detail}</p>
      </div>
      <span className={`shrink-0 text-sm font-semibold ${toneClass}`}>{value}</span>
    </div>
  )
}

export default function Dashboard() {
  const { device, status, events, loading, nearbyLink, playPreviewScene, sendNearbyDeviceCommand, describeNearbySurroundings, obstacleHistory, wakeRequestedAt } = useDevice()
  const [sensingControl, setSensingControl] = useState({ pending: null, message: '', error: '' })
  const [describeControl, setDescribeControl] = useState({
    pending: null,
    lastMode: 'describe',
    textHi: '',
    imageJpegB64: '',
    message: '',
    error: '',
  })
  const [geminiUnavailable, setGeminiUnavailable] = useState(() => {
    try {
      return window.sessionStorage.getItem(GEMINI_UNAVAILABLE_KEY) === '1'
    } catch {
      return false
    }
  })
  const state = safetyState(status)
  const sensingPaused = nearbyLink.status?.paused === true
  const displayState = sensingPaused ? 'paused' : state
  const copy = statusCopy(status, state, sensingPaused)
  const HeroIcon = copy.icon
  const liveAlert = nearbyLink.status?.phone_alert
  // Prefer phone-local obstacle/read history (has photos). Fall back to live
  // nearby alert, then cloud events (text-only, often without a snapshot).
  const obstacleRows = (obstacleHistory || []).filter((row) =>
    row?.event_type !== 'voice_command'
    && row?.source !== 'describe'
    && row?.source !== 'read',
  )
  // Prefer a row that actually has a snapshot — empty live refreshes used to hide real photos.
  const latestObstacle = obstacleRows.find((row) => row?.image_jpeg_b64 || row?.detail?.image_jpeg_b64)
    || obstacleRows[0]
    || null
  const liveHasPhoto = Boolean(liveAlert?.image_jpeg_b64)
  const latest = (liveHasPhoto ? {
    speak_hi: liveAlert.speak_hi || liveAlert.text_hi,
    created_at: liveAlert.created_at,
    event_type: liveAlert.event_type || 'obstacle_ahead',
    image_jpeg_b64: liveAlert.image_jpeg_b64,
    distance_mm: liveAlert.distance_mm,
    direction: liveAlert.direction,
  } : null)
    || latestObstacle
    || obstacleHistory?.[0]
    || (liveAlert ? {
      speak_hi: liveAlert.speak_hi || liveAlert.text_hi,
      created_at: liveAlert.created_at,
      event_type: liveAlert.event_type || 'obstacle_ahead',
      image_jpeg_b64: liveAlert.image_jpeg_b64,
      distance_mm: liveAlert.distance_mm,
      direction: liveAlert.direction,
    } : null)
    || events?.[0]
  const latestDistanceMm = latest?.distance_mm ?? latest?.detail?.distance_mm
  const sensingLive = !sensingPaused && (state === 'online' || state === 'alert')
  const batteryMissing = status?.battery_pct == null
  const battery = batteryMissing ? '—' : `${Math.round(status.battery_pct)}%`
  const batteryLabel = batteryMissing ? 'Battery · not shared' : 'Battery'
  const nearbyControlAvailable = !isDemoMode && nearbyLink.state === 'connected'
  const commandPending = sensingControl.pending !== null
  const describePending = describeControl.pending

  const toggleSensing = async () => {
    if (!nearbyControlAvailable || commandPending) return

    const command = sensingPaused ? 'resume' : 'pause'
    const expectedPaused = command === 'pause'
    setSensingControl({ pending: command, message: '', error: '' })

    try {
      const confirmedStatus = await sendNearbyDeviceCommand(command)
      if (confirmedStatus?.paused !== expectedPaused) {
        throw new Error('The glasses did not confirm the requested sensing state.')
      }
      setSensingControl({
        pending: null,
        message: expectedPaused ? 'Sensing paused on glasses.' : 'Sensing resumed on glasses.',
        error: '',
      })
    } catch {
      setSensingControl({
        pending: null,
        message: '',
        error: 'Could not reach nearby glasses. Put this phone and the glasses on the same Wi-Fi, then try again.',
      })
    }
  }

  const markGeminiUnavailable = () => {
    setGeminiUnavailable(true)
    try {
      window.sessionStorage.setItem(GEMINI_UNAVAILABLE_KEY, '1')
    } catch {
      // ignore
    }
  }

  const runVision = async (mode) => {
    if (describePending) return
    const kind = mode === 'read' ? 'read' : 'describe'

    setDescribeControl({
      pending: kind,
      lastMode: kind,
      textHi: '',
      imageJpegB64: '',
      message: '',
      error: '',
    })

    try {
      const result = await describeNearbySurroundings(kind)
      if (result?.status === 'cooldown') {
        const wait = result.retry_after_seconds ?? 8
        setDescribeControl({
          pending: null,
          lastMode: kind,
          textHi: '',
          imageJpegB64: '',
          message: '',
          error: `Thoda wait karein — ${wait} seconds mein phir try karein.`,
        })
        return
      }

      const geminiError = String(result?.error || '')
      const geminiBlocked = /429|401|403|quota|billing|unauth/i.test(geminiError)
      if (result?.status === 'error' && (geminiBlocked || !result?.text_hi?.trim())) {
        if (geminiBlocked) markGeminiUnavailable()
        setDescribeControl({
          pending: null,
          lastMode: kind,
          textHi: '',
          imageJpegB64: result?.image_jpeg_b64 || '',
          message: '',
          error: geminiBlocked
            ? `${kind === 'read' ? 'Read' : 'Describe'} failed: Gemini key/quota. Put the new billed key on the glasses, then try again.`
            : (geminiError || `${kind === 'read' ? 'Read' : 'Describe'} failed on the glasses.`),
        })
        return
      }

      const textHi = result?.text_hi?.trim() || ''
      if (!textHi) throw new Error(result?.error || 'No description returned.')

      // Already spoken: the Pi has no speaker of its own, so it asks this
      // same phone to run Gemini (DeviceContext's onVisionRequest handler),
      // which speaks the answer the moment it gets it — before this
      // command round trip even resolves. Speaking it again here would
      // duplicate it.
      if (isDemoMode) await speakGuidance(textHi)
      if (!isDemoMode) {
        try {
          await sendNearbyDeviceCommand('unmute_haptics')
        } catch {
          // unmute is best-effort; Pi also auto-unmutes after 20s
        }
      }
      setDescribeControl({
        pending: null,
        lastMode: kind,
        textHi,
        imageJpegB64: result?.image_jpeg_b64 || '',
        message: isDemoMode
          ? (kind === 'read' ? 'Demo sign text ready.' : 'Demo description ready.')
          : result?.status === 'ok'
            ? (kind === 'read' ? 'Read ready — spoken on this phone.' : 'Describe ready — spoken on this phone.')
            : 'Finished with a fallback message.',
        error: '',
      })
    } catch (error) {
      setDescribeControl({
        pending: null,
        lastMode: kind,
        textHi: '',
        imageJpegB64: '',
        message: '',
        error: error?.message?.includes('Glasses') || error?.message?.includes('reach')
          ? 'Could not reach glasses. Same Wi-Fi chahiye phone aur glasses ka.'
          : 'अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।',
      })
    }
  }

  const getDistanceMm = () => (
    liveAlert?.distance_mm
    ?? latestDistanceMm
    ?? nearbyLink.status?.phone_alert?.distance_mm
    ?? null
  )

  const pairingCode = isDemoMode ? import.meta.env.VITE_LOCAL_PAIRING_CODE : device?.pairing_code

  const voice = useVoiceCommands({
    runVision,
    sendNearbyDeviceCommand,
    nearbyControlAvailable,
    getDistanceMm,
    describePending,
    commandPending,
    pairingCode,
  })

  // The Pi has no mic of its own — a single button click asks this phone to
  // start listening, the same as tapping the listen button (wakeRequestedAt
  // starts at 0, so the initial mount is a no-op here).
  useEffect(() => {
    if (wakeRequestedAt) voice.listenOnce()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wakeRequestedAt])

  if (loading) return <Layout title="Divya Drishti"><p className="text-mist-400 text-sm">Getting your device ready…</p></Layout>

  return (
    <Layout
      title="Divya Drishti"
      subtitle={connectionSubtitle(nearbyLink, state, sensingPaused)}
      action={<StatusPulse state={displayState} />}
    >
      <div className="space-y-4">
        {isDemoMode && (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-night-800 px-3 py-1 text-xs font-medium text-mist-300">
            <Sparkles size={13} className="text-signal-400" /> Preview experience · Indian voice
          </div>
        )}

        <section className={`overflow-hidden rounded-3xl border p-5 ${displayState === 'alert' ? 'border-signal-500/50 bg-signal-500/10' : displayState === 'online' ? 'border-safe-500/30 bg-safe-500/10' : 'border-alert-500/40 bg-alert-500/10'}`}>
          <div className="flex items-start gap-4">
            <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ${displayState === 'alert' ? 'bg-signal-500 text-night-950' : displayState === 'online' ? 'bg-safe-500 text-night-950' : 'bg-alert-500 text-night-950'}`}>
              <HeroIcon size={24} strokeWidth={2.5} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist-400">Live guidance</p>
              <h2 className="mt-1 font-display text-2xl font-semibold tracking-tight text-mist-100">{copy.title}</h2>
              <p className="mt-1 text-sm leading-6 text-mist-300">{copy.body}</p>
            </div>
          </div>
          {(state === 'online' || state === 'alert') && <button onClick={() => speakGuidance(copy.speak_hi || `${copy.title}. ${copy.body}`)} className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-signal-300">
            <Volume2 size={16} /> Hear this update
          </button>}
        </section>

        {!isDemoMode && (
          <Card title="Sensing control" eyebrow="Nearby glasses">
            <div className={`rounded-2xl border p-4 ${sensingPaused ? 'border-alert-500/50 bg-alert-500/10' : 'border-safe-500/30 bg-safe-500/10'}`}>
              <div className="flex items-start gap-3">
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${sensingPaused ? 'bg-alert-500 text-night-950' : 'bg-safe-500 text-night-950'}`}>
                  {sensingPaused ? <Pause size={20} strokeWidth={2.5} /> : <Play size={20} strokeWidth={2.5} />}
                </span>
                <div>
                  <p className="text-sm font-semibold text-mist-100">{sensingPaused ? 'Sensing is paused' : 'Sensing is active'}</p>
                  <p className="mt-1 text-xs leading-5 text-mist-400">
                    {sensingPaused
                      ? 'Obstacle alerts are off. Resume before you start walking.'
                      : 'Pause alerts while you are sitting or talking to someone.'}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={toggleSensing}
                disabled={!nearbyControlAvailable || commandPending}
                className={`mt-4 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 ${sensingPaused ? 'bg-safe-500 text-night-950' : 'bg-signal-500 text-night-950'}`}
              >
                {commandPending
                  ? <><LoaderCircle className="animate-spin" size={17} /> Sending to glasses…</>
                  : sensingPaused
                    ? <><Play size={17} /> Resume sensing</>
                    : <><Pause size={17} /> Pause sensing</>}
              </button>

              <p className="mt-3 text-xs leading-5 text-mist-500" role={sensingControl.error ? 'alert' : 'status'} aria-live="polite">
                {sensingControl.error || sensingControl.message || (nearbyControlAvailable
                  ? 'The glasses confirm each change before this screen updates.'
                  : 'Connect this phone and the glasses to the same Wi-Fi to use this control.')}
              </p>
            </div>
          </Card>
        )}

        <Card title="Voice commands" eyebrow="Phone mic · Google speech · glasses still do the work">
          <p className="text-sm leading-6 text-mist-400">
            Mic and speaker are this phone until the glasses hardware is ready. Double-tap on the glasses still Describes. Say Hey Divya, then a command — or tap Listen.
          </p>
          <button
            type="button"
            onClick={voice.listenOnce}
            disabled={voice.listening || voice.busy || !!describePending}
            className={`mt-4 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50 ${voice.listening ? 'bg-alert-500 text-night-950' : 'bg-signal-500 text-night-950'}`}
          >
            {voice.listening
              ? <><LoaderCircle className="animate-spin" size={17} /> Listening…</>
              : <><Mic size={17} /> Listen</>}
          </button>
          <button
            type="button"
            onClick={voice.toggleHandsFree}
            className={`mt-2 flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-3 text-sm font-bold transition active:scale-[0.99] ${voice.handsFree ? 'border-signal-500/60 bg-signal-500/10 text-signal-300' : 'border-night-600 bg-night-800 text-mist-100'}`}
          >
            {voice.handsFree
              ? <><MicOff size={17} /> Stop hands-free</>
              : <><Mic size={17} /> Keep listening for Hey Divya</>}
          </button>
          <p className="mt-3 text-xs leading-5 text-mist-500" role={voice.status.error ? 'alert' : 'status'} aria-live="polite">
            {voice.status.error
              || voice.status.message
              || 'Try: what’s ahead · पढ़ो · कितनी दूर · रुक जाओ · शुरू करो · मदद'}
          </p>
          {voice.status.transcript && (
            <p className="mt-2 text-xs leading-5 text-mist-400">Heard: {voice.status.transcript}</p>
          )}
        </Card>

        <Card title="What’s in front" eyebrow="Camera · objects or sign text · phone speaker">
          {geminiUnavailable && (
            <p
              className="mb-3 rounded-xl border border-alert-500/40 bg-alert-500/10 px-3 py-2 text-xs leading-5 text-alert-300"
              role="status"
            >
              Gemini unavailable. Describe and Read may fail until the new API key works — obstacle distance + photos still work.
            </p>
          )}
          <p className="text-sm leading-6 text-mist-400">
            Describe names people and objects. Read speaks only printed text. Double-tap on the glasses is Describe. Phone speaks Hindi; distances stay like 80 cm.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => runVision('describe')}
              disabled={!!describePending}
              className="flex items-center justify-center gap-2 rounded-xl bg-signal-500 px-3 py-3 text-sm font-bold text-night-950 transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {describePending === 'describe'
                ? <><LoaderCircle className="animate-spin" size={17} /> Describing…</>
                : <><ScanEye size={17} /> Describe</>}
            </button>
            <button
              type="button"
              onClick={() => runVision('read')}
              disabled={!!describePending}
              className="flex items-center justify-center gap-2 rounded-xl border border-night-600 bg-night-800 px-3 py-3 text-sm font-bold text-mist-100 transition active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {describePending === 'read'
                ? <><LoaderCircle className="animate-spin" size={17} /> Reading…</>
                : <><Type size={17} /> Read</>}
            </button>
          </div>
          <p className="mt-3 text-xs leading-5 text-mist-500" role={describeControl.error ? 'alert' : 'status'} aria-live="polite">
            {describeControl.error
              || describeControl.message
              || (isDemoMode
                ? 'Preview mode will speak a sample Hindi line on this phone.'
                : 'Same Wi-Fi as the glasses. Point at a sign before Read.')}
          </p>
          {describeControl.textHi && (
            <div className="mt-4 rounded-2xl border border-night-700 bg-night-900/60 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-mist-500">
                {describeControl.lastMode === 'read' ? 'Sign text' : 'Description'}
              </p>
              <p className="mt-2 text-sm leading-6 text-mist-100">{describeControl.textHi}</p>
              <button
                type="button"
                onClick={() => speakGuidance(describeControl.textHi)}
                className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-signal-300"
              >
                <Volume2 size={16} /> Hear again
              </button>
            </div>
          )}
          {describeControl.imageJpegB64 && (
            <img
              alt="Latest capture from the glasses camera"
              src={`data:image/jpeg;base64,${describeControl.imageJpegB64}`}
              className="mt-4 w-full rounded-2xl border border-night-700 object-cover"
            />
          )}
        </Card>

        <Card title="Safety layers" eyebrow={sensingLive ? `Obstacle sensing · updated ${timeAgo(status?.updated_at)}` : 'Current capability status'}>
          {capabilityRow(
            'Obstacle sensing',
            sensingLive ? 'Live' : state === 'offline' ? 'Delayed' : 'Needs attention',
            sensingLive ? 'Dual distance sensors are reporting obstacle guidance.' : 'This status needs a fresh update before it can be trusted.',
            sensingLive ? 'safe' : 'alert'
          )}
          {capabilityRow(
            'Camera describe and OCR',
            status?.camera_ok ? 'Available' : 'Unavailable',
            status?.camera_ok ? 'Describe names what is in front. Read speaks visible sign text.' : 'Obstacle sensing can continue without the camera.',
            status?.camera_ok ? 'safe' : 'neutral'
          )}
          {capabilityRow(
            'Audio and haptics',
            'Phone stand-in',
            'Mic and speaker are this phone. Glasses I²S will take over when hardware is ready. Double-tap still Describes.',
            'signal'
          )}
        </Card>

        <Card title="Your glasses" eyebrow={nearbyLink.state === 'connected' ? 'Nearby Wi-Fi connection' : isDemoMode ? 'Preview connection' : 'Cloud link'}>
          {nearbyLink.state !== 'connected' && !isDemoMode && (
            <p className="mb-3 rounded-xl border border-alert-500/40 bg-alert-500/10 px-3 py-2 text-xs leading-5 text-alert-300" role="status">
              Phone is not linked to glasses on Wi-Fi right now — photos cannot arrive. Keep both on the same Wi-Fi (glasses are at 192.168.1.39), reopen the app, then stand in front again.
            </p>
          )}
          <div className="grid grid-cols-3 divide-x divide-night-700">
            <div className="pr-3"><BatteryMedium size={19} className="mb-2 text-signal-400" /><p className="font-data text-sm text-mist-100">{battery}</p><p className="mt-0.5 text-xs text-mist-500">{batteryLabel}</p></div>
            <div className="px-3"><Radio size={19} className="mb-2 text-safe-400" /><p className="text-lg font-semibold text-mist-100">{nearbyLink.state === 'connected' ? 'Nearby' : state === 'offline' ? 'Delayed' : sensingLive ? 'Live' : 'Check'}</p><p className="mt-0.5 text-xs text-mist-500">Safety link</p></div>
            <div className="pl-3"><Eye size={19} className="mb-2 text-signal-400" /><p className="text-lg font-semibold text-mist-100">{sensingLive ? 'ToF' : status?.mode === 'camera_fallback' ? 'Camera' : 'Waiting'}</p><p className="mt-0.5 text-xs text-mist-500">Guidance</p></div>
          </div>
        </Card>

        <Card title="Latest update" eyebrow="Recent activity" action={<ChevronRight size={18} className="text-mist-500" />}>
          {!nearbyControlAvailable && !isDemoMode && (
            <p className="mb-3 rounded-xl border border-alert-500/40 bg-alert-500/10 px-3 py-2 text-xs leading-5 text-alert-300" role="status">
              Glasses buzz can still work offline, but photos only reach this phone on the same Wi‑Fi. Reconnect nearby to fill Recent activity.
            </p>
          )}
          <p className="text-sm font-medium text-mist-200">
            {latest
              ? (latest.speak_hi || latest.detail?.speak_hi || alertLabel(latest.event_type))
              : 'No recent obstacle yet'}
          </p>
          <p className="mt-1 text-sm text-mist-500">
            {latest
              ? [
                  timeAgo(latest.created_at),
                  latestDistanceMm != null ? formatDistanceMeters(latestDistanceMm) : null,
                  latest.direction || latest.detail?.direction || null,
                  'History → Obstacles',
                ].filter(Boolean).join(' · ')
              : nearbyControlAvailable
                ? 'When ToF buzzes within your Settings range, Hindi guidance speaks on this phone — even if the screen is off.'
                : 'Connect nearby Wi‑Fi, then walk toward something inside your Settings range.'}
          </p>
        </Card>

        {isDemoMode && (
          <Card title="Feel the guidance" eyebrow="Live preview">
            <p className="mb-4 text-sm leading-6 text-mist-400">Every preview speaks in an Indian voice and vibrates your phone, like the glasses will do in use.</p>
            <button
              onClick={() => signalGuidance({ text: 'सामने कुर्सी है। लगभग 60 cm।', isHazard: true })}
              className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl bg-signal-500 px-4 py-3 text-sm font-bold text-night-950 active:scale-[0.99]"
            >
              <Waves size={17} /> Test obstacle alert
            </button>
            <div className="grid grid-cols-2 gap-2">
              {previewScenes.map((scene) => (
                <button key={scene.id} onClick={() => playPreviewScene(scene)} className="rounded-xl border border-night-700 bg-night-800 px-3 py-3 text-left text-sm font-medium text-mist-200 transition hover:border-signal-500/50 hover:bg-night-700 active:scale-[0.98]">
                  <span className="block">{scene.label}</span>
                  <span className="mt-1 block text-xs font-normal text-mist-500">Voice + vibration</span>
                </button>
              ))}
            </div>
          </Card>
        )}
      </div>
    </Layout>
  )
}
