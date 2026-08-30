// Runs every Gemini vision call for Divya Drishti -- the Pi has no Gemini
// key of its own. Called by the phone whenever the glasses (button click,
// near-obstacle naming, ambient scene description, or the phone's own
// UI/voice) ask to process a photo -- see request_phone_vision() in
// setup/hardware-integration/divya_drishti_final.py for the Pi side. If
// this can't be reached, that request just doesn't happen; there is no
// Pi-local fallback.
//
// Prompts below are the only copy that exists -- the Pi no longer keeps
// its own copies to stay in sync with.
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const GEMINI_MODEL = 'gemini-3.5-flash'

const HINDI_TTS_RULES =
  'Reply ONLY in Hindi Devanagari script. ' +
  'Keep numbers as digits (2, 80, 1.5), never as words. ' +
  'Write distance units in English as cm or m, for example 80 cm or 1 m. ' +
  'Do not write सेंटीमीटर or मीटर. ' +
  'Do not use other English words except printed text you read from signs, labels, ' +
  'screens, or posters — quote that text exactly as written. '

const DESCRIBE_PROMPT =
  'You are Divya Drishti object mode for a blind walker looking through glasses. ' +
  HINDI_TTS_RULES +
  'Name what is directly in front: people, furniture, walls, doors, vehicles, poles, ' +
  'or stairs if clearly visible. Say side when obvious (सामने / बाईं ओर / दाईं ओर). ' +
  'If a large sign is the main thing, say a board is there — do not read long text; ' +
  'that is a separate Read action. Do NOT tour the far background. Max 40 words.'

const OCR_PROMPT =
  'You are Divya Drishti read mode for a blind user pointing the glasses at text. ' +
  HINDI_TTS_RULES +
  'Read ONLY printed or on-screen text that is clearly visible ' +
  '(signs, labels, posters, screens). Quote it exactly as written. ' +
  'If several lines, read the main heading first, then one short extra line if useful. ' +
  'If no writing is readable, say exactly: कोई लिखावट नहीं दिख रही। ' +
  'Do NOT describe furniture, people, or the room. Max 40 words.'

const OCR_FULL_PROMPT =
  'You are Divya Drishti full-document read mode for a blind user pointing ' +
  'the glasses at a page of a paper or document and asking to have it read ' +
  'in full, not just glanced at. ' +
  'Reply ONLY in Hindi Devanagari script. Keep numbers as digits (2, 80, 1.5), ' +
  'never as words. ' +
  'Read ALL the visible printed or on-screen text on this page, in reading ' +
  'order (top to bottom, left to right for most layouts). Do not stop after ' +
  'the heading or first line — continue through every visible paragraph, ' +
  'row, or block of text on the page. ' +
  'If the text is written in a language other than Hindi, translate its full ' +
  'meaning into Hindi and speak that translation faithfully — do not skip a ' +
  'section just because it is in another language, and do not just name the ' +
  'language. ' +
  'If no readable text is visible at all, say exactly: कोई लिखावट नहीं दिख रही। ' +
  'Do NOT describe furniture, people, or the room — text only. ' +
  'There is no fixed word limit, but do not repeat the same line twice.'

const MOCK_DESCRIBE_HI = 'सामने कुर्सी है। दाईं ओर एक व्यक्ति खड़ा है।'
const MOCK_OCR_HI = 'बोर्ड पर लिखा है EXIT। नीचे Gate 2 लिखा है।'
const MOCK_OCR_FULL_HI =
  'पहला पैराग्राफ: यह एक नमूना दस्तावेज़ है। ' +
  'दूसरा पैराग्राफ: इस पन्ने पर जो कुछ भी लिखा था, वह पूरा पढ़ दिया गया है।'

function formatDistanceLabel(distanceMm: number | null | undefined): string {
  if (distanceMm == null) return 'अज्ञात दूरी'
  const mm = Math.max(0, Math.round(distanceMm))
  if (mm < 1000) return `${Math.max(1, Math.round(mm / 10))} cm`
  const meters = mm / 1000
  if (Math.abs(meters - Math.round(meters)) < 0.05) return `${Math.round(meters)} m`
  return `${meters.toFixed(1)} m`
}

