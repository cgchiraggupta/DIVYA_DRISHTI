/**
 * @typedef {Object} Destination
 * @property {string} label       Display name (e.g. "India Gate, New Delhi")
 * @property {number} lat
 * @property {number} lng
 */

/** @returns {Destination} */
export function createDestination(label, lat, lng) {
  return { label, lat, lng }
}
