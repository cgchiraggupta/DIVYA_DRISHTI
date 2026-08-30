const WAKE_PHRASES = [
  'hey divya drishti',
  'ok divya drishti',
  'हे दिव्या दृष्टि',
  'हे दिव्य दृष्टि',
  'hey divya dristi',
  'hey divyadrishti',
  'divya drishti',
  'divya dristi',
  'दिव्या दृष्टि',
  'दिव्य दृष्टि',
  'hey divya',
  'ok divya',
  'ओके दिव्या',
  'हे दिव्या',
  'हे दिव्य',
  'दिव्या',
]

const PHRASES = {
  help: [
    'what can you do',
    'commands',
    'help me',
    'help',
    'मदद करो',
    'मदद',
    'कमांड',
  ],
  repeat: [
    'say that again',
    'say again',
    'hear again',
    'repeat',
    'again',
    'फिर से बोलो',
    'फिर से',
    'दोबारा बोलो',
  ],
  read: [
    'what is written',
    "what's written",
    'whats written',
    'read this',
    'read the sign',
    'read sign',
    'read it',
    'ocr',
    'पढ़ कर बताओ',
    'क्या लिखा है',
    'लिखा क्या है',
    'पढ़ो',
    'पढो',
  ],
  distance: [
    'how far',
    'how close',
    'what distance',
    'distance',
    'कितनी दूर',
    'कितना पास',
    'दूरी',
  ],
  pause: [
    'pause sensing',
    'stop sensing',
    'turn off alerts',
    'quiet mode',
    'pause',
    'सेंसिंग बंद',
    'अलर्ट बंद',
    'रुक जाओ',
    'बंद करो',
  ],
  resume: [
    'resume sensing',
    'start sensing',
    'turn on alerts',
    'unpause',
    'resume',
    'start',
    'सेंसिंग चालू',
    'शुरू करो',
    'चालू करो',
  ],
  describe: [
    "what's ahead",
    'whats ahead',
    'what is ahead',
    "what's in front",
    'whats in front',
    'what is in front',
    'look ahead',
    'describe',
    'आगे क्या है',
    'सामने क्या है',
    'क्या दिख रहा है',
    'क्या दिख रहा',
    'बताओ आगे',
    'देखो आगे',
  ],
  // Checked last on purpose: bare "stop"/"बस" would otherwise shadow more
  // specific compound phrases in other categories (e.g. pause's "stop
  // sensing") since findIntent takes the first category that matches.
  stop_speech: [
    'stop talking',
    'stop',
    'be quiet',
    'shut up',
    'silence',
    'मत बोलो',
    'चुप रहो',
    'चुप हो जाओ',
    'बस',
    'बात खत्म',
  ],
}

const HELP_SPEAK_HI =
  'कहिए: आगे क्या है, पढ़ो, कितनी दूर, रुक जाओ, शुरू करो, फिर से बोलो, या मदद। Double tap भी Describe है।'

export function normalizeTranscript(text) {
  return String(text || '')
    .toLowerCase()
    .replace(/['’]/g, '')
    .replace(/[।.?!,:;“”]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function containsPhrase(text, phrase) {
  const needle = normalizeTranscript(phrase)
  if (!text || !needle) return false
  if (text === needle) return true
  const isHindi = /[\u0900-\u097F]/.test(needle)
  if (isHindi || needle.includes(' ')) return text.includes(needle)
  return new RegExp(`(?:^|\\s)${needle}(?:\\s|$)`).test(text)
}

export function stripWakePhrase(text) {
  const normalized = normalizeTranscript(text)
  if (!normalized) return { remainder: '', hadWake: false }

  const sorted = [...WAKE_PHRASES].sort((a, b) => b.length - a.length)
  for (const wake of sorted) {
    if (normalized === wake) return { remainder: '', hadWake: true }
    if (normalized.startsWith(`${wake} `)) {
      return { remainder: normalized.slice(wake.length).trim(), hadWake: true }
    }
  }

  const compact = normalized.replace(/\s+/g, '')
  for (const wake of sorted) {
    const compactWake = wake.replace(/\s+/g, '')
    if (compact === compactWake) return { remainder: '', hadWake: true }
    if (compact.startsWith(compactWake) && compactWake.length >= 6) {
      const rest = compact.slice(compactWake.length)
      return { remainder: rest ? normalized.replace(wake, ' ').trim() || rest : '', hadWake: true }
    }
  }

  return { remainder: normalized, hadWake: false }
}

function findIntent(remainder) {
  for (const [intent, phrases] of Object.entries(PHRASES)) {
    if (phrases.some((phrase) => containsPhrase(remainder, phrase))) return intent
  }
  return 'unknown'
}

/**
 * Map one STT string to a command. Wake word is optional for a mic-button tap.
 */
export function matchVoiceIntent(raw) {
  const transcript = String(raw || '').trim()
  const { remainder, hadWake } = stripWakePhrase(transcript)
  if (!remainder) {
    return {
      intent: hadWake ? 'await_command' : 'empty',
      hadWake,
      remainder,
      transcript,
    }
  }

  return {
    intent: findIntent(remainder),
    hadWake,
    remainder,
    transcript,
  }
}

/** Prefer the first alternative that maps to a real command. */
export function pickVoiceIntent(matches, { requireWake = false } = {}) {
  const list = (Array.isArray(matches) ? matches : [matches]).filter(Boolean)
  for (const raw of list) {
    const mapped = matchVoiceIntent(raw)
    if (mapped.intent === 'unknown' || mapped.intent === 'empty') continue
    if (requireWake && !mapped.hadWake && mapped.intent !== 'await_command') continue
    return mapped
  }
  const fallback = matchVoiceIntent(list[0] || '')
  if (requireWake && !fallback.hadWake && fallback.intent !== 'await_command') {
    return { ...fallback, intent: 'ignored' }
  }
  return fallback
}

export function helpSpeech() {
  return HELP_SPEAK_HI
}
