/**
 * Where mic and speaker live right now.
 *
 * Both on the phone -- the Pi has no mic or speaker of its own. Earbuds
 * pair to the phone directly (normal Bluetooth headset pairing); the OS
 * routes phone STT/TTS through them once connected.
 */
export const AUDIO_IO = {
  mic: 'phone',
  speaker: 'phone',
}

export function isPhoneMic() {
  return AUDIO_IO.mic === 'phone'
}

export function isPhoneSpeaker() {
  return AUDIO_IO.speaker === 'phone'
}
