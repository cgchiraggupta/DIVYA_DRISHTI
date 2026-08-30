// Free-form conversation with "Divya" -- the fallback when a spoken command
// doesn't match any of the fixed voice intents (voiceIntents.js). Unlike
// gemini-vision, this never touches the camera: it's plain multi-turn text
// chat, called from useVoiceCommands.js's executeIntent default case. The
// phone keeps the conversation history client-side and resends it each turn
// (Gemini is stateless between calls) -- see src/services/divyaChat.js.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const GEMINI_MODEL = 'gemini-3.5-flash'
const MAX_HISTORY_TURNS = 8

const SYSTEM_INSTRUCTION =
  'You are Divya, the voice companion built into Divya Drishti smart glasses for a ' +
  'blind or low-vision user. You are having a spoken conversation, not a text chat -- ' +
  'your reply is read aloud immediately, so keep it short and natural: normally one to ' +
  'three sentences, never a list, never markdown. ' +
  'Reply in the same language the user just spoke in -- Hindi (Devanagari script) if ' +
  'they spoke Hindi or Hinglish, English if they spoke English. Match their language ' +
  'each turn; do not force one language throughout. ' +
  'You have no live camera access in this conversation -- if asked what is nearby, or ' +
  'to describe/read something right now, tell them to say "what\'s ahead" or "read this" ' +
  'instead, which does use the camera. Never claim to see anything here. ' +
  'You are not responsible for obstacle safety alerts -- those come from the glasses\' ' +
  'own sensors independently of this conversation; do not comment on them unless asked. ' +
  'Be warm, direct, and genuinely useful -- this is a real assistant conversation, not a ' +
  'canned script.'

type HistoryTurn = { role: 'user' | 'model'; text: string }

function sanitizeHistory(raw: unknown): HistoryTurn[] {
  if (!Array.isArray(raw)) return []
  const turns: HistoryTurn[] = []
  for (const item of raw) {
    const role = item?.role === 'model' ? 'model' : item?.role === 'user' ? 'user' : null
    const text = typeof item?.text === 'string' ? item.text.trim() : ''
    if (role && text) turns.push({ role, text })
  }
  return turns.slice(-MAX_HISTORY_TURNS * 2)
}

async function callGemini(apiKey: string, history: HistoryTurn[], message: string): Promise<string> {
  const contents = [
    ...history.map((turn) => ({ role: turn.role, parts: [{ text: turn.text }] })),
    { role: 'user', parts: [{ text: message }] },
  ]

  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey,
      },
      body: JSON.stringify({
        system_instruction: { parts: [{ text: SYSTEM_INSTRUCTION }] },
        contents,
        generationConfig: {
          thinkingConfig: { thinkingLevel: 'low' },
        },
      }),
    },
  )

  if (!response.ok) {
    const body = await response.text()
    throw new Error(`Gemini ${response.status}: ${body.slice(0, 200)}`)
  }
  const data = await response.json()
  const text = data?.candidates?.[0]?.content?.parts?.[0]?.text
  if (!text) throw new Error('Gemini returned no text')
  return text.trim()
}

function mockReplyFor(message: string): string {
  const isHindi = /[ऀ-ॿ]/.test(message)
  return isHindi
    ? 'अभी मैं डेमो मोड में हूँ, असली जवाब के लिए Gemini कुंजी चाहिए।'
    : "I'm in demo mode right now -- a Gemini key is needed for real replies."
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  })
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: CORS_HEADERS })
  }

  try {
    const { pairing_code, message, history } = await req.json()

    if (!pairing_code || typeof pairing_code !== 'string') {
      return json({ status: 'error', reply: '', error: 'pairing_code required' }, 400)
    }
    const trimmedMessage = typeof message === 'string' ? message.trim() : ''
    if (!trimmedMessage) {
      return json({ status: 'error', reply: '', error: 'message required' }, 400)
    }

    // Same access control as gemini-vision: a valid pairing code before
    // spending any Gemini quota.
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
    )
    const { data: device, error: deviceError } = await supabase
      .from('devices')
      .select('id')
      .eq('pairing_code', String(pairing_code).trim().toUpperCase())
      .maybeSingle()

    if (deviceError || !device) {
      return json({ status: 'error', reply: '', error: 'Unknown pairing code' }, 401)
    }

    const geminiKey = Deno.env.get('GEMINI_API_KEY')
    const safeHistory = sanitizeHistory(history)
    let reply: string
    let source: string
    if (!geminiKey) {
      reply = mockReplyFor(trimmedMessage)
      source = 'mock'
    } else {
      reply = await callGemini(geminiKey, safeHistory, trimmedMessage)
      source = 'gemini'
    }

    return json({ status: 'ok', reply, source })
  } catch (error) {
    console.error('[divya-chat] failed:', error)
    return json({
      status: 'error',
      reply: 'अभी जवाब नहीं दे पाई। फिर से कोशिश करें।',
      error: String(error),
    }, 500)
  }
})
