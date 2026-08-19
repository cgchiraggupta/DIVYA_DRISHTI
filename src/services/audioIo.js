/**
 * Where mic and speaker live right now.
 *
 * Phone Google STT + phone TTS are the stand-in until the glasses I²S
 * mic (INMP441) and speaker (MAX98357A) are verified by hardware.
 * Intent mapping does not change when this flips — only capture/playback.
 *
 * Set either field to 'glasses' only after that hardware path works.
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
