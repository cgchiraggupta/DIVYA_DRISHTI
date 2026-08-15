import { Capacitor } from '@capacitor/core'
import { Haptics, ImpactStyle } from '@capacitor/haptics'
import { TextToSpeech } from '@capacitor-community/text-to-speech'
import { isSarvamConfigured, speakWithSarvam } from './sarvamTts'

/** Devanagari → hi-IN. Latin fallback stays en-IN for mixed device voices. */
function voiceLangFor(text) {
  return /[\u0900-\u097F]/.test(text) ? 'hi-IN' : 'en-IN'
}

function browserSpeech(text, volume) {
  if (!('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 0.95
  utterance.volume = volume
  utterance.lang = voiceLangFor(text)
  window.speechSynthesis.speak(utterance)
}

async function deviceSpeech(text, volume) {
  if (!Capacitor.isNativePlatform()) {
    browserSpeech(text, volume)
    return
  }

  // Some engines reject an unsupported locale, so degrade instead of going silent.
  const attempts = [voiceLangFor(text), 'en-IN', 'en-US']
  let lastError = null
  for (const lang of attempts) {
    try {
      await TextToSpeech.speak({ text, rate: 0.95, volume, lang })
      return
    } catch (error) {
      lastError = error
    }
  }
  throw lastError ?? new Error('Device TTS unavailable')
}

/**
 * Speak on this phone. `fast` (obstacle alerts, system announcements) goes
 * straight to the offline device voice — no network hop before a safety cue.
 * Longer Read/OCR text prefers the Sarvam Indian voice and falls back.
 */
export async function speakGuidance(text, volume = 1, { fast = false } = {}) {
  if (!text) return

  if (fast) {
    try {
      await deviceSpeech(text, volume)
      return
    } catch (error) {
      console.warn('[tts] device voice failed, trying Sarvam', error)
    }
  }

  if (isSarvamConfigured()) {
    try {
      const played = await speakWithSarvam(text, { volume })
      if (played) return
    } catch (error) {
      console.warn('[tts] Sarvam unavailable, using device voice', error)
    }
  }

  try {
    await deviceSpeech(text, volume)
  } catch (error) {
    console.warn('[tts] falling back to browser speech', error)
    browserSpeech(text, volume)
  }
}

export async function tapFeedback() {
  try {
    if (Capacitor.isNativePlatform()) {
      await Haptics.impact({ style: ImpactStyle.Light })
      return
    }
  } catch {
    // Fall through to the browser vibration API.
  }

  navigator.vibrate?.(12)
}

export async function signalGuidance({ text, isHazard = false, audio = true, vibration = true, audioVolume = 1, vibrationDuration = 420 }) {
  const vibrationPattern = isHazard ? [120, 80, 260] : [45]

  if (vibration) {
    try {
      if (Capacitor.isNativePlatform()) {
        if (isHazard) await Haptics.vibrate({ duration: vibrationDuration })
        else await Haptics.impact({ style: ImpactStyle.Light })
      } else {
        navigator.vibrate?.(vibrationPattern)
      }
    } catch {
      navigator.vibrate?.(vibrationPattern)
    }
  }

  if (audio) await speakGuidance(text, audioVolume)
}
