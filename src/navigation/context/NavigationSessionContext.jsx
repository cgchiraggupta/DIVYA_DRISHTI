import { createContext, useContext } from 'react'
import { useNavigation } from '../hooks/useNavigation'
import { useDevice } from '../../context/DeviceContext'

const NavigationSessionContext = createContext(undefined)

/**
 * One shared NavigationController instance for the whole app, not one per
 * page. Without this, a voice-triggered "take me to X" from Dashboard (via
 * useVoiceCommands) would create its own controller that Navigate.jsx never
 * sees, so the screen would show nothing even though a route was started.
 * Provided once at the App root, inside DeviceProvider.
 */
export function NavigationSessionProvider({ children }) {
  const { device } = useDevice()
  const session = useNavigation(device?.pairing_code)
  return (
    <NavigationSessionContext.Provider value={session}>
      {children}
    </NavigationSessionContext.Provider>
  )
}

export function useNavigationSession() {
  const ctx = useContext(NavigationSessionContext)
  if (ctx === undefined) throw new Error('useNavigationSession must be used within NavigationSessionProvider')
  return ctx
}
