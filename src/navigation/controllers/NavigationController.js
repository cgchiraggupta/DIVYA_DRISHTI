import { createInitialNavState } from '../models/NavState'
import { extractDestination } from '../services/destinationExtractor'
import { geocodePlace } from '../services/geocodingService'
import { fetchWalkingRoute } from '../services/routingService'
import {
  ensureLocationPermission,
  getCurrentPosition,
  startWatchingPosition,
  stopWatchingPosition,
  distanceMeters,
} from '../services/gpsTrackerService'
import { announceStep } from '../services/navigationSpeech'
import { setNavigatingActive } from '../navActiveFlag'

// Once the walker is within this many meters of a step's start point, that
// step is considered reached and the next instruction is spoken.
const STEP_ARRIVAL_RADIUS_M = 15
// Within this radius of the final destination coordinate, navigation ends.
const DESTINATION_ARRIVAL_RADIUS_M = 20
// Matches gemini-navigate's MAX_HISTORY_TURNS.
const MAX_HISTORY_TURNS = 10

/**
 * Orchestrates "Take me to <place>" end-to-end: Gemini extraction ->
 * geocoding -> routing -> GPS-driven step advancement -> spoken guidance.
 * Framework-agnostic; src/navigation/hooks/useNavigation.js adapts this to
 * React state for the view layer.
 */
export class NavigationController {
  /**
   * @param {(state: import('../models/NavState').NavState) => void} onStateChange
   * @param {(matches: string[]) => void} [onInterrupted]  called with the
   *   user's words the moment a spoken announcement is barged into, so the
   *   caller can act on it immediately (e.g. re-run navigateTo with a new
   *   destination) instead of waiting for the announcement to finish.
   */
  constructor(onStateChange, onInterrupted) {
    this.state = createInitialNavState()
    this.onStateChange = onStateChange
    this.onInterrupted = onInterrupted
    this._stopWatch = null
    // Turns in this navigation session ("take me to X" -> extracted
    // destination), so a follow-up like "actually go to Y instead" resolves
    // against what was already said, same pattern as divya-chat's history.
    this._history = []
  }

  _setState(patch) {
    this.state = { ...this.state, ...patch }
    if (patch.phase) {
      // Only 'navigating' should mute ambient obstacle speech -- typing a
      // destination, extracting/geocoding/routing, arrived, and error all
      // leave it un-muted.
      setNavigatingActive(patch.phase === 'navigating')
    }
    this.onStateChange(this.state)
  }

  _remember(userText, modelText) {
    this._history = [
      ...this._history,
      { role: 'user', text: userText },
      { role: 'model', text: modelText },
    ].slice(-MAX_HISTORY_TURNS * 2)
  }

  /**
   * Run the full flow for a spoken/typed command.
   * @param {string} pairingCode
   * @param {string} query  e.g. "Take me to India Gate"
   * @param {{status: string, destination: string}} [preExtracted]  skip the
   *   extraction call when the caller already ran it (useVoiceCommands.js
   *   checks navigation intent before falling back to Divya-chat, so the
   *   same Gemini call is reused here instead of asking twice)
   */
  async navigateTo(pairingCode, query, preExtracted) {
    this._setState({ phase: 'extracting', query, error: null })

    const extracted = preExtracted || (await extractDestination(pairingCode, query, this._history))
    if (extracted.status !== 'ok' || !extracted.destination) {
      this._setState({ phase: 'error', error: extracted.error || 'Could not understand the destination' })
      return
    }
    this._remember(query, extracted.destination)

    this._setState({ phase: 'geocoding' })
    let destination
    try {
      destination = await geocodePlace(extracted.destination)
    } catch (error) {
      this._setState({ phase: 'error', error: String(error?.message || error) })
      return
    }
    if (!destination) {
      this._setState({ phase: 'error', error: `Could not find "${extracted.destination}"` })
      return
    }
    this._setState({ destination })

    const granted = await ensureLocationPermission()
    if (!granted) {
      this._setState({ phase: 'error', error: 'Location permission denied' })
      return
    }

    this._setState({ phase: 'routing' })
    let origin
    try {
      origin = await getCurrentPosition()
    } catch (error) {
      this._setState({ phase: 'error', error: `Could not get current location: ${String(error?.message || error)}` })
      return
    }

    let route
    try {
      route = await fetchWalkingRoute(origin, destination)
    } catch (error) {
      this._setState({ phase: 'error', error: String(error?.message || error) })
      return
    }

    this._setState({
      phase: 'navigating',
      route,
      currentStepIndex: 0,
      currentPosition: origin,
    })

    const firstStep = route.steps[0]
    if (firstStep) this._announce(firstStep.instruction)

    this._stopWatch = await startWatchingPosition(
      (position) => this._onPosition(position, destination),
      (error) => this._setState({ phase: 'error', error: String(error?.message || error) }),
    )
  }

  /**
   * Speak one announcement; if the user barges in, hand their words to
   * onInterrupted instead of letting the rest of the sentence keep playing.
   * Fire-and-forget by design -- GPS tracking must not pause for TTS.
   * Also logs the text immediately (not after speech finishes) so the
   * on-screen transcript matches what's being said even if the phone is
   * pocketed and no one sees it speak.
   */
  _announce(text) {
    this._setState({ spokenLog: [...this.state.spokenLog, { text, at: Date.now() }] })
    announceStep(text).then((result) => {
      if (result.interrupted && result.matches?.length) {
        this.onInterrupted?.(result.matches)
      }
    })
  }

  _onPosition(position, destination) {
    if (this.state.phase !== 'navigating') return
    this._setState({ currentPosition: position })

    const distanceToDestination = distanceMeters(position, destination)
    if (distanceToDestination <= DESTINATION_ARRIVAL_RADIUS_M) {
      this._announce('आप अपनी मंज़िल पर पहुँच गए हैं।')
      this._setState({ phase: 'arrived' })
      this.stop()
      return
    }

    const { route, currentStepIndex } = this.state
    const nextStep = route?.steps?.[currentStepIndex + 1]
    if (!nextStep) return

    const [lng, lat] = nextStep.location
    const distanceToNextStep = distanceMeters(position, { lat, lng })
    if (distanceToNextStep <= STEP_ARRIVAL_RADIUS_M) {
      this._setState({ currentStepIndex: currentStepIndex + 1 })
      this._announce(nextStep.instruction)
    }
  }

  async stop() {
    // Covers the unmount path (leaving the Navigate screen mid-route) too --
    // that must not leave obstacle speech muted forever.
    setNavigatingActive(false)
    await stopWatchingPosition()
    this._stopWatch = null
  }

  reset() {
    this.stop()
    this._history = []
    this._setState(createInitialNavState())
  }
}
