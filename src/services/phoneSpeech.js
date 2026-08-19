/**
 * Capture one spoken utterance from the phone mic (Google / Android STT).
 * Glasses I²S capture is not used until AUDIO_IO.mic flips to 'glasses'.
 */
import { Capacitor } from '@capacitor/core'
import { SpeechRecognition } from '@capgo/capacitor-speech-recognition'
import { isPhoneMic } from './audioIo'

const LISTEN_LANGUAGE = 'hi-IN'

function webListen(language) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!Recognition) {
    return Promise.reject(new Error('This browser has no speech recognition.'))
  }

  return new Promise((resolve, reject) => {
    const rec = new Recognition()
    rec.lang = language
    rec.interimResults = false
    rec.maxAlternatives = 5
    rec.continuous = false
    let settled = false
    const finish = (matches) => {
      if (settled) return
      settled = true
      resolve(matches)
    }

    rec.onresult = (event) => {
      const matches = []
      const row = event.results?.[0]
      if (row) {
        for (let i = 0; i < row.length; i += 1) matches.push(row[i].transcript)
      }
      finish(matches)
    }
    rec.onerror = (event) => {
      if (settled) return
      settled = true
      const code = event?.error || 'failed'
      if (code === 'no-speech' || code === 'aborted') {
        resolve([])
        return
      }
      reject(new Error(code === 'not-allowed' ? 'Microphone permission is required.' : `Could not hear you (${code}).`))
    }
    rec.onend = () => finish([])
    try {
      rec.start()
    } catch (error) {
      reject(error)
    }
  })
}

async function ensurePermission() {
  const current = await SpeechRecognition.checkPermissions()
  if (current.speechRecognition === 'granted') return
  const requested = await SpeechRecognition.requestPermissions()
  if (requested.speechRecognition !== 'granted') {
    throw new Error('Microphone permission is required for voice commands.')
  }
}

/**
 * Listen for one command. Returns ranked transcript strings (best first).
 */
export async function listenForSpeech() {
  if (!isPhoneMic()) {
    throw new Error('Glasses mic is not enabled yet. Voice still uses this phone.')
  }

  if (!Capacitor.isNativePlatform()) {
    return webListen(LISTEN_LANGUAGE)
  }

  const { available } = await SpeechRecognition.available()
  if (!available) {
    throw new Error('Google speech recognition is not available on this phone.')
  }

  await ensurePermission()

  try {
    await SpeechRecognition.stop()
  } catch {
    // ignore — nothing listening
  }

  const result = await SpeechRecognition.start({
    language: LISTEN_LANGUAGE,
    maxResults: 5,
    prompt: 'Divya Drishti',
    popup: false,
    partialResults: false,
  })

  const matches = Array.isArray(result?.matches)
    ? result.matches.map((item) => String(item || '').trim()).filter(Boolean)
    : []
  return matches
}

export async function stopListening() {
  if (!Capacitor.isNativePlatform()) return
  try {
    await SpeechRecognition.stop()
  } catch {
    // ignore
  }
}

export function playListenCue() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return Promise.resolve()
    const ctx = new Ctx()
    const now = ctx.currentTime
    const gain = ctx.createGain()
    gain.gain.setValueAtTime(0.001, now)
    gain.gain.exponentialRampToValueAtTime(0.18, now + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.16)
    gain.connect(ctx.destination)
    const osc = ctx.createOscillator()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(990, now)
    osc.connect(gain)
    osc.start(now)
    osc.stop(now + 0.18)
    return new Promise((resolve) => {
      osc.onended = () => {
        ctx.close().catch(() => {})
        resolve()
      }
      window.setTimeout(resolve, 220)
    })
  } catch {
    return Promise.resolve()
  }
}
