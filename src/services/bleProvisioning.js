import { BleClient, dataViewToText, numbersToDataView } from '@capacitor-community/bluetooth-le'
import { Capacitor } from '@capacitor/core'

// Must match setup/hardware-integration/divyadrishti-ble-provisioner.py.
const SERVICE_UUID = '5f3e0001-2a11-4b0e-9c3a-1f2e3d4c5b6a'
const RX_CHRC_UUID = '5f3e0002-2a11-4b0e-9c3a-1f2e3d4c5b6a'
const COMMIT_CHRC_UUID = '5f3e0003-2a11-4b0e-9c3a-1f2e3d4c5b6a'
const STATUS_CHRC_UUID = '5f3e0004-2a11-4b0e-9c3a-1f2e3d4c5b6a'
const PAIRING_CODE_CHRC_UUID = '5f3e0005-2a11-4b0e-9c3a-1f2e3d4c5b6a'

// Conservative chunk size: fits inside the 23-byte default ATT MTU (20 usable)
// so provisioning works before any MTU negotiation.
const CHUNK_BYTES = 18
const JOIN_TIMEOUT_MS = 35_000

export function isBleSupported() {
  return Capacitor.isNativePlatform()
}

/**
 * Provision the glasses' home Wi-Fi over BLE.
 *
 * @param {{ ssid: string, password: string, pairingCode: string,
 *           onStatus?: (state: string) => void }} params
 * @returns {Promise<void>} resolves once the glasses report `connected`.
 */
export async function provisionOverBle({ ssid, password, pairingCode, onStatus }) {
  if (!isBleSupported()) {
    throw new Error('Bluetooth setup is only available in the installed app.')
  }

  const report = (state) => { if (onStatus) onStatus(state) }
  let deviceId = null

  await BleClient.initialize({ androidNeverForLocation: true })
  if (!(await BleClient.isEnabled())) {
    // Prompts the user to turn Bluetooth on (Android); throws if declined.
    await BleClient.requestEnable()
  }

  report('scanning')
  const device = await BleClient.requestDevice({ services: [SERVICE_UUID] })
  deviceId = device.deviceId

  try {
    report('connecting')
    await BleClient.connect(deviceId, () => report('disconnected'))
    // Watch status before committing so we never miss the transition.
    const status = subscribeStatus(deviceId, report)
    // BlueZ can complete the nmcli join quickly (or reject invalid input) after
    // the commit write. Do not send credentials until Android has finished
    // enabling notifications, otherwise its terminal state can be lost.
    await status.ready

    const payload = JSON.stringify({ code: pairingCode, ssid, password })
    await writeChunked(deviceId, payload)

    report('saving')
    await BleClient.write(deviceId, SERVICE_UUID, COMMIT_CHRC_UUID, numbersToDataView([1]))

    await status.completion
  } finally {
    if (deviceId) {
      try { await BleClient.stopNotifications(deviceId, SERVICE_UUID, STATUS_CHRC_UUID) } catch { /* ignore */ }
      try { await BleClient.disconnect(deviceId) } catch { /* ignore */ }
    }
  }
}

/**
 * Read the glasses' Supabase claim code directly over BLE. The Pi has no
 * speaker, so this is how the phone learns the code instead of it being
 * spoken aloud -- used on the Pairing screen as an alternative to typing
 * the code in by hand.
 *
 * @returns {Promise<string>} the claim code, or throws if the glasses
 *   haven't registered one yet (e.g. no internet on their first boot).
 */
export async function readPairingCodeOverBle() {
  if (!isBleSupported()) {
    throw new Error('Bluetooth setup is only available in the installed app.')
  }

  await BleClient.initialize({ androidNeverForLocation: true })
  if (!(await BleClient.isEnabled())) {
    await BleClient.requestEnable()
  }

  const device = await BleClient.requestDevice({ services: [SERVICE_UUID] })
  const deviceId = device.deviceId
  try {
    await BleClient.connect(deviceId)
    const value = await BleClient.read(deviceId, SERVICE_UUID, PAIRING_CODE_CHRC_UUID)
    const code = dataViewToText(value).trim().toUpperCase()
    if (!code) throw new Error('The glasses have not registered a pairing code yet.')
    return code
  } finally {
    try { await BleClient.disconnect(deviceId) } catch { /* ignore */ }
  }
}

async function writeChunked(deviceId, text) {
  const bytes = new TextEncoder().encode(text)
  for (let offset = 0; offset < bytes.length; offset += CHUNK_BYTES) {
    const slice = bytes.subarray(offset, offset + CHUNK_BYTES)
    const view = new DataView(slice.buffer, slice.byteOffset, slice.byteLength)
    await BleClient.write(deviceId, SERVICE_UUID, RX_CHRC_UUID, view)
  }
}

/**
 * Resolves when the glasses report `connected`, rejects on any `error:*` state
 * or timeout. Status strings mirror the Pi provisioner.
 */
function subscribeStatus(deviceId, report) {
  let resolveReady
  let rejectReady
  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve
    rejectReady = reject
  })
  const completion = new Promise((resolve, reject) => {
    let settled = false
    const finish = (fn, arg) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      fn(arg)
    }

    const timer = setTimeout(
      () => finish(reject, new Error('The glasses did not confirm the network in time.')),
      JOIN_TIMEOUT_MS,
    )

    BleClient.startNotifications(deviceId, SERVICE_UUID, STATUS_CHRC_UUID, (value) => {
      const state = dataViewToText(value)
      report(state)
      if (state === 'connected') finish(resolve)
      else if (state.startsWith('error:')) finish(reject, new Error(errorMessage(state)))
    }).then(resolveReady).catch((error) => {
      finish(reject, error)
      rejectReady(error)
    })
  })
  // `ready` may fail before the caller awaits `completion`; attach a handler
  // now so the same failure is not reported as an unhandled rejection.
  completion.catch(() => {})
  return { ready, completion }
}

function errorMessage(state) {
  switch (state) {
    case 'error:pairing': return 'Pairing code did not match the glasses.'
    case 'error:ssid': return 'That Wi-Fi name is not valid.'
    case 'error:password': return 'Wi-Fi password must be 8 to 63 characters.'
    case 'error:join-failed': return 'The glasses could not join that network. Check the name and password.'
    default: return 'The glasses could not save this Wi-Fi network.'
  }
}
