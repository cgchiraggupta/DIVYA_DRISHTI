import { supabase } from '../lib/supabaseClient'

/**
 * Free-form conversation with Divya via the divya-chat Supabase Edge
 * Function -- the fallback path in useVoiceCommands.js's executeIntent when
 * a spoken utterance doesn't match any fixed voice intent. Never throws:
 * a failure here must still produce a spoken line, not a dead end.
 */
export async function askDivya(pairingCode, message, history = []) {
  try {
    const { data, error } = await supabase.functions.invoke('divya-chat', {
      body: { pairing_code: pairingCode, message, history },
    })
    if (error) throw error
    if (data?.status !== 'ok' || !data?.reply) {
      throw new Error(data?.error || 'No reply')
    }
    return { ok: true, reply: data.reply }
  } catch (error) {
    return {
      ok: false,
      reply: 'अभी जवाब नहीं दे पाई। फिर से कोशिश करें।',
      error: String(error?.message || error),
    }
  }
}
