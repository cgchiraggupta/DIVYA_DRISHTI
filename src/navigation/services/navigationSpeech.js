/**
 * Thin wrapper around the existing Sarvam TTS integration for turn-by-turn
 * announcements, so navigation doesn't duplicate speech/audio-session logic
 * already solved in services/sarvamTts.js.
 */
import { speakWithSarvam } from '../../services/sarvamTts'
import { speakWithBargeIn } from '../../services/bargeIn'

/**
 * Speak a turn-by-turn announcement, interruptible: if the user starts
 * talking mid-instruction (e.g. to change destination or ask a question),
 * playback stops immediately.
 * @returns {Promise<{interrupted: boolean, matches?: string[]}>}
 */
export function announceStep(text) {
  return speakWithBargeIn(() => speakWithSarvam(text, { language: 'hi-IN' }))
}
