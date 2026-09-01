import { useState } from 'react'
import { Zap } from '../lib/lucide'
import { useDevice } from '../context/DeviceContext'
import { isDemoMode } from '../lib/supabaseClient'
import { tapFeedback } from '../services/sensoryFeedback'

/**
 * In-app stand-in for the glasses' physical GPIO25 button's single-tap wake
 * gesture (see setup/hardware-integration/divyadrishti_control_button.py) --
 * for testing or using voice without the physical glasses in hand. Does the
 * exact same job: send "wake", which the Pi turns into a wake_requested
 * broadcast that Dashboard's existing effect turns into voice.listenOnce()
 * (and, if the background listener is on, VoiceCaptureService while the app
 * is backgrounded) -- not a separate shortcut path.
 */
export default function FloatingWakeButton() {
  const { device, nearbyLink, sendNearbyDeviceCommand, triggerWakeLocally } = useDevice()
  const [pressed, setPressed] = useState(false)

  if (!device) return null

  const nearbyControlAvailable = !isDemoMode && nearbyLink.state === 'connected'

  const handlePress = async () => {
    tapFeedback()
    setPressed(true)
    window.setTimeout(() => setPressed(false), 400)

    if (nearbyControlAvailable) {
      try {
        await sendNearbyDeviceCommand('wake')
        return
      } catch {
        // Fall through to the local trigger below so the button still
        // responds even if the round trip to the glasses failed.
      }
    }
    triggerWakeLocally()
  }

  return (
    <button
      type="button"
      onClick={handlePress}
      aria-label="Wake voice assistant (same as the glasses button)"
      className={`fixed z-30 flex h-14 w-14 items-center justify-center rounded-full shadow-lg shadow-black/40
                  transition active:scale-95 ${pressed ? 'bg-alert-500 text-night-950' : 'bg-signal-500 text-night-950'}`}
      style={{
        right: 'calc(env(safe-area-inset-right) + 1.25rem)',
        bottom: 'calc(env(safe-area-inset-bottom) + 6.5rem)',
      }}
    >
      <Zap size={24} strokeWidth={2.25} />
    </button>
  )
}
