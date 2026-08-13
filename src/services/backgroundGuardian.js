/**
 * Keeps obstacle guidance running when the phone is pocketed.
 *
 * Android parks a backgrounded WebView's timers and the Wi-Fi radio, so the
 * one-second glasses poll (and every spoken alert) stopped the moment the
 * screen went off. The native foreground service holds a wake lock and a
 * Wi-Fi lock for as long as the glasses are paired.
 */
import { Capacitor, registerPlugin } from '@capacitor/core'

const BackgroundGuardian = registerPlugin('BackgroundGuardian')

export async function startBackgroundGuardian() {
  if (!Capacitor.isNativePlatform()) return false
  try {
    await BackgroundGuardian.start()
    return true
  } catch (error) {
    console.warn('[guardian] could not start background guidance', error)
    return false
  }
}

export async function stopBackgroundGuardian() {
  if (!Capacitor.isNativePlatform()) return
  try {
    await BackgroundGuardian.stop()
  } catch (error) {
    console.warn('[guardian] could not stop background guidance', error)
  }
}
