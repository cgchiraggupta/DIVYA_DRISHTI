import { useMemo, useState } from 'react'
import { AlertTriangle, Mic, ShieldCheck, Settings as SettingsIcon, Volume2 } from 'lucide-react'
import Layout from '../components/Layout'
import { useDevice } from '../context/DeviceContext'
import { alertLabel, formatDistanceMeters, formatTimestamp, isHazardEvent } from '../lib/format'
import { signalGuidance, speakGuidance, tapFeedback } from '../services/sensoryFeedback'

const FILTERS = [
  { id: 'obstacles', label: 'Obstacles' },
  { id: 'all', label: 'Cloud log' },
  { id: 'hazard', label: 'Cloud hazards' },
  { id: 'voice_command', label: 'Voice' },
  { id: 'system', label: 'System' },
]

function eventIcon(eventType) {
  if (isHazardEvent(eventType)) return AlertTriangle
  if (eventType === 'voice_command') return Mic
  if (eventType === 'system') return SettingsIcon
  return ShieldCheck
}

export default function History() {
  const { events, loading, obstacleHistory } = useDevice()
  const [filter, setFilter] = useState(() => {
    try {
      return window.sessionStorage.getItem('divyadrishti-history-filter') || 'obstacles'
    } catch {
      return 'obstacles'
    }
  })

  const filtered = useMemo(() => {
    if (filter === 'obstacles') return obstacleHistory || []
    if (filter === 'all') return events
    if (filter === 'hazard') return events.filter((e) => isHazardEvent(e.event_type))
    return events.filter((e) => e.event_type === filter)
  }, [events, filter, obstacleHistory])

  const selectFilter = (id) => {
    setFilter(id)
    try {
      window.sessionStorage.setItem('divyadrishti-history-filter', id)
    } catch {
      // ignore
    }
    tapFeedback()
  }

  const replayEvent = (event) => {
    const distance = event.detail?.distance_mm || event.distance_mm
      ? ` ${formatDistanceMeters(event.detail?.distance_mm ?? event.distance_mm)} away.`
      : ''
    const message =
      event.speak_hi
      ?? event.detail?.speak_hi
      ?? event.detail?.response
      ?? event.detail?.message
      ?? `${alertLabel(event.event_type)}.${distance}`
    signalGuidance({ text: message, isHazard: isHazardEvent(event.event_type) || event.kind === 'obstacle' })
  }

  return (
    <Layout title="Alert History" subtitle="Obstacle photos + Hinglish on this phone">
      <div className="flex gap-2 overflow-x-auto pb-4 -mx-1 px-1">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => {
              selectFilter(f.id)
            }}
            className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs font-medium border transition-colors ${
              filter === f.id
                ? 'bg-signal-500 text-night-950 border-signal-500'
                : 'bg-night-900 text-mist-300 border-night-700 hover:border-night-600'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {filter === 'obstacles' && (
        <p className="mb-3 text-xs leading-5 text-mist-500">
          Phone photos + spoken distance — saved here when glasses detect a nearby obstacle (within your Settings range) or you tap Read. Best tab for demos. Distances under 1 m show as cm. Tap a card to hear it again.
        </p>
      )}
      {filter === 'all' && (
        <p className="mb-3 text-xs leading-5 text-mist-500">
          Cloud log only — text events without photos. For demos (and live obstacle photos + spoken distance), stay on Obstacles — phone and glasses need the same Wi‑Fi.
        </p>
      )}

      {loading && filter !== 'obstacles' && <p className="text-mist-400 text-sm">Loading…</p>}

      {!loading && filtered.length === 0 && (
        <div className="mt-10 text-center text-mist-500">
          <p className="text-sm">No events in this view yet.</p>
        </div>
      )}

      <ul className="space-y-2.5">
        {filtered.map((event) => {
          const Icon = eventIcon(event.event_type)
          const hazard = isHazardEvent(event.event_type) || filter === 'obstacles'
          const speakText = event.speak_hi || event.detail?.speak_hi || event.detail?.message
          const image = event.image_jpeg_b64 || event.detail?.image_jpeg_b64
          const key = event.id || `${event.created_at}-${event.event_type}`
          return (
            <li key={key}>
              <button
                onClick={() => replayEvent(event)}
                className="flex w-full flex-col gap-3 rounded-xl border border-night-700 bg-night-900 p-3.5 text-left transition active:scale-[0.99] hover:border-night-600"
              >
                <div className="flex items-start gap-3">
                  <span
                    className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                      hazard ? 'bg-signal-500/15 text-signal-400' : 'bg-night-700 text-mist-300'
                    }`}
                  >
                    <Icon size={16} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-mist-100">
                      {filter === 'obstacles'
                        ? (event.source === 'describe' || event.source === 'read' || event.event_type === 'voice_command'
                          ? 'Read'
                          : alertLabel(event.event_type))
                        : alertLabel(event.event_type)}
                    </p>
                    {speakText && <p className="mt-1 text-sm leading-5 text-mist-300">{speakText}</p>}
                    {event.detail?.command && (
                      <p className="text-xs text-mist-400 truncate">"{event.detail.command}"</p>
                    )}
                    {(event.distance_mm || event.detail?.distance_mm) && (
                      <p className="mt-1 text-xs text-mist-500">
                        {formatDistanceMeters(event.distance_mm ?? event.detail.distance_mm)} · {event.direction || event.detail?.direction || 'ahead'}
                      </p>
                    )}
                  </div>
                  <span className="font-data text-xs text-mist-500 shrink-0">{formatTimestamp(event.created_at)}</span>
                </div>
                {image && (
                  <img
                    alt="Obstacle or describe snapshot"
                    src={`data:image/jpeg;base64,${image}`}
                    className="w-full rounded-lg border border-night-700 object-cover"
                  />
                )}
                {speakText && (
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-signal-300">
                    <Volume2 size={14} /> Tap to hear again
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </Layout>
  )
}
