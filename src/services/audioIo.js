/**
 * Where mic and speaker live right now.
 *
 * Phone Google STT is still the mic. Speaker is the Pi Bluetooth
 * earbuds (Nirvana Ion A2DP) now that that path is heard working.
 * Intent mapping does not change when this flips — only capture/playback.
 */
export const AUDIO_IO = {
  mic: 'phone',
  speaker: 'glasses',
}

export function isPhoneMic() {
  return AUDIO_IO.mic === 'phone'
}

export function isPhoneSpeaker() {
  return AUDIO_IO.speaker === 'phone'
}
