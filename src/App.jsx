import { useEffect, useState } from 'react'
import DotGrid from './components/DotGrid'
import LegalPage from './components/LegalPage'
import LiveSteps from './components/LiveSteps'
import PipelineShow from './components/PipelineShow'
import ResultView from './components/ResultView'
import { loadShared, runCheck } from './lib/api'
import { DISCLAIMER } from './lib/labels'
import exampleCheck from './data/example-check.json'

const TONES = [
  { value: 'academic', label: 'Academic', sublabel: 'Formal', icon: '/iconos/academico.webp' },
  { value: 'casual', label: 'Casual', sublabel: 'Friendly', icon: '/iconos/casual.webp' },
  { value: 'aggressive', label: 'Mic Drop', sublabel: 'Savage', icon: '/iconos/contundente.webp' },
]

const EXAMPLES = ['Cracking your knuckles causes arthritis', 'Sugar makes kids hyperactive', 'We only use 10% of our brain']

const PAGES = { '/privacy': 'privacy', '/terms': 'terms', '/how-it-works': 'how' }

export default function App() {
  const [claim, setClaim] = useState('')
  const [tone, setTone] = useState('casual')
  const [loading, setLoading] = useState(false)
  const [steps, setSteps] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(() => PAGES[window.location.pathname] || 'home')
  const [chatOpen, setChatOpen] = useState(() => window.location.pathname === '/how-it-works')
  const [shared, setShared] = useState(false)

  // A shared link (/c/<id> forwards here, to /r/<id>): show that result without running a new check.
  useEffect(() => {
    const match = window.location.pathname.match(/^\/r\/([A-Za-z0-9]{8})$/)
    if (!match) return
    loadShared(match[1])
      .then((data) => { setResult(data); setShared(true) })
      .catch((err) => { setError(err.message); window.history.replaceState({}, '', '/') })
  }, [])

  useEffect(() => {
    const onPop = () => {
      const p = PAGES[window.location.pathname] || 'home'
      setPage(p === 'how' ? 'home' : p)
      setChatOpen(p === 'how')
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = (path) => {
    window.history.pushState({}, '', path)
    setPage(PAGES[path] && PAGES[path] !== 'how' ? PAGES[path] : 'home')
  }

  const openChat = () => {
    setChatOpen(true)
    window.history.pushState({}, '', '/how-it-works')
  }
  const closeChat = () => {
    setChatOpen(false)
    if (window.location.pathname === '/how-it-works') window.history.pushState({}, '', '/')
  }

  const submit = async (e) => {
    e?.preventDefault()
    const text = claim.trim()
    if (text.length < 5) {
      setError('Type a claim to check (at least a few words).')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setSteps([])
    try {
      const data = await runCheck({ claim: text, tone }, (step) => setSteps((list) => [...list, step]))
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const reset = () => {
    setResult(null)
    setSteps([])
    setError(null)
    if (shared) {
      setShared(false)
      window.history.pushState({}, '', '/')
    }
  }

  if (page === 'privacy' || page === 'terms') {
    return <LegalPage page={page} onBack={() => go('/')} />
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-50">
      <DotGrid dotSize={6} gap={35} baseColor="#1e293b" activeColor="#6366f1" proximity={100} />

      <main className="fixed inset-0 overflow-y-auto">
        <div className="flex min-h-full flex-col items-center px-4 py-6 md:py-10">
          {loading && (
            <div className="flex w-full flex-1 flex-col items-center justify-center gap-4">
              <p className="max-w-xl text-center text-sm text-slate-400">“{claim.trim()}”</p>
              <LiveSteps steps={steps} />
            </div>
          )}

          {!loading && result && <ResultView result={result} onNewCheck={reset} shared={shared} />}

          {!loading && !result && (
            <div className="flex w-full max-w-xl animate-fade-in-up flex-col">
              <header className="py-2 text-center md:py-4">
                <img src="/logo_transparente.png" alt="FactSlap logo" className="mx-auto h-14 w-auto md:h-20" />
                <h1 className="text-2xl font-extrabold md:text-3xl"><span className="gradient-text">FactSlap</span></h1>
                <p className="text-xs text-slate-400 md:text-sm">Because “I saw it on Twitter” isn't an argument.</p>
              </header>

              <form onSubmit={submit} className="flex flex-col gap-3">
                <div className="glass-card rounded-xl p-3 md:p-4">
                  <textarea
                    id="claim"
                    value={claim}
                    onChange={(e) => setClaim(e.target.value.slice(0, 300))}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) submit(e) }}
                    placeholder='Type a claim, e.g. "Cracking your knuckles causes arthritis"'
                    rows={2}
                    className="w-full resize-none rounded-lg border border-slate-700 bg-slate-900/80 px-3 py-2 text-base text-slate-100 placeholder-slate-500 transition-all focus:border-transparent focus:outline-none focus:ring-2 focus:ring-indigo-500 md:text-lg"
                  />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {EXAMPLES.map((ex) => (
                      <button key={ex} type="button" onClick={() => setClaim(ex)}
                        className="rounded-full border border-slate-700 px-2.5 py-1 text-[11px] text-slate-400 hover:border-indigo-500 hover:text-indigo-300">
                        {ex}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="glass-card rounded-xl p-3 md:p-4">
                  <span className="mb-2 block text-xs font-medium uppercase tracking-wider text-slate-400">Response style</span>
                  <div className="flex gap-2">
                    {TONES.map((opt) => (
                      <button key={opt.value} type="button" onClick={() => setTone(opt.value)}
                        className={`flex-1 rounded-lg border-2 px-2 py-2 transition-all duration-200 ${tone === opt.value ? 'border-indigo-500 bg-indigo-500/15 text-indigo-300' : 'border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600'}`}>
                        <img src={opt.icon} alt="" className="mx-auto mb-1 h-6 w-6 object-contain" />
                        <span className="block text-xs font-medium">{opt.label}</span>
                        <span className="text-[10px] text-slate-500">{opt.sublabel}</span>
                      </button>
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] leading-snug text-slate-500">
                    The style only changes the wording. The verdict is decided first, from the evidence alone.
                  </p>
                </div>

                {error && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>
                )}

                <button type="submit"
                  className="flex items-center justify-center gap-3 rounded-xl bg-indigo-600 px-6 py-3 text-base font-bold text-white shadow-xl shadow-indigo-500/30 transition-all duration-300 hover:bg-indigo-500 hover:shadow-indigo-500/50 md:py-4 md:text-lg">
                  FIND THE EVIDENCE
                </button>

                <p className="text-center text-[11px] text-slate-400">
                  Free: one check per hour per person, 50 a day in total. Claims already checked load instantly.
                </p>
                <p className="text-center text-[11px] leading-snug text-slate-500">{DISCLAIMER}</p>

                <footer className="pb-16 pt-1 text-center text-[11px] text-slate-500">
                  <span>Papers, not opinions</span>
                  <span className="mx-2 text-slate-700">·</span>
                  <a href="/privacy" onClick={(e) => { e.preventDefault(); go('/privacy') }} className="hover:text-slate-300">Privacy</a>
                  <span className="mx-2 text-slate-700">·</span>
                  <a href="/terms" onClick={(e) => { e.preventDefault(); go('/terms') }} className="hover:text-slate-300">Terms</a>
                </footer>
              </form>
            </div>
          )}
        </div>
      </main>

      <PipelineShow open={chatOpen} onOpen={openChat} onClose={closeChat} lastResult={result} example={exampleCheck} />
    </div>
  )
}
