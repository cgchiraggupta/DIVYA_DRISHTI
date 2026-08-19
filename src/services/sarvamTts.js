/**
 * Sarvam Bulbul TTS for Indian-language companion alerts.
 * Prototype: key from VITE_SARVAM_API_KEY. Move to an edge proxy before public release.
 */

const SARVAM_URL = 'https://api.sarvam.ai/text-to-speech'
const DEFAULT_SPEAKER = 'priya'
const DEFAULT_LANG = 'hi-IN'

let activeAudio = null

function apiKey() {
  return import.meta.env.VITE_SARVAM_API_KEY?.trim() || ''
}

export function isSarvamConfigured() {
  return Boolean(apiKey())
}

export function stopSarvamAudio() {
  if (!activeAudio) return
  try {
    activeAudio.pause()
    activeAudio.src = ''
  } catch {
    // ignore cleanup errors
  }
  activeAudio = null
}

function stopActiveAudio() {
  stopSarvamAudio()
}

function playBase64Wav(base64, volume = 1) {
  stopActiveAudio()
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  const blob = new Blob([bytes], { type: 'audio/wav' })
  const url = URL.createObjectURL(blob)
  const audio = new Audio(url)
  audio.volume = Math.min(1, Math.max(0, volume))
  activeAudio = audio
  return new Promise((resolve, reject) => {
    audio.onended = () => {
      URL.revokeObjectURL(url)
      if (activeAudio === audio) activeAudio = null
      resolve()
    }
    audio.onerror = () => {
      URL.revokeObjectURL(url)
      if (activeAudio === audio) activeAudio = null
      reject(new Error('Could not play Sarvam audio'))
    }
    audio.play().catch(reject)
  })
}

/**
 * Speak text with Sarvam. Returns true if audio played, false if skipped/failed.
 */
export async function speakWithSarvam(
  text,
  { volume = 1, language = DEFAULT_LANG, speaker = DEFAULT_SPEAKER, timeoutMs = 6_000 } = {},
) {
  const key = apiKey()
  if (!key || !text?.trim()) return false

  // Without this the request can hang forever on a flaky network and block
  // every later alert, which is why the phone went silent during walks.
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response
  try {
    response = await fetch(SARVAM_URL, {
      method: 'POST',
      headers: {
        'api-subscription-key': key,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: text.trim().slice(0, 2500),
        target_language_code: language,
        speaker,
        model: 'bulbul:v3',
        pace: 0.95,
      }),
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Sarvam TTS failed (${response.status})${detail ? `: ${detail.slice(0, 120)}` : ''}`)
  }

  const payload = await response.json()
  const audioB64 = payload?.audios?.[0]
  if (!audioB64) throw new Error('Sarvam TTS returned no audio')

  await playBase64Wav(audioB64, volume)
  return true
}
