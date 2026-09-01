import BottomNav from './BottomNav'
import FloatingWakeButton from './FloatingWakeButton'

export default function Layout({ title, subtitle, action, children }) {
  return (
    <div className="min-h-screen bg-night-950 text-mist-100 flex flex-col">
      <header className="px-5 pt-[calc(env(safe-area-inset-top)+1.25rem)] pb-4 flex items-start justify-between">
        <div>
          <h1 className="font-display text-xl font-semibold tracking-tight text-mist-100">{title}</h1>
          {subtitle && <p className="text-sm text-mist-400 mt-0.5">{subtitle}</p>}
        </div>
        {action}
      </header>

      <main className="flex-1 px-5 pb-28">{children}</main>

      <FloatingWakeButton />
      <BottomNav />
    </div>
  )
}
