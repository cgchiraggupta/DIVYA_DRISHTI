/**
 * Whether a route is actively being followed right now (phase 'navigating').
 * Plain module state, not React context -- DeviceContext.jsx (outside the
 * navigation/ folder) needs to read this to mute ambient obstacle-alert
 * speech while turn-by-turn directions are being spoken, without the two
 * features depending on each other's React trees. Directions still speak
 * through their own path (navigationSpeech.js); this only gates the
 * glasses' passive obstacle narration. Beep/vibration are unaffected --
 * those come from the glasses' own motors, not this phone.
 */
let active = false

export function setNavigatingActive(value) {
  active = Boolean(value)
}

export function isNavigatingActive() {
  return active
}
