import { supabase } from '../lib/supabaseClient'

/**
 * Run Gemini on a photo the glasses just captured, via the gemini-vision
 * Supabase Edge Function (the only place any Gemini key exists -- the Pi
 * has none). Called from DeviceContext's onVisionRequest handler whenever
 * the Pi asks this phone to process a photo (on-demand describe/read/
 * read_full, near-obstacle naming, or ambient scene description) -- see
 * request_phone_vision() in setup/hardware-integration/divya_drishti_final.py.
 * `visionRequest` is the Pi's vision_request payload as-is: at minimum
 * { mode, image_jpeg_b64 }, plus { direction, distance_mm, max_range_mm }
 * for mode "obstacle".
 *
 * Never throws: the Pi is waiting on a reply, so a failure here must still
 * produce a {status:'error', ...} payload rather than an unhandled
 * rejection that leaves the Pi's request hanging.
 */
export async function describeForGlasses(pairingCode, visionRequest) {
  try {
    const { data, error } = await supabase.functions.invoke('gemini-vision', {
      body: {
        pairing_code: pairingCode,
        mode: visionRequest?.mode,
        image_base64: visionRequest?.image_jpeg_b64,
        direction: visionRequest?.direction,
        distance_mm: visionRequest?.distance_mm,
        max_range_mm: visionRequest?.max_range_mm,
      },
    })
    if (error) throw error
    return data
  } catch (error) {
    return {
      status: 'error',
      text_hi: '',
      error: String(error?.message || error),
    }
  }
}
