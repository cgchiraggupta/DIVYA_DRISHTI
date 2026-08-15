/**
 * Phone-local obstacle history (photos + Hindi text).
 * Kept on-device so large snapshots don't depend on cloud row size.
 */

const STORAGE_KEY = 'divyadrishti-obstacle-history'
const MAX_ITEMS = 40

export function loadObstacleHistory() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveObstacleHistoryItem(item) {
  const next = [
    {
      id: item.id || `obs-${Date.now()}`,
      created_at: item.created_at || new Date().toISOString(),
      event_type: item.event_type || 'obstacle_ahead',
      direction: item.direction || 'ahead',
      distance_mm: item.distance_mm ?? null,
      speak_hi: item.speak_hi || item.text_hi || '',
      image_jpeg_b64: item.image_jpeg_b64 || '',
      source: item.source || 'glasses',
    },
    ...loadObstacleHistory().filter((row) => row.id !== item.id),
  ].slice(0, MAX_ITEMS)

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // If storage is full, drop images from older rows and retry once.
    const slim = next.map((row, index) => (index < 8 ? row : { ...row, image_jpeg_b64: '' }))
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
    } catch {
      // ignore
    }
  }
  return next
}
