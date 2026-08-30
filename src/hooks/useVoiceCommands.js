import { useCallback, useEffect, useRef, useState } from 'react'
import { formatDistanceMeters } from '../lib/format'
import { getLastSpokenText, speakGuidance, stopSpeech, tapFeedback } from '../services/sensoryFeedback'
import { listenForSpeech, playListenCue, stopListening } from '../services/phoneSpeech'
import { helpSpeech, pickVoiceIntent } from '../services/voiceIntents'

const UNKNOWN_SPEAK = 'समझ नहीं आई। कहिए आगे क्या है, पढ़ो, कितनी दूर, या मदद।'
const WAIT_SPEAK = 'थोड़ा रुकिए, अभी एक काम चल रहा है।'
const NO_DISTANCE_SPEAK = 'अभी दूरी नहीं मिली। थोड़ा चलिए, फिर पूछिए कितनी दूर।'

export function useVoiceCommands({
  runVision,
  sendNearbyDeviceCommand,
  nearbyControlAvailable,
  getDistanceMm,
  describePending,
  commandPending,
}) {
  const [listening, setListening] = useState(false)
  const [handsFree, setHandsFree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState({ message: '', error: '', transcript: '' })

  const handsFreeRef = useRef(false)
  const listeningRef = useRef(false)
  const mountedRef = useRef(true)
  const loopRef = useRef(0)

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
      default:
        await speakGuidance(UNKNOWN_SPEAK, 1, { fast: true })
        return { ok: false }
    }
  }, [commandPending, describePending, getDistanceMm, nearbyControlAvailable, runVision, sendNearbyDeviceCommand])

  const captureAndRun = useCallback(async ({ requireWake } = {}) => {
    await stopSpeech()
    await playListenCue()
    const matches = await listenForSpeech()
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
    if (result?.listenAgain) {
      return captureAndRun({ requireWake: false })
    }
    return mapped
  }, [executeIntent, setSafeStatus])

  const listenOnce = useCallback(async () => {
    if (listeningRef.current || busy) return
    listeningRef.current = true
    setListening(true)
    setBusy(true)
    setSafeStatus({ message: 'Listening…', error: '', transcript: '' })
    tapFeedback()
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
  }, [busy, captureAndRun, setSafeStatus])

  const runHandsFreeLoop = useCallback(async (token) => {
    while (mountedRef.current && handsFreeRef.current && loopRef.current === token) {
      if (listeningRef.current) {
        await new Promise((resolve) => window.setTimeout(resolve, 400))
        continue
      }
      listeningRef.current = true
      if (mountedRef.current) setListening(true)
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
    status,
    listenOnce,
    toggleHandsFree,
  }
}