function formatDirectionHi(direction?: string | null): string {
  const mapping: Record<string, string> = {
    ahead: 'सामने', left: 'बाईं ओर', right: 'दाईं ओर', behind: 'पीछे',
  }
  return mapping[(direction || 'ahead').trim().toLowerCase()] || 'सामने'
}

// Near-obstacle naming: only the object likely causing a ToF reading that
// just fired -- not a general scene description. Templated with the actual
// direction/distance/range, mirroring gemini_describe.py's old OBSTACLE_PROMPT.
function obstaclePrompt(direction: string | null, distanceMm: number | null, maxRangeMm: number | null): string {
  const rangeMm = Math.max(1000, Math.min(2500, maxRangeMm ?? 2500))
  const distanceLabel = formatDistanceLabel(distanceMm)
  const maxRangeLabel = formatDistanceLabel(rangeMm)
  const directionHi = formatDirectionHi(direction)
  return (
    `You are Divya Drishti obstacle mode. A distance sensor fired: direction=${directionHi}, ` +
    `measured distance about ${distanceLabel}. User obstacle range setting is max ${maxRangeLabel}. ` +
    HINDI_TTS_RULES +
    'Look at the photo and name ONLY the nearby object likely causing that reading ' +
    `(chair, person, door, wall, vehicle, pole, stairs — roughly within ${maxRangeLabel}, ` +
    `toward ${directionHi}). Example: 'सामने कुर्सी है, लगभग 80 cm।' ` +
    `Do NOT mention far walls, distant people, sky, or anything clearly beyond ${maxRangeLabel}. ` +
    'Do NOT read sign text. If the near object is unclear, say so briefly with the distance. ' +
    'Max 20 words.'
  )
}

function promptFor(mode: string, direction: string | null, distanceMm: number | null, maxRangeMm: number | null): string {
  if (mode === 'read') return OCR_PROMPT
  if (mode === 'read_full') return OCR_FULL_PROMPT
  if (mode === 'obstacle') return obstaclePrompt(direction, distanceMm, maxRangeMm)
  return DESCRIBE_PROMPT
}

function mockFor(mode: string, direction: string | null, distanceMm: number | null): string {
  if (mode === 'read') return MOCK_OCR_HI
  if (mode === 'read_full') return MOCK_OCR_FULL_HI
  if (mode === 'obstacle') return `${formatDirectionHi(direction)} बाधा है, लगभग ${formatDistanceLabel(distanceMm)}।`
  return MOCK_DESCRIBE_HI
}

async function callGemini(apiKey: string, prompt: string, imageBase64: string): Promise<string> {
  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey,
      },
      body: JSON.stringify({
        contents: [{
          parts: [
            { text: prompt },
            { inline_data: { mime_type: 'image/jpeg', data: imageBase64 } },
          ],
        }],
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
    const { pairing_code, mode, image_base64, direction, distance_mm, max_range_mm } = await req.json()
    const safeMode = ['read', 'read_full', 'obstacle'].includes(mode) ? mode : 'describe'

    if (!pairing_code || typeof pairing_code !== 'string') {
      return json({ status: 'error', text_hi: '', error: 'pairing_code required' }, 400)
    }
    if (!image_base64 || typeof image_base64 !== 'string') {
      return json({ status: 'error', text_hi: '', error: 'image_base64 required' }, 400)
    }

    // Reject anyone who doesn't hold a real pairing code before spending any
    // Gemini quota -- the pairing code is this project's access control
    // everywhere else too (RLS on the device tables is deliberately open).
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
      return json({ status: 'error', text_hi: '', error: 'Unknown pairing code' }, 401)
    }

    const geminiKey = Deno.env.get('GEMINI_API_KEY')
    let textHi: string
    let source: string
    if (!geminiKey) {
      textHi = mockFor(safeMode, direction ?? null, distance_mm ?? null)
      source = 'mock'
    } else {
      const prompt = promptFor(safeMode, direction ?? null, distance_mm ?? null, max_range_mm ?? null)
      textHi = await callGemini(geminiKey, prompt, image_base64)
      source = 'gemini'
    }

    return json({ status: 'ok', text_hi: textHi, source: `phone_${source}`, mode: safeMode })
  } catch (error) {
    console.error('[gemini-vision] failed:', error)
    return json({
      status: 'error',
      text_hi: 'अभी बता नहीं पाए। थोड़ी देर बाद फिर कोशिश करें।',
      error: String(error),
    }, 500)
  }
})
