import { Capacitor } from '@capacitor/core'
import { Geolocation } from '@capacitor/geolocation'

let watchId = null

/**
 * Ask for location permission (native only -- browsers prompt on first watch call).
 */
export async function ensureLocationPermission() {
  if (!Capacitor.isNativePlatform()) return true
  const status = await Geolocation.checkPermissions()
  if (status.location === 'granted') return true
  const requested = await Geolocation.requestPermissions()
  return requested.location === 'granted'
}

/**
 * Start watching device position. Calls onPosition({lat, lng, heading, speed})
 * on every update; onError(error) if the watch itself fails.
 * @returns {() => void} stop function
 */
export async function startWatchingPosition(onPosition, onError) {
  await stopWatchingPosition()

  watchId = await Geolocation.watchPosition(
    { enableHighAccuracy: true, timeout: 10_000 },
    (position, error) => {
      if (error) {
        onError?.(error)
        return
      }
      if (!position) return
      onPosition({
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        heading: position.coords.heading ?? null,
        speed: position.coords.speed ?? null,
      })
    },
  )

  return stopWatchingPosition
}

export async function stopWatchingPosition() {
  if (watchId == null) return
  try {
    await Geolocation.clearWatch({ id: watchId })
  } catch {
    // ignore cleanup errors
  }
  watchId = null
}

export async function getCurrentPosition() {
  const position = await Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 10_000 })
  return {
    lat: position.coords.latitude,
    lng: position.coords.longitude,
  }
}

/** Haversine distance in meters. */
export function distanceMeters(a, b) {
  const R = 6371000
  const toRad = (deg) => (deg * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const lat1 = toRad(a.lat)
  const lat2 = toRad(b.lat)
  const sinDLat = Math.sin(dLat / 2)
  const sinDLng = Math.sin(dLng / 2)
  const h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}
