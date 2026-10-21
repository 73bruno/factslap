import { STEPS, STEP_HINTS, SOURCES } from '../lib/labels'

function detail(step) {
  const d = step.data || {}
  switch (step.step) {
    case 'plan':
      return d.queries?.length ? `“${d.queries.slice(0, 2).join('”, “')}”` : null
    case 'search': {
      const parts = Object.entries(d.per_source || {})
        .filter(([, v]) => typeof v === 'number' && v > 0)
        .map(([k, v]) => `${SOURCES[k] || k} ${v}`)
      return parts.length ? parts.join(' · ') : null
    }
    case 'rank':
      return d.unique ? `${d.unique} unique passages → best ${step.message.match(/\d+/)?.[0] ?? ''}` : null
    case 'evidence':
      return `${d.refutes ?? 0} refute · ${d.supports ?? 0} support · ${d.neutral ?? 0} context`
    case 'verdict':
      return d.why || null
    case 'verify':
      return (d.checks || []).every((c) => c.passed) ? 'Citations, quotes and numbers: all checked' : 'Some checks needed a rewrite'
    default:
      return null
  }
}

export default function LiveSteps({ steps }) {
  const done = new Map(steps.map((s) => [s.step, s]))
  const firstPending = STEPS.find((s) => !done.has(s.key))?.key

  return (
    <div className="glass-card rounded-2xl p-5 w-full max-w-xl animate-fade-in-up">
      <p className="text-slate-400 text-xs uppercase tracking-wider mb-4">Checking the evidence</p>
      <ol className="space-y-3">
        {STEPS.map((s) => {
          const step = done.get(s.key)
          const active = s.key === firstPending
          return (
            <li key={s.key} className="flex gap-3 items-start">
              <span
                className={`mt-0.5 h-5 w-5 flex-shrink-0 rounded-full border-2 flex items-center justify-center text-[10px] font-bold
                  ${step ? 'border-indigo-400 bg-indigo-500 text-white' : active ? 'border-indigo-400 animate-pulse' : 'border-slate-600'}`}
              >
                {step ? '✓' : ''}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className={`text-sm font-semibold ${step || active ? 'text-slate-100' : 'text-slate-500'}`}>{s.label}</span>
                  {step && <span className="font-mono text-[11px] text-slate-500 tabular-nums">{(step.ms / 1000).toFixed(1)} s</span>}
                </div>
                {(step || active) && (
                  <p className="text-xs text-slate-400 mt-0.5 break-words">{(step && detail(step)) || STEP_HINTS[s.key]}</p>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
