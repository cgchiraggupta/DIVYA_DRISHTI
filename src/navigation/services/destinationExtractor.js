import { supabase } from '../../lib/supabaseClient'

/**
 * Extract a destination place name from free-form navigation text via the
 * gemini-navigate Supabase Edge Function (same pattern as glassesVision.js --
 * the Gemini key never reaches the client).
 *
 * @param {string} pairingCode
 * @param {string} text  e.g. "Take me to India Gate"
 * @param {{role: 'user'|'model', text: string}[]} [history]  prior turns in
 *   this navigation session, so "actually go to X instead" resolves correctly
 * @returns {Promise<{status: 'ok'|'not_found'|'error', destination: string, error?: string}>}
 */
export async function extractDestination(pairingCode, text, history = []) {
  try {
    const { data, error } = await supabase.functions.invoke('gemini-navigate', {
      body: { pairing_code: pairingCode, text, history },
    })
    if (error) throw error
    return data
  } catch (error) {
    return {
      status: 'error',
      destination: '',
      error: String(error?.message || error),
    }
  }
}
