import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Clock3, Ruler, Vibrate, Volume2, Wifi } from 'lucide-react'
import Layout from '../components/Layout'
import Card from '../components/Card'
import Button from '../components/Button'
import { supabase, isDemoMode } from '../lib/supabaseClient'
import { useDevice } from '../context/DeviceContext'
import { formatDistanceMeters, timeAgo } from '../lib/format'
import { signalGuidance, tapFeedback } from '../services/sensoryFeedback'
import { sendNearbySettings } from '../services/localDeviceLink'

const FEEDBACK_MODES = [
  { id: 'audio', label: 'Audio only' },
  { id: 'vibration', label: 'Vibration only' },
  { id: 'both', label: 'Both' },
]

const DEFAULTS = {
  sensitivity_mm: 2000,
  feedback_mode: 'both',
  volume: 70,
  vibration_intensity: 70,
  revision: 0,
  applied_at: null,
  last_request_id: null,
}
const SETTING_KEYS = ['sensitivity_mm', 'feedback_mode', 'volume', 'vibration_intensity']
const DEMO_SETTINGS_KEY = 'divya-drishti-demo-settings'

function clamp(value, minimum, maximum, fallback) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.min(maximum, Math.max(minimum, Math.round(numeric)))
}

function normalizeSettings(values, fallback = DEFAULTS) {
  const source = values ?? {}
  return {
    ...fallback,
    sensitivity_mm: clamp(source.sensitivity_mm, 1000, 2500, fallback.sensitivity_mm),
    feedback_mode: FEEDBACK_MODES.some((mode) => mode.id === source.feedback_mode)
      ? source.feedback_mode
      : fallback.feedback_mode,
    volume: clamp(source.volume, 20, 100, fallback.volume),
    vibration_intensity: clamp(source.vibration_intensity, 40, 100, fallback.vibration_intensity),
    revision: Number.isFinite(Number(source.revision)) ? Number(source.revision) : fallback.revision,
    applied_at: source.applied_at ?? fallback.applied_at,
    last_request_id: source.last_request_id ?? fallback.last_request_id,
  }
}

function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()

  const bytes = new Uint8Array(16)
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function getInitialSettings() {
  if (!isDemoMode) return { ...DEFAULTS }
  try {
    const saved = window.localStorage.getItem(DEMO_SETTINGS_KEY)
    return saved ? normalizeSettings(JSON.parse(saved)) : { ...DEFAULTS }
  } catch {
    return { ...DEFAULTS }
  }
}

function valuesFromRequest(request, prior = DEFAULTS) {
  const values = normalizeSettings(request, prior)
  return {
    ...values,
    revision: request?.applied_revision ?? prior.revision,
    applied_at: request?.applied_at ?? prior.applied_at,
    last_request_id: request?.id ?? prior.last_request_id,
  }
}

function isPending(request) {
  return ['queued', 'received', 'applying'].includes(request?.state)
}

function compareRequests(left, right) {
  if (!left) return -1
  if (!right) return 1
  if (left.id === right.id) return 0
  const leftTime = Date.parse(left.requested_at ?? '') || 0
  const rightTime = Date.parse(right.requested_at ?? '') || 0
  if (leftTime !== rightTime) return leftTime - rightTime
  return String(left.id).localeCompare(String(right.id))
}

function newestRequest(current, incoming) {
  if (!incoming) return current
  if (!current || incoming.id === current.id || compareRequests(incoming, current) > 0) return incoming
  return current
}

function sameSettingValues(left, right) {
  return SETTING_KEYS.every((key) => left[key] === right[key])
}

function isFresh(updatedAt) {
  const time = Date.parse(updatedAt ?? '')
  return Number.isFinite(time) && Date.now() - time < 60_000
}

