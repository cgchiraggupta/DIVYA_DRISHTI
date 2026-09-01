/**
 * @typedef {Object} RouteStep
 * @property {string} instruction   Human-readable step text (from OpenRouteService)
 * @property {number} distanceM     Length of this step, meters
 * @property {number} durationS     Expected duration, seconds
 * @property {[number, number]} location  [lng, lat] where this step starts
 */

/**
 * @typedef {Object} Route
 * @property {RouteStep[]} steps
 * @property {number} distanceM     Total route distance, meters
 * @property {number} durationS     Total expected duration, seconds
 * @property {[number, number][]} coordinates  Full [lng, lat] polyline
 */

/** @returns {RouteStep} */
export function createRouteStep(instruction, distanceM, durationS, location) {
  return { instruction, distanceM, durationS, location }
}
