/**
 * OpenRouteService directions: origin + destination -> walking route + steps.
 * Prototype: key from VITE_ORS_API_KEY (see geocodingService.js caveat).
 */
import { createRouteStep } from '../models/RouteStep'

const DIRECTIONS_URL = 'https://api.openrouteservice.org/v2/directions/foot-walking/geojson'

function apiKey() {
  return import.meta.env.VITE_ORS_API_KEY?.trim() || ''
}

export function isRoutingConfigured() {
  return Boolean(apiKey())
}

/**
 * @param {{lat:number,lng:number}} origin
 * @param {import('../models/Destination').Destination} destination
 * @returns {Promise<import('../models/RouteStep').Route>}
 */
export async function fetchWalkingRoute(origin, destination) {
  const key = apiKey()
  if (!key) throw new Error('Routing is not configured (missing VITE_ORS_API_KEY)')

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10_000)
  let response
  try {
    response = await fetch(DIRECTIONS_URL, {
      method: 'POST',
      headers: {
        Authorization: key,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        coordinates: [
          [origin.lng, origin.lat],
          [destination.lng, destination.lat],
        ],
      }),
      signal: controller.signal,
    })
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Routing failed (${response.status})${detail ? `: ${detail.slice(0, 120)}` : ''}`)
  }

  const payload = await response.json()
  const feature = payload?.features?.[0]
  if (!feature) throw new Error('No route found')

  const summary = feature.properties?.summary || { distance: 0, duration: 0 }
  const coordinates = feature.geometry?.coordinates || []
  const segments = feature.properties?.segments || []

  const steps = segments.flatMap((segment) =>
    (segment.steps || []).map((step) => {
      const wayIndex = Array.isArray(step.way_points) ? step.way_points[0] : 0
      const location = coordinates[wayIndex] || coordinates[0] || [origin.lng, origin.lat]
      return createRouteStep(step.instruction, step.distance, step.duration, location)
    }),
  )

  return {
    steps,
    distanceM: summary.distance,
    durationS: summary.duration,
    coordinates,
  }
}
