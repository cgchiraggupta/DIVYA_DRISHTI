// Extracts a destination place name from a spoken/typed navigation command
// ("Take me to India Gate", "mujhe Connaught Place le chalo") for the phone's
// Navigate flow. Mirrors gemini-vision's auth pattern (pairing code gates
// Gemini spend) but takes text in, text out -- no image, no Pi involvement.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const GEMINI_MODEL = 'gemini-3.5-flash'
// Same window as divya-chat's MAX_HISTORY_TURNS -- lets "actually take me to
// X instead" or "how far now" resolve against what was already said in this
// navigation session, without growing the prompt unboundedly.
const MAX_HISTORY_TURNS = 10

const EXTRACT_PROMPT =
  'You extract a navigation destination from a user\'s spoken or typed request, ' +
  'which may be in English, Hindi, or Hinglish. This function is called on every ' +
  'utterance a blind/low-vision user speaks to their assistant, most of which are ' +
  'NOT navigation requests -- only recognize an ACTUAL request to go/walk/be guided ' +
  'somewhere right now (e.g. "take me to India Gate", "mujhe Connaught Place le chalo", ' +
  '"navigate to the metro station", "kahan hai ATM, wahan le chalo"). ' +
  'Do NOT treat a past-tense mention, a question about a place without asking to go ' +
  'there, or an unrelated sentence that happens to name a place as a navigation ' +
  'request (e.g. "I went to India Gate yesterday", "what is India Gate", "India Gate ' +
  'is beautiful" are all NONE). ' +
  'The conversation history, if any, is prior turns in this same navigation session -- ' +
  'use it to resolve references ("actually go there instead", "no, the other one") but ' +
  'the CURRENT request is what you are extracting a destination for. ' +
  'Reply with ONLY the destination place name as plain text, suitable for a ' +
  'geocoding search (e.g. "India Gate, Delhi" or "Connaught Place, New Delhi"). ' +
  'Do not add explanations, quotes, or punctuation beyond the place name itself. ' +
  'If this is not an actual navigation request, reply with exactly: NONE.'

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

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  })
}

async function callGemini(apiKey: string, history: HistoryTurn[], userText: string): Promise<string> {
  const contents = [
    ...history.map((turn) => ({ role: turn.role, parts: [{ text: turn.text }] })),
    { role: 'user', parts: [{ text: userText }] },
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
        system_instruction: { parts: [{ text: EXTRACT_PROMPT }] },
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

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: CORS_HEADERS })
  }

  try {
    const { pairing_code, text, history } = await req.json()

    if (!pairing_code || typeof pairing_code !== 'string') {
      return json({ status: 'error', destination: '', error: 'pairing_code required' }, 400)
    }
    if (!text || typeof text !== 'string' || !text.trim()) {
      return json({ status: 'error', destination: '', error: 'text required' }, 400)
    }

    // Same access control as gemini-vision: a valid pairing code is required
    // before spending any Gemini quota (RLS on device tables is deliberately
    // open, so the pairing code is the boundary everywhere in this project).
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
      return json({ status: 'error', destination: '', error: 'Unknown pairing code' }, 401)
    }

    const geminiKey = Deno.env.get('GEMINI_API_KEY')
    if (!geminiKey) {
      return json({ status: 'error', destination: '', error: 'Gemini not configured', source: 'mock' }, 503)
    }

    const safeHistory = sanitizeHistory(history)
    const raw = await callGemini(geminiKey, safeHistory, text.trim().slice(0, 500))
    if (!raw || raw.toUpperCase() === 'NONE') {
      return json({ status: 'not_found', destination: '', source: 'gemini' })
    }

    return json({ status: 'ok', destination: raw, source: 'gemini' })
  } catch (error) {
    console.error('[gemini-navigate] failed:', error)
    return json({ status: 'error', destination: '', error: String(error) }, 500)
  }
})
