import { useCallback, useEffect, useRef, useState } from 'react'
import { formatDistanceMeters } from '../lib/format'
import { getLastSpokenText, speakGuidance, stopSpeech, tapFeedback } from '../services/sensoryFeedback'
import { listenForSpeech, playListenCue, stopListening } from '../services/phoneSpeech'
import { helpSpeech, pickVoiceIntent } from '../services/voiceIntents'
import { askDivya } from '../services/divyaChat'
import { speakWithBargeIn } from '../services/bargeIn'
import { extractDestination } from '../navigation/services/destinationExtractor'

const WAIT_SPEAK = 'थोड़ा रुकिए, अभी एक काम चल रहा है।'
const NO_DISTANCE_SPEAK = 'अभी दूरी नहीं मिली। थोड़ा चलिए, फिर पूछिए कितनी दूर।'
// Matches divya-chat's MAX_HISTORY_TURNS — keep the client-side cap in sync
// with what the server actually keeps.
const MAX_CHAT_HISTORY_TURNS = 10

export function useVoiceCommands({
  runVision,
  sendNearbyDeviceCommand,
  nearbyControlAvailable,
  getDistanceMm,
  describePending,
  commandPending,
  pairingCode,
  // Shared NavigationController's navigateTo + a screen switch, so a spoken
  // "take me to X" from anywhere (button wake included) actually starts a
  // route instead of falling through to a generic Divya-chat reply that
  // doesn't know navigation exists -- see NavigationSessionContext.
  navigateTo,
  goToNavigateScreen,
}) {
  const [listening, setListening] = useState(false)
  const [handsFree, setHandsFree] = useState(false)
  const [busy, setBusy] = useState(false)
  // True only while a Divya reply is actively playing (not during capture or
  // thinking) -- lets the UI offer tap-to-interrupt instead of a disabled
  // button for that window.
  const [speaking, setSpeaking] = useState(false)
  const [status, setStatus] = useState({ message: '', error: '', transcript: '' })

  const handsFreeRef = useRef(false)
  const listeningRef = useRef(false)
  const mountedRef = useRef(true)
  const loopRef = useRef(0)
  // Chat context for the current back-and-forth with Divya. Cleared whenever
  // a fresh top-level listen starts (button/tap or hands-free turning on),
  // not on each recursive listenAgain -- that's what keeps one conversation
  // coherent while still starting clean each time the user re-engages.
  const chatHistoryRef = useRef([])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      handsFreeRef.current = false
      listeningRef.current = false
      stopListening()
    }
  }, [])

  const setSafeStatus = useCallback((next) => {
    if (mountedRef.current) setStatus(next)
  }, [])

  const executeIntent = useCallback(async (mapped) => {
    switch (mapped.intent) {
      case 'describe':
        if (describePending || commandPending) {
          await speakGuidance(WAIT_SPEAK, 1, { fast: true })
          return { ok: false }
        }
        await speakGuidance('देख रही हूँ।', 1, { fast: true })
        await runVision('describe')
        return { ok: true }
      case 'read':
        if (describePending || commandPending) {
          await speakGuidance(WAIT_SPEAK, 1, { fast: true })
          return { ok: false }
        }
        await speakGuidance('पढ़ रही हूँ।', 1, { fast: true })
        await runVision('read')
        return { ok: true }
      case 'distance': {
        const mm = getDistanceMm?.()
        const label = formatDistanceMeters(mm)
        const line = label === '—' ? NO_DISTANCE_SPEAK : `आगे ${label} है।`
        await speakGuidance(line, 1, { fast: true })
        return { ok: true }
      }
      case 'pause':
        if (!nearbyControlAvailable) {
          await speakGuidance('चश्मा पास के Wi-Fi पर नहीं मिला।', 1, { fast: true })
          return { ok: false }
        }
        await sendNearbyDeviceCommand('pause')
        await speakGuidance('सेंसिंग बंद है।', 1, { fast: true })
        return { ok: true }
      case 'resume':
        if (!nearbyControlAvailable) {
          await speakGuidance('चश्मा पास के Wi-Fi पर नहीं मिला।', 1, { fast: true })
          return { ok: false }
        }
        await sendNearbyDeviceCommand('resume')
        await speakGuidance('सेंसिंग चालू है।', 1, { fast: true })
        return { ok: true }
      case 'stop_speech':
        await stopSpeech()
        return { ok: true }
      case 'repeat': {
        const last = getLastSpokenText()
        if (!last) {
          await speakGuidance('अभी दोहराने के लिए कुछ नहीं है।', 1, { fast: true })
          return { ok: false }
        }
        await speakGuidance(last)
        return { ok: true }
      }
      case 'help':
        await speakGuidance(helpSpeech(), 1, { fast: true })
        return { ok: true }
      case 'await_command':
        await speakGuidance('कहिए।', 1, { fast: true })
        return { ok: true, listenAgain: true, requireWake: false }
      case 'ignored':
        return { ok: true, silent: true }
      default: {
        // Anything that doesn't match a fixed command goes to Divya as a
        // real question instead of a dead-end "didn't understand" -- the
        // conversation then keeps listening for a reply, turn after turn,
        // until the user goes quiet or says a fixed command instead.
        const question = mapped.remainder || mapped.transcript
        if (!question) {
          await speakGuidance('कुछ सुनाई नहीं दिया।', 1, { fast: true })
          return { ok: false }
        }

        // Check navigation before Divya-chat -- a blind user speaks a
        // destination directly ("India Gate le chalo"), never opens a
        // screen or types anything. gemini-navigate returns 'not_found' for
        // anything that isn't an actual travel request, so this safely
        // falls through to the normal conversation below for everything
        // else -- one Gemini call either way, no separate classifier needed.
        if (navigateTo) {
          const navCheck = await extractDestination(pairingCode, question)
          if (navCheck.status === 'ok' && navCheck.destination) {
            goToNavigateScreen?.()
            navigateTo(question, navCheck)
            return { ok: true }
          }
        }

        const result = await askDivya(pairingCode, question, chatHistoryRef.current)
        if (result.ok) {
          chatHistoryRef.current = [
            ...chatHistoryRef.current,
            { role: 'user', text: question },
            { role: 'model', text: result.reply },
          ].slice(-MAX_CHAT_HISTORY_TURNS * 2)
        }
        // Barge-in: if the user starts talking while the reply is still
        // playing, cut it off immediately and treat what they said as the
        // next turn -- no need to wait for the reply to finish or re-open
        // the mic separately. `speaking` also drives tap-to-interrupt on
        // platforms where continuous listening isn't available.
        if (mountedRef.current) setSpeaking(true)
        const spoken = await speakWithBargeIn(() => speakGuidance(result.reply, 1, { fast: true }))
        if (mountedRef.current) setSpeaking(false)
        if (spoken.interrupted) {
          return { ok: result.ok, listenAgain: false, requireWake: false, interruptedWith: spoken.matches }
        }
        return { ok: result.ok, listenAgain: result.ok, requireWake: false }
      }
    }
  }, [commandPending, describePending, getDistanceMm, goToNavigateScreen, navigateTo, nearbyControlAvailable, runVision, sendNearbyDeviceCommand])

  const captureAndRun = useCallback(async ({ requireWake, prefetchedMatches } = {}) => {
    let matches = prefetchedMatches
    if (!matches) {
      await stopSpeech()
      await playListenCue()
      matches = await listenForSpeech()
    }
    const mapped = pickVoiceIntent(matches, { requireWake })
    setSafeStatus({
      message: mapped.intent === 'ignored' ? 'Waiting for Hey Divya.' : '',
      error: '',
      transcript: mapped.transcript,
    })
    if (!mapped.transcript && mapped.intent === 'empty') {
      if (!requireWake) await speakGuidance('सुनाई नहीं दी। फिर से बोलिए।', 1, { fast: true })
      return mapped
    }
    const result = await executeIntent(mapped)
    // Interrupted mid-reply: the user's own words are already in hand, so
    // go straight to that turn instead of stopping to listen again.
    if (result?.interruptedWith) {
      return captureAndRun({ requireWake: false, prefetchedMatches: result.interruptedWith })
    }
    if (result?.listenAgain) {
      return captureAndRun({ requireWake: false })
    }
    return mapped
  }, [executeIntent, setSafeStatus])

  const listenOnce = useCallback(async () => {
    // Tap-to-interrupt: while Divya is only speaking (not actively
    // capturing), tapping Listen stops her immediately and starts a fresh
    // capture, instead of being disabled until she finishes. Still refuses
    // to double-start over an in-progress capture.
    if (listeningRef.current) return
    if (busy && !speaking) return
    const wasInterrupt = speaking
    if (wasInterrupt) await stopSpeech()
    listeningRef.current = true
    setListening(true)
    setBusy(true)
    setSpeaking(false)
    setSafeStatus({ message: 'Listening…', error: '', transcript: '' })
    tapFeedback()
    // A fresh top-level tap starts a clean conversation; interrupting an
    // in-progress reply keeps history so the exchange stays coherent.
    if (!wasInterrupt) chatHistoryRef.current = []
    try {
      await captureAndRun({ requireWake: false })
    } catch (error) {
      const message = error?.message || ''
      setSafeStatus({ message: '', error: message || 'Could not hear you.', transcript: '' })
      // Native STT rejects for many reasons ("No match", a timeout, a busy
      // recognizer) that have nothing to do with permission -- only blame
      // permission when the error actually says so, instead of guessing wrong.
      const spoken = /permission/i.test(message)
        ? 'माइक नहीं खुल सका। फोन की अनुमति दें।'
        : /no match|timeout/i.test(message)
          ? 'सुनाई नहीं दी। फिर से बोलिए।'
          : 'अभी सुन नहीं पाए। फिर कोशिश करें।'
      await speakGuidance(spoken, 1, { fast: true }).catch(() => {})
    } finally {
      listeningRef.current = false
      if (mountedRef.current) {
        setListening(false)
        setBusy(false)
        setStatus((prev) => (prev.message === 'Listening…' ? { ...prev, message: '' } : prev))
      }
    }
  }, [busy, speaking, captureAndRun, setSafeStatus])

  const runHandsFreeLoop = useCallback(async (token) => {
    while (mountedRef.current && handsFreeRef.current && loopRef.current === token) {
      if (listeningRef.current) {
        await new Promise((resolve) => window.setTimeout(resolve, 400))
        continue
      }
      listeningRef.current = true
      if (mountedRef.current) setListening(true)
      chatHistoryRef.current = []
      try {
        await captureAndRun({ requireWake: true })
      } catch {
        await new Promise((resolve) => window.setTimeout(resolve, 800))
      } finally {
        listeningRef.current = false
        if (mountedRef.current) setListening(false)
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500))
    }
  }, [captureAndRun])

  const toggleHandsFree = useCallback(async () => {
    if (handsFreeRef.current) {
      handsFreeRef.current = false
      setHandsFree(false)
      loopRef.current += 1
      await stopListening()
      setSafeStatus({ message: 'Hands-free off.', error: '', transcript: '' })
      return
    }
    handsFreeRef.current = true
    setHandsFree(true)
    setSafeStatus({ message: 'Say Hey Divya, then a command.', error: '', transcript: '' })
    tapFeedback()
    const token = loopRef.current + 1
    loopRef.current = token
    runHandsFreeLoop(token)
  }, [runHandsFreeLoop, setSafeStatus])

  return {
    listening,
    handsFree,
    busy,
    speaking,
    status,
    listenOnce,
    toggleHandsFree,
  }
}
