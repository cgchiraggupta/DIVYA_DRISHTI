import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { matchVoiceIntent, pickVoiceIntent } from './voiceIntents.js'

describe('matchVoiceIntent', () => {
  it('maps what’s ahead with and without wake word', () => {
    assert.equal(matchVoiceIntent("what's ahead").intent, 'describe')
    assert.equal(matchVoiceIntent('हे दिव्या आगे क्या है').intent, 'describe')
    assert.equal(matchVoiceIntent('hey divya whats ahead').hadWake, true)
  })

  it('maps read, distance, pause, resume, help', () => {
    assert.equal(matchVoiceIntent('पढ़ो').intent, 'read')
    assert.equal(matchVoiceIntent('read this').intent, 'read')
    assert.equal(matchVoiceIntent('कितनी दूर').intent, 'distance')
    assert.equal(matchVoiceIntent('pause').intent, 'pause')
    assert.equal(matchVoiceIntent('शुरू करो').intent, 'resume')
    assert.equal(matchVoiceIntent('मदद').intent, 'help')
  })

  it('does not treat already as read', () => {
    assert.equal(matchVoiceIntent('already there').intent, 'unknown')
  })

  it('wake-only waits for the command', () => {
    assert.equal(matchVoiceIntent('hey divya').intent, 'await_command')
    assert.equal(matchVoiceIntent('हे दिव्या').intent, 'await_command')
  })

  it('hands-free ignores speech without the wake word', () => {
    const mapped = pickVoiceIntent(['random chatter'], { requireWake: true })
    assert.equal(mapped.intent, 'ignored')
  })
})