function RequestStatus({ request, hasConfirmedSettings }) {
  if (!request) {
    return (
      <p className="text-sm leading-6 text-mist-400">
        {hasConfirmedSettings
          ? 'No change is waiting for the glasses.'
          : 'No setting has been confirmed by the glasses yet.'}
      </p>
    )
  }

  if (request.state === 'applied') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-2 rounded-xl border border-safe-500/30 bg-safe-500/10 px-3 py-3 text-sm leading-6 text-safe-400"
      >
        <CheckCircle2 className="mt-0.5 shrink-0" size={17} />
        <span>Applied on glasses {request.applied_at ? timeAgo(request.applied_at) : 'just now'}.</span>
      </div>
    )
  }

  if (isPending(request)) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-start gap-2 rounded-xl border border-signal-500/30 bg-signal-500/10 px-3 py-3 text-sm leading-6 text-signal-300"
      >
        <Clock3 className="mt-0.5 shrink-0" size={17} />
        <span>
          {request.state === 'queued'
            ? 'Waiting for the glasses to receive this change.'
            : 'Glasses received the change and are applying it.'}
        </span>
      </div>
    )
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-start gap-2 rounded-xl border border-alert-500/30 bg-alert-500/10 px-3 py-3 text-sm leading-6 text-alert-400"
    >
      <AlertTriangle className="mt-0.5 shrink-0" size={17} />
      <span>Not applied{request.error_message ? `: ${request.error_message}` : '. The glasses kept their previous settings.'}</span>
    </div>
  )
}

