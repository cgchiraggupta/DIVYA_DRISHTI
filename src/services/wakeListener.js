/**
 * JS side of background wake-and-listen: hands config to the native
 * WakeConfigPlugin (see android/.../WakeConfigPlugin.java) and starts the
 * always-on WakeListenerService, which watches for the glasses button's
 * "wake" command even with the app closed and the phone locked, then hands
 * off to VoiceCaptureService (native STT -> divya-chat -> native TTS) for
 * one voice turn without ever needing the WebView to be running.
 *
 * This intentionally does NOT reuse useVoiceCommands.js's pipeline -- that
 * pipeline only runs while the WebView is alive, which Android suspends in
 * the background. This is a second, native implementation of the same
 * "wake -> listen -> answer" turn for when the WebView isn't.
 */
import { Capacitor, registerPlugin } from '@capacitor/core'
import { getLocalDeviceHost } from './localDeviceLink'

const WakeConfig = registerPlugin('WakeConfig')

export async function requestWakeListenerPermissions() {
  if (!Capacitor.isNativePlatform()) return { mic: false, notifications: false }
  try {
    return await WakeConfig.requestPermissions()
  } catch {
    return { mic: false, notifications: false }
  }
}

export async function checkWakeListenerPermissions() {
  if (!Capacitor.isNativePlatform()) return { mic: false, notifications: false }
  try {
    return await WakeConfig.checkPermissions()
  } catch {
    return { mic: false, notifications: false }
  }
}

/**
 * Sync current config to native and (re)start the always-on wake listener.
 * Safe to call repeatedly (e.g. every time the pairing code or nearby host
 * changes) -- sync() just overwrites the stored config.
 */
export async function startWakeListener(pairingCode) {
  if (!Capacitor.isNativePlatform() || !pairingCode) return false

  let localDeviceHost = ''
  try {
    localDeviceHost = await getLocalDeviceHost()
  } catch {
    // Not on the same Wi-Fi as the glasses right now -- WakeListenerService
    // will keep retrying with backoff once a host is known.
  }

  try {
    await WakeConfig.sync({
      pairingCode,
      supabaseUrl: import.meta.env.VITE_SUPABASE_URL || '',
      supabaseAnonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || '',
      sarvamApiKey: import.meta.env.VITE_SARVAM_API_KEY || '',
      localDeviceHost,
    })
    await WakeConfig.startWakeListening()
    return true
  } catch (error) {
    console.warn('[wakeListener] could not start', error)
    return false
  }
}

export async function stopWakeListener() {
  if (!Capacitor.isNativePlatform()) return
  try {
    await WakeConfig.stopWakeListening()
  } catch (error) {
    console.warn('[wakeListener] could not stop', error)
  }
}

export async function isWakeListenerRunning() {
  if (!Capacitor.isNativePlatform()) return false
  try {
    const result = await WakeConfig.isWakeListening()
    return Boolean(result?.running)
  } catch {
    return false
  }
}
