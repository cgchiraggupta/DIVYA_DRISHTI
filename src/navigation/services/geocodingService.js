/**
 * OpenRouteService geocoding: place name -> lat/lng.
 * Prototype: key from VITE_ORS_API_KEY. Move to an edge proxy before public release
 * (same caveat as sarvamTts.js -- do not ship a client-embedded key to production).
 */
import { createDestination } from '../models/Destination'

const GEOCODE_URL = 'https://api.openrouteservice.org/geocode/search'

function apiKey() {
  return import.meta.env.VITE_ORS_API_KEY?.trim() || ''
}

export function isGeocodingConfigured() {
  return Boolean(apiKey())
}

/**
 * @param {string} placeName
 * @returns {Promise<import('../models/Destination').Destination|null>}
 */
export async function geocodePlace(placeName) {
  const key = apiKey()
  if (!key || !placeName?.trim()) return null

  const url = new URL(GEOCODE_URL)
  url.searchParams.set('api_key', key)
  url.searchParams.set('text', placeName.trim())
  url.searchParams.set('size', '1')

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8_000)
  let response
  try {
    response = await fetch(url.toString(), { signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Geocoding failed (${response.status})${detail ? `: ${detail.slice(0, 120)}` : ''}`)
  }

  const payload = await response.json()
  const feature = payload?.features?.[0]
  if (!feature) return null

  const [lng, lat] = feature.geometry.coordinates
  const label = feature.properties?.label || placeName.trim()
  return createDestination(label, lat, lng)
}
