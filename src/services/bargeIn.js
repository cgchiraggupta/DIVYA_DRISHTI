/**
 * Voice barge-in: lets the user interrupt Divya mid-sentence by just
 * speaking, instead of waiting for her to finish. Runs a continuous
 * partial-results recognition session in parallel with TTS playback; the
 * moment real speech is detected, it stops the TTS and hands back the
 * in-progress session so the caller doesn't need a second "start listening"
 * round trip.
 *
 * Native-only (needs @capgo/capacitor-speech-recognition's partialResults +
 * continuousPTT support). On web or when unsupported, callers fall back to
 * tap-to-interrupt (stopSpeech() wired to a button/tap) -- see
 * hooks/useVoiceCommands.js.
 */
import { Capacitor } from '@capacitor/core'
import { SpeechRecognition } from '@capgo/capacitor-speech-recognition'
import { isPhoneMic } from './audioIo'
import { stopSpeech } from './sensoryFeedback'

const LISTEN_LANGUAGE = 'hi-IN'
// Android's on-device recognizer emits a partial for ANY sound above its VAD
// threshold, not just speech -- steady background noise (a fan, AC hum) very
// commonly produces short low-confidence garbage transcripts. 2 characters
// was too permissive and cut Divya off on ambient noise alone; require a
// transcript that actually looks like a word or two.
const MIN_INTERRUPT_CHARS = 4
// A single noise-triggered partial rarely repeats with the same or growing
// text; real speech does. Require the same growing transcript to show up on
// two consecutive partial events before treating it as a real interruption.
const CONFIRM_PARTIALS = 2

export function isBargeInSupported() {
  return Capacitor.isNativePlatform() && isPhoneMic()
}

/**
 * Speak (via the given speak function) while listening in the background for
 * the user to interrupt. Resolves with:
 *   { interrupted: false } -- speech finished normally
 *   { interrupted: true, matches: string[] } -- user started talking;
 *     TTS was stopped and `matches` is what they said so far (final result
 *     from the same session, not just the partial that triggered the cut).
 *
 * `speak` must be a function returning a promise that resolves when audio
 * playback ends (e.g. () => speakGuidance(text)).
 */
export async function speakWithBargeIn(speak) {
  if (!isBargeInSupported()) {
    await speak()
    return { interrupted: false }
  }

  let interruptResolve
  const interrupted = new Promise((resolve) => {
    interruptResolve = resolve
  })

  let partialListener
  let listeningStarted = false
  let settled = false
  let consecutiveHits = 0
  let lastText = ''

  const cleanup = async () => {
    partialListener?.remove().catch(() => {})
    if (listeningStarted) {
      try {
        await SpeechRecognition.forceStop({ timeout: 800 })
      } catch {
        // ignore — best-effort teardown
      }
    }
  }

  try {
    partialListener = await SpeechRecognition.addListener('partialResults', (event) => {
      if (settled) return
      const text = (event.matches?.[0] || event.accumulatedText || '').trim()
      if (text.length < MIN_INTERRUPT_CHARS) {
        consecutiveHits = 0
        lastText = ''
        return
      }
      // A real utterance keeps producing partials as the person keeps
      // talking; a noise blip fires once and stops. Require the transcript
      // to still be there (same or longer) on the next partial too.
      consecutiveHits = text.startsWith(lastText) || lastText.startsWith(text) ? consecutiveHits + 1 : 1
      lastText = text
      if (consecutiveHits < CONFIRM_PARTIALS) return

      settled = true
      stopSpeech()
      interruptResolve({ interrupted: true, matches: event.matches || [text] })
    })

    // Best-effort: some devices reject a listen session started while TTS
    // audio is already routed to the speaker. If it throws, barge-in simply
    // doesn't fire for this utterance -- speech still plays normally.
    SpeechRecognition.start({
      language: LISTEN_LANGUAGE,
      partialResults: true,
      popup: false,
      continuousPTT: true,
      allowForSilence: 4000,
    })
      .then(() => {
        listeningStarted = true
      })
      .catch(() => {
        // no barge-in available for this utterance
      })

    const finishedNormally = speak().then(() => ({ interrupted: false }))
    const result = await Promise.race([finishedNormally, interrupted])
    settled = true
    return result
  } finally {
    await cleanup()
  }
}
