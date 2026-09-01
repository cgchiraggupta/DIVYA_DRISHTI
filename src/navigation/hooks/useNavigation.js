import { useCallback, useEffect, useRef, useState } from 'react'
import { NavigationController } from '../controllers/NavigationController'
import { createInitialNavState } from '../models/NavState'

/**
 * React adapter over NavigationController -- keeps the controller
 * framework-agnostic (testable without React) while giving views normal
 * state + actions.
 */
export function useNavigation(pairingCode) {
  const [state, setState] = useState(createInitialNavState)
  const controllerRef = useRef(null)
  const pairingCodeRef = useRef(pairingCode)
  pairingCodeRef.current = pairingCode

  if (!controllerRef.current) {
    // Barge-in during a step announcement: the user's words are handed
    // straight back into navigateTo as a new request (e.g. "actually take
    // me to Connaught Place instead"), same pattern as useVoiceCommands'
    // interruptedWith handling -- no need to reopen a separate listen step.
    controllerRef.current = new NavigationController(setState, (matches) => {
      const query = matches?.[0]
      if (query) controllerRef.current.navigateTo(pairingCodeRef.current, query)
    })
  }

  useEffect(() => {
    const controller = controllerRef.current
    return () => {
      controller.stop()
    }
  }, [])

  const navigateTo = useCallback(
    (query, preExtracted) => controllerRef.current.navigateTo(pairingCode, query, preExtracted),
    [pairingCode],
  )

  const reset = useCallback(() => controllerRef.current.reset(), [])

  return { state, navigateTo, reset }
}
