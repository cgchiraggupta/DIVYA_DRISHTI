import { useState } from 'react'
import { Navigation2, MapPin, LoaderCircle, AlertTriangle, CheckCircle2 } from '../../lib/lucide'
import Layout from '../../components/Layout'
import Card from '../../components/Card'
import Button from '../../components/Button'
import { useNavigationSession } from '../context/NavigationSessionContext'

const PHASE_LABEL = {
  idle: '',
  extracting: 'Understanding your destination…',
  geocoding: 'Locating place…',
  routing: 'Building your route…',
  navigating: 'Navigating',
  arrived: 'You have arrived',
  error: 'Something went wrong',
}

export default function Navigate() {
  const { state, navigateTo, reset } = useNavigationSession()
  const [query, setQuery] = useState('')

  const isBusy = ['extracting', 'geocoding', 'routing'].includes(state.phase)
  const isNavigating = state.phase === 'navigating'
  const currentStep = state.route?.steps?.[state.currentStepIndex]

  const handleSubmit = (event) => {
    event.preventDefault()
    if (!query.trim() || isBusy || isNavigating) return
    navigateTo(query.trim())
  }

  return (
    <Layout title="Navigate" subtitle="Say or type where you want to go">
      <div className="flex flex-col gap-4">
        <Card>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <label htmlFor="nav-query" className="text-sm text-mist-400">
              Destination
            </label>
            <input
              id="nav-query"
              type="text"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Take me to India Gate"
              disabled={isBusy || isNavigating}
              className="rounded-xl border border-night-600 bg-night-950 px-4 py-2.5 text-sm text-mist-100
                         placeholder:text-mist-500 focus:outline-none focus:ring-2 focus:ring-signal-500/50"
            />
            <Button type="submit" disabled={isBusy || isNavigating || !query.trim()}>
              {isBusy ? <LoaderCircle size={16} className="animate-spin" /> : <Navigation2 size={16} />}
              Start navigation
            </Button>
          </form>
        </Card>

        {state.phase !== 'idle' && (
          <Card eyebrow={PHASE_LABEL[state.phase]} title={state.destination?.label || state.query}>
            {isBusy && (
              <p className="flex items-center gap-2 text-sm text-mist-400">
                <LoaderCircle size={16} className="animate-spin" />
                {PHASE_LABEL[state.phase]}
              </p>
            )}

            {state.phase === 'error' && (
              <p className="flex items-center gap-2 text-sm text-alert-400">
                <AlertTriangle size={16} />
                {state.error}
              </p>
            )}

            {isNavigating && currentStep && (
              <div className="flex flex-col gap-2">
                <p className="flex items-start gap-2 text-base text-mist-100">
                  <MapPin size={18} className="mt-0.5 shrink-0 text-signal-400" />
                  {currentStep.instruction}
                </p>
                <p className="text-xs text-mist-500">
                  Step {state.currentStepIndex + 1} of {state.route.steps.length}
                </p>
              </div>
            )}

            {state.spokenLog.length > 0 && (
              <div className="mt-4 border-t border-night-700 pt-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-mist-500">
                  What's been said
                </p>
                <ul className="flex max-h-48 flex-col gap-2 overflow-y-auto">
                  {[...state.spokenLog].reverse().map((entry) => (
                    <li key={entry.at} className="text-sm leading-5 text-mist-300">
                      {entry.text}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {state.phase === 'arrived' && (
              <p className="flex items-center gap-2 text-sm text-signal-400">
                <CheckCircle2 size={16} />
                You have reached {state.destination?.label}.
              </p>
            )}

            {(state.phase === 'error' || state.phase === 'arrived') && (
              <Button variant="secondary" className="mt-4" onClick={reset}>
                Start over
              </Button>
            )}

            {isNavigating && (
              <Button variant="danger" className="mt-4" onClick={reset}>
                Stop navigation
              </Button>
            )}
          </Card>
        )}
      </div>
    </Layout>
  )
}
