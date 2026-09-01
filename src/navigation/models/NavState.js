/**
 * @typedef {'idle'|'listening'|'extracting'|'geocoding'|'routing'|'navigating'|'arrived'|'error'} NavPhase
 *
 * @typedef {Object} NavState
 * @property {NavPhase} phase
 * @property {string} query              Raw user command text
 * @property {import('./Destination').Destination|null} destination
 * @property {import('./RouteStep').Route|null} route
 * @property {number} currentStepIndex
 * @property {{lat:number, lng:number}|null} currentPosition
 * @property {string|null} error
 * @property {{text: string, at: number}[]} spokenLog  every instruction
 *   announced so far this session, oldest first -- shown as an on-screen
 *   transcript of what's being said, since the phone may be pocketed.
 */

/** @returns {NavState} */
export function createInitialNavState() {
  return {
    phase: 'idle',
    query: '',
    destination: null,
    route: null,
    currentStepIndex: 0,
    currentPosition: null,
    error: null,
    spokenLog: [],
  }
}
