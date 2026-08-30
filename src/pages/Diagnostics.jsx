import { useCallback, useEffect, useState } from 'react'
import { HeartPulse, RefreshCw } from 'lucide-react'
import Layout from '../components/Layout'
import Card from '../components/Card'
import Button from '../components/Button'
import { useDevice } from '../context/DeviceContext'
import { timeAgo } from '../lib/format'
import { checkMicPermission } from '../services/phoneSpeech'

function Row({ label, value, ok }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-night-800 last:border-0">
      <span className="text-sm text-mist-300">{label}</span>
      <span className={`text-sm font-medium ${ok === undefined ? 'text-mist-200' : ok ? 'text-safe-400' : 'text-alert-400'}`}>
        {value}
      </span>
    </div>
  )
}

export default function Diagnostics() {
  const { device, status, refresh, loading, dataError } = useDevice()
  const [micOk, setMicOk] = useState(null)

  const loadMic = useCallback(() => {
    checkMicPermission().then(setMicOk)
  }, [])

  useEffect(() => {
    loadMic()
  }, [loadMic])

  const handleRefresh = () => {
    refresh()
    loadMic()
  }

  return (
    <Layout title="Device care" subtitle="A quick check of your glasses">
      <div className="space-y-4">
        <Card eyebrow="Your device" title={device?.name ?? 'Divya Drishti'}>
          <Row label="Set up" value={device?.paired_at ? timeAgo(device.paired_at) : '—'} />
          <Row label="Last safety update" value={status?.updated_at ? timeAgo(status.updated_at) : '—'} />
          <Row label="Guidance" value={status?.mode === 'tof' ? 'Obstacle sensing' : status?.mode === 'camera_fallback' ? 'Camera fallback' : 'Waiting for status'} />
        </Card>

        <Card eyebrow="Health" title="Hardware health">
          <Row label="Left sensing" value={status?.tof_left_ok ? 'Working well' : 'Needs attention'} ok={status?.tof_left_ok} />
          <Row label="Right sensing" value={status?.tof_right_ok ? 'Working well' : 'Needs attention'} ok={status?.tof_right_ok} />
          <Row label="Camera" value={status?.camera_ok ? 'Online' : 'Unavailable'} ok={status?.camera_ok} />
          <Row
            label="Microphone (phone)"
            value={micOk === null ? 'Checking…' : micOk ? 'Permission granted' : 'Permission needed'}
            ok={micOk === null ? undefined : micOk}
          />
          <Row label="Buzzer" value={status?.buzzer_ok ? 'Online' : 'Unavailable'} ok={status?.buzzer_ok} />
        </Card>

        <Card eyebrow="Live status" title="Refresh device information">
          <p className="text-sm text-mist-400 mb-4">
            Refresh checks the latest status sent by your glasses. It does not start sound, vibration, or a hardware self-test.
          </p>
          <Button onClick={handleRefresh} disabled={loading || !device} className="w-full">
            <RefreshCw size={16} />
            {loading ? 'Refreshing…' : 'Refresh status'}
          </Button>
        </Card>

        {dataError && (
          <div className="rounded-xl bg-alert-500/10 px-4 py-3 text-sm leading-6 text-alert-400">
            {dataError}
          </div>
        )}

        <div className="flex items-center gap-2 justify-center text-xs text-mist-500 pt-2">
          <HeartPulse size={14} />
          <span>Designed to support every journey</span>
        </div>
      </div>
    </Layout>
  )
}
