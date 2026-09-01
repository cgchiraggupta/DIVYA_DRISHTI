import { NavLink } from 'react-router-dom'
import { LayoutDashboard, History, Navigation2, SlidersHorizontal, Stethoscope } from '../lib/lucide'
import { tapFeedback } from '../services/sensoryFeedback'

const items = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/navigate', label: 'Navigate', icon: Navigation2 },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: SlidersHorizontal },
  { to: '/diagnostics', label: 'Diagnostics', icon: Stethoscope },
]

export default function BottomNav() {
  return (
    <nav
      className="fixed bottom-0 inset-x-0 z-20 border-t border-night-700 bg-night-900/95 backdrop-blur
                 pb-[env(safe-area-inset-bottom)]"
      aria-label="Primary"
    >
      <ul className="grid grid-cols-5">
        {items.map(({ to, label, icon: Icon, end }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={end}
              onClick={tapFeedback}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 py-2.5 text-xs font-medium transition-colors ${
                  isActive ? 'text-signal-400' : 'text-mist-400 hover:text-mist-200'
                }`
              }
            >
              <Icon size={20} strokeWidth={2} />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