export default function Settings() {
  const { device, status, nearbyLink } = useDevice()
  const deviceId = device?.id
  const [appliedSettings, setAppliedSettings] = useState(getInitialSettings)
  const [draft, setDraft] = useState(getInitialSettings)
  const [hasConfirmedSettings, setHasConfirmedSettings] = useState(isDemoMode)
  const [latestRequest, setLatestRequest] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [retryableSubmission, setRetryableSubmission] = useState(null)
  const [error, setError] = useState('')
  const [nearbyApplyMessage, setNearbyApplyMessage] = useState('')

  const latestRequestRef = useRef(null)
  const draftDirtyRef = useRef(false)
  const initializedRef = useRef(false)
  const submissionRef = useRef(null)

  const pending = isPending(latestRequest)
  const hasChanges = useMemo(
    () => !sameSettingValues(draft, appliedSettings),
    [draft, appliedSettings]
  )
  const needsApply = !hasConfirmedSettings || hasChanges
  const statusFresh = isFresh(status?.updated_at)
  const detectionRangeMeters = draft.sensitivity_mm / 1000
  const nearbyConnected = !isDemoMode && nearbyLink.state === 'connected'
  const glassesSettings = nearbyLink.status?.settings
    ? normalizeSettings(nearbyLink.status.settings, appliedSettings)
    : null
  const glassesMatchDraft = glassesSettings
    ? sameSettingValues(draft, glassesSettings)
    : false

  const mergeLatestRequest = (incoming) => {
    const next = newestRequest(latestRequestRef.current, incoming)
    latestRequestRef.current = next
    setLatestRequest(next)
    return next
  }

  const acceptAppliedRequest = useCallback((request, shouldUpdateDraft) => {
    if (request?.state !== 'applied') return
    const confirmed = valuesFromRequest(request)
    setAppliedSettings((previous) => valuesFromRequest(request, previous))
    setHasConfirmedSettings(true)
    if (shouldUpdateDraft && !draftDirtyRef.current) {
      setDraft(confirmed)
    }
  }, [])

  useEffect(() => {
    if (!deviceId || isDemoMode) return undefined

    let active = true
    let initialLoad = true
    draftDirtyRef.current = false
    initializedRef.current = false
    latestRequestRef.current = null
    submissionRef.current = null
    setLatestRequest(null)
    setRetryableSubmission(null)
    setError('')

    const applyAuthoritativeRows = (settingsRow, requestRow) => {
      const confirmed = settingsRow?.applied_at ? normalizeSettings(settingsRow) : null
      const latest = mergeLatestRequest(requestRow)

      if (confirmed) {
        setAppliedSettings(confirmed)
        setHasConfirmedSettings(true)
      } else {
        setAppliedSettings({ ...DEFAULTS })
        setHasConfirmedSettings(false)
      }

      if (!initializedRef.current || !draftDirtyRef.current) {
        const pendingValues = isPending(latest) ? valuesFromRequest(latest, confirmed ?? DEFAULTS) : null
        const prefilled = pendingValues ?? confirmed ?? normalizeSettings(settingsRow, DEFAULTS)
        setDraft(prefilled)
        initializedRef.current = true
      }
    }

    const refreshSettings = async () => {
      if (initialLoad) setLoading(true)
      try {
        const [{ data: settingsRow, error: settingsError }, { data: requestRows, error: requestError }] = await Promise.all([
          supabase.from('device_settings').select('*').eq('device_id', deviceId).maybeSingle(),
          supabase
            .from('device_setting_requests')
            .select('*')
            .eq('device_id', deviceId)
            .order('requested_at', { ascending: false })
            .limit(1),
        ])

        if (settingsError) throw settingsError
        if (requestError) throw requestError
        if (!active) return

        applyAuthoritativeRows(settingsRow, requestRows?.[0] ?? null)
        setError('')
      } catch {
        if (active) setError('Settings could not be refreshed. The glasses have not been changed.')
      } finally {
        if (active && initialLoad) setLoading(false)
        initialLoad = false
      }
    }

    const handleRequestUpdate = (payload) => {
      const request = payload.new
      if (!active || !request || request.device_id !== deviceId) return

      const previousLatest = latestRequestRef.current
      const latest = mergeLatestRequest(request)
      const isCurrentRequest = latest?.id === request.id

      if (request.state === 'applied') {
        acceptAppliedRequest(request, isCurrentRequest && (!previousLatest || previousLatest.id === request.id))
      }

      if (submissionRef.current?.id === request.client_request_id && !isPending(request)) {
        submissionRef.current = null
        setRetryableSubmission(null)
      }
    }

    // Subscribe first, then fetch the authoritative rows so a quick Pi
    // acknowledgement cannot be missed between the two operations.
    const channel = supabase
      .channel(`device-settings-${deviceId}`)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'device_setting_requests', filter: `device_id=eq.${deviceId}` },
        handleRequestUpdate
      )
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'device_setting_requests', filter: `device_id=eq.${deviceId}` },
        handleRequestUpdate
      )
      .subscribe()

    refreshSettings()
    const interval = window.setInterval(refreshSettings, 12_000)
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') refreshSettings()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      active = false
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      supabase.removeChannel(channel)
    }
  }, [deviceId, acceptAppliedRequest])

  const update = (patch) => {
    draftDirtyRef.current = true
    setDraft((previous) => ({ ...previous, ...patch }))
  }

  const save = async () => {
    if (!device || saving || pending || !needsApply) return
    setSaving(true)
    setError('')
    setNearbyApplyMessage('')

    if (isDemoMode) {
      const request = {
        ...draft,
        id: newRequestId(),
        client_request_id: newRequestId(),
        requested_at: new Date().toISOString(),
        state: 'applied',
        applied_revision: appliedSettings.revision + 1,
        applied_at: new Date().toISOString(),
      }
      window.localStorage.setItem(DEMO_SETTINGS_KEY, JSON.stringify(valuesFromRequest(request)))
      mergeLatestRequest(request)
      draftDirtyRef.current = false
      acceptAppliedRequest(request, true)
      setSaving(false)
      return
    }

    let submission = submissionRef.current
    const baseRevision = appliedSettings.revision ?? 0
    if (!submission || !sameSettingValues(submission.values, draft) || submission.baseRevision !== baseRevision) {
      submission = {
        id: newRequestId(),
        values: { ...draft },
        baseRevision,
      }
      submissionRef.current = submission
      setRetryableSubmission(submission)
    }

    try {
      const { data, error: requestError } = await supabase
        .rpc('request_device_settings', {
          pairing_code_input: device.pairing_code,
          client_request_id_input: submission.id,
          sensitivity_mm_input: submission.values.sensitivity_mm,
          feedback_mode_input: submission.values.feedback_mode,
          volume_input: submission.values.volume,
          vibration_intensity_input: submission.values.vibration_intensity,
          base_revision_input: submission.baseRevision,
        })
        .maybeSingle()

      if (requestError || !data) {
        throw requestError ?? new Error('The change was not accepted by the cloud.')
      }

      const latest = mergeLatestRequest(data)
      draftDirtyRef.current = false

      // Dual path: push to nearby glasses immediately when on the same Wi-Fi.
      if (nearbyConnected) {
        try {
          const nearby = await sendNearbySettings(device.pairing_code, {
            ...submission.values,
            request_id: data.id,
          })
          const live = nearby?.settings ? normalizeSettings(nearby.settings) : null
          if (live) {
            setAppliedSettings({
              ...live,
              revision: appliedSettings.revision,
              applied_at: nearby.updated_at || new Date().toISOString(),
              last_request_id: data.id,
            })
            setHasConfirmedSettings(true)
            setNearbyApplyMessage(
              `Glasses updated now: detection ${formatDistanceMeters(live.sensitivity_mm)}.`,
            )
          } else {
            setNearbyApplyMessage('Glasses received the change over Wi-Fi.')
          }
        } catch {
          setNearbyApplyMessage(
            'Cloud queued the change, but nearby Wi-Fi push failed. Glasses will pick it up within a few seconds if online.',
          )
        }
      } else {
        setNearbyApplyMessage(
          'Change queued in the cloud. Glasses will apply it when they are online (keep phone and glasses on the same Wi-Fi for instant apply).',
        )
      }

      if (data.state === 'applied') acceptAppliedRequest(data, latest?.id === data.id)
      if (!isPending(data)) {
        submissionRef.current = null
        setRetryableSubmission(null)
      }
    } catch (requestError) {
      setError(requestError?.message ?? 'The change was not sent. Retry uses the same safe request ID.')
      setNearbyApplyMessage('')
    } finally {
      setSaving(false)
    }
  }

  const controlsDisabled = loading || saving || pending || !device
  const primaryLabel = saving
    ? 'Sending to glasses…'
    : pending && !nearbyApplyMessage
      ? 'Waiting for glasses…'
      : retryableSubmission
        ? 'Retry sending change'
        : !hasConfirmedSettings
          ? 'Set defaults on glasses'
          : hasChanges
            ? nearbyConnected
              ? 'Apply to glasses now'
              : 'Apply to glasses'
            : 'Applied settings are current'

  return (
    <Layout title="Settings" subtitle="Apply sends to the glasses — slider alone does not change hardware">
      <div className="space-y-4">
        <Card eyebrow="Glasses confirmation" title="Current device setting">
          <RequestStatus request={latestRequest} hasConfirmedSettings={hasConfirmedSettings} />
          {glassesSettings && (
            <p className="mt-3 rounded-xl border border-night-700 bg-night-800 px-3 py-2 text-sm leading-6 text-mist-200">
              On glasses now:{' '}
              <span className="font-data text-signal-300">
                {formatDistanceMeters(glassesSettings.sensitivity_mm)}
              </span>
              {' · '}
              {glassesSettings.feedback_mode}
              {glassesMatchDraft ? ' · matches your selection' : ' · differs from slider below'}
            </p>
          )}
          {!glassesSettings && !isDemoMode && (
            <p className="mt-3 text-xs leading-5 text-mist-500">
              Nearby Wi-Fi not linked — live glasses range unavailable. Last cloud-confirmed:{' '}
              {formatDistanceMeters(appliedSettings.sensitivity_mm)}.
            </p>
          )}
          {appliedSettings.applied_at && (
            <p className="mt-2 text-xs text-mist-500">Last confirmed setting: {timeAgo(appliedSettings.applied_at)}</p>
          )}
          {nearbyApplyMessage && (
            <p className="mt-2 text-xs leading-5 text-safe-300">{nearbyApplyMessage}</p>
          )}
          {pending && !statusFresh && (
            <p className="mt-2 text-xs leading-5 text-alert-400">No recent safety update from the glasses. This request will wait until they reconnect.</p>
          )}
        </Card>

        <Card eyebrow="Audio" title="Mic and speaker">
          <p className="text-sm leading-6 text-mist-300">
            Voice commands and spoken alerts use this phone until the glasses mic and speaker are working. Commands still run on the glasses.
          </p>
        </Card>

        <Card eyebrow="Detection" title="Detection range">
          <div className="mb-2 flex items-center gap-3">
            <Ruler size={18} className="text-signal-400" />
            <span className="font-data text-sm text-mist-200">{formatDistanceMeters(draft.sensitivity_mm)}</span>
            <span className="text-xs text-mist-500">selected</span>
          </div>
          <input
            type="range"
            min="1"
            max="2.5"
            step="0.5"
            value={detectionRangeMeters}
            onChange={(event) => {
              setNearbyApplyMessage('')
              update({ sensitivity_mm: Math.round(Number(event.target.value) * 1000) })
            }}
            onPointerUp={tapFeedback}
            aria-valuetext={formatDistanceMeters(draft.sensitivity_mm)}
            disabled={controlsDisabled}
            className="w-full accent-signal-500 disabled:opacity-50"
          />
          <p className="mt-2 text-xs leading-5 text-mist-500">
            Early-warning range for ToF. Press Apply to push this to the glasses
            {nearbyConnected ? ' (instant over Wi-Fi + cloud confirm).' : ' (cloud queue until glasses are online).'}
          </p>
        </Card>

        <Card eyebrow="Feedback" title="Alert mode">
          <div className="grid grid-cols-3 gap-2">
            {FEEDBACK_MODES.map((mode) => (
              <button
                key={mode.id}
                onClick={() => {
                  if (controlsDisabled) return
                  update({ feedback_mode: mode.id })
                  tapFeedback()
                }}
                disabled={controlsDisabled}
                aria-pressed={draft.feedback_mode === mode.id}
                className={`rounded-xl border py-2.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                  draft.feedback_mode === mode.id
                    ? 'border-signal-500 bg-signal-500/15 text-signal-400'
                    : 'border-night-700 bg-night-800 text-mist-300 hover:border-night-600'
                }`}
              >
                {mode.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-mist-500">Audio and vibration changes affect future alerts only.</p>
          <button
            onClick={() => signalGuidance({
              text: 'Obstacle ahead. This is a phone-only preview of your alert setting.',
              isHazard: true,
              audio: draft.feedback_mode !== 'vibration',
              vibration: draft.feedback_mode !== 'audio',
              audioVolume: draft.volume / 100,
              vibrationDuration: 120 + draft.vibration_intensity * 4,
            })}
            className="mt-4 text-sm font-semibold text-signal-300"
          >
            Test on this phone
          </button>
        </Card>

        <Card eyebrow="Audio" title="Volume">
          <div className="flex items-center gap-3">
            <Volume2 size={18} className="text-signal-400" />
            <input
              type="range"
              min="20"
              max="100"
              value={draft.volume}
              onChange={(event) => update({ volume: Number(event.target.value) })}
              onPointerUp={tapFeedback}
              disabled={controlsDisabled}
              className="flex-1 accent-signal-500 disabled:opacity-50"
            />
            <span className="w-10 text-right font-data text-sm text-mist-200">{draft.volume}%</span>
          </div>
        </Card>

        <Card eyebrow="Haptics" title="Vibration intensity">
          <div className="flex items-center gap-3">
            <Vibrate size={18} className="text-signal-400" />
            <input
              type="range"
              min="40"
              max="100"
              value={draft.vibration_intensity}
              onChange={(event) => update({ vibration_intensity: Number(event.target.value) })}
              onPointerUp={tapFeedback}
              disabled={controlsDisabled}
              className="flex-1 accent-signal-500 disabled:opacity-50"
            />
            <span className="w-10 text-right font-data text-sm text-mist-200">{draft.vibration_intensity}%</span>
          </div>
          <p className="mt-2 text-xs leading-5 text-mist-500">
            Urgent safety alerts keep a minimum vibration intensity, even when this slider is lower.
          </p>
        </Card>

        <Link
          to="/wifi-setup"
          onClick={tapFeedback}
          className="flex items-center justify-between rounded-2xl border border-night-700 bg-night-900 p-5 transition-colors hover:border-night-600"
        >
          <span>
            <span className="block text-xs font-medium uppercase tracking-wider text-mist-500">Connection</span>
            <span className="mt-1 block font-display text-base font-semibold text-mist-100">Change Wi-Fi network</span>
            <span className="mt-1 block text-xs text-mist-500">Connect your glasses to home Wi-Fi or your phone hotspot.</span>
          </span>
          <Wifi size={20} className="shrink-0 text-signal-400" />
        </Link>

        {error && <p className="rounded-xl bg-alert-500/10 px-4 py-3 text-sm leading-6 text-alert-400">{error}</p>}

        <Button onClick={save} disabled={controlsDisabled || !needsApply} className="w-full">
          {primaryLabel}
        </Button>
      </div>
    </Layout>
  )
}
