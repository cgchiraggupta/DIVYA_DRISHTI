const minutesAgo = (minutes) => new Date(Date.now() - minutes * 60_000).toISOString()

export const demoUser = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'demo@divyadrishti.local',
}

export const demoDevice = {
  id: '00000000-0000-4000-8000-000000000101',
  name: 'Divya Drishti',
  pairing_code: 'DEMO01',
  paired_at: minutesAgo(1_440),
  last_seen_at: new Date().toISOString(),
}

export const demoStatus = {
  device_id: demoDevice.id,
  battery_pct: 82,
  tof_left_ok: true,
  tof_right_ok: true,
  camera_ok: true,
  mic_ok: true,
  mode: 'tof',
  current_alert: 'path_clear',
  updated_at: new Date().toISOString(),
}

export const demoEvents = [
  {
    id: 1,
    device_id: demoDevice.id,
    event_type: 'path_clear',
    detail: {
      message: 'Path ahead is clear.',
      speak_hi: 'रास्ता साफ़ है। आप आराम से आगे बढ़ सकते हैं।',
    },
    created_at: minutesAgo(1),
  },
  {
    id: 2,
    device_id: demoDevice.id,
    event_type: 'obstacle_ahead',
    detail: {
      distance_mm: 620,
      object_label: 'Chair',
      direction: 'ahead',
      speak_hi: 'सामने कुर्सी है। लगभग 60 cm।',
    },
    created_at: minutesAgo(4),
  },
  {
    id: 3,
    device_id: demoDevice.id,
    event_type: 'voice_command',
    detail: {
      command: 'what is ahead',
      response: 'Chair ahead, about 60 centimetres away.',
      speak_hi: 'सामने कुर्सी है। लगभग 60 cm।',
    },
    created_at: minutesAgo(9),
  },
]

export const previewScenes = [
  {
    id: 'clear',
    label: 'Clear path',
    event_type: 'path_clear',
    title: 'Path ahead is clear',
    message: 'You can continue comfortably.',
    speak_hi: 'रास्ता साफ़ है। आप आराम से आगे बढ़ सकते हैं।',
    detail: { message: 'Path ahead is clear.', speak_hi: 'रास्ता साफ़ है। आप आराम से आगे बढ़ सकते हैं।' },
  },
  {
    id: 'chair',
    label: 'Object ahead',
    event_type: 'obstacle_ahead',
    title: 'Chair ahead',
    message: 'About 60 centimetres away.',
    speak_hi: 'सामने कुर्सी है। लगभग 60 cm।',
    detail: { object_label: 'Chair', distance_mm: 620, direction: 'ahead', speak_hi: 'सामने कुर्सी है। लगभग 60 cm।' },
  },
  {
    id: 'right',
    label: 'Right-side alert',
    event_type: 'obstacle_right',
    title: 'Obstacle on your right',
    message: 'About 80 centimetres away.',
    speak_hi: 'दाईं ओर बाधा है। लगभग 80 cm।',
    detail: { distance_mm: 800, direction: 'right', speak_hi: 'दाईं ओर बाधा है। लगभग 80 cm।' },
  },
  {
    id: 'ground',
    label: 'Uneven ground',
    event_type: 'uneven_ground',
    title: 'Uneven ground ahead',
    message: 'Please take care with your next step.',
    speak_hi: 'आगे जमीन ऊबड़-खाबड़ है। सावधानी से कदम बढ़ाएँ।',
    detail: { distance_mm: 450, speak_hi: 'आगे जमीन ऊबड़-खाबड़ है। सावधानी से कदम बढ़ाएँ।' },
  },
]

export function createDemoEvent(scene) {
  return {
    id: `demo-${Date.now()}`,
    device_id: demoDevice.id,
    event_type: scene.event_type,
    detail: scene.detail,
    created_at: new Date().toISOString(),
  }
}

export function sceneSpeakText(scene) {
  return scene?.speak_hi || `${scene?.title || ''}. ${scene?.message || ''}`.trim()
}
