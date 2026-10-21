import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { VERDICTS } from '../lib/labels'

/* Full-screen, animated walkthrough of the pipeline.
   One large SVG canvas holds the whole architecture; a "camera" (the SVG viewBox) glides from stage to
   stage while packets flow along the edges already reached. With a real check it shows that check's numbers. */

const W = 4900
const H = 1000
const MID = 500

const SOURCE_ROWS = [
  { key: 'openalex', label: 'OpenAlex', note: '250M+ research works', logo: '/logos/openalex.png' },
  { key: 'semantic_scholar', label: 'Semantic Scholar', note: 'passages inside papers', logo: '/logos/semanticscholar.svg' },
  { key: 'europe_pmc', label: 'Europe PMC', note: 'medicine & life sciences', logo: '/logos/europepmc.png' },
  { key: 'fact_check', label: 'Google Fact Check', note: 'published fact-checks', logo: '/logos/google.svg' },
  { key: 'wikipedia', label: 'Wikipedia', note: 'general knowledge', logo: '/logos/wikipedia.svg' },
  { key: 'open_data', label: 'Open data', note: 'World Bank · Open Food Facts', logo: '/logos/worldbank.png', logo2: '/logos/openfoodfacts.png' },
]
const SOURCE_Y = [160, 296, 432, 568, 704, 840]

// Node boxes: [x, y, width, height] with x,y = centre.
const NODES = {
  claim: [240, MID, 380, 250],
  plan: [720, MID, 430, 340],
  ...Object.fromEntries(SOURCE_ROWS.map((s, i) => [`src_${s.key}`, [1250, SOURCE_Y[i], 420, 112]])),
  merge: [1760, MID, 340, 250],
  bm25: [2170, 330, 340, 120],
  embed: [2170, MID, 340, 120],
  order: [2170, 670, 340, 120],
  rrf: [2560, MID, 300, 210],
  rerank: [2950, MID, 330, 260],
  read: [3400, MID, 440, 440],
  verdict: [3890, MID, 380, 380],
  write: [4340, MID, 400, 380],
  tone: [4760, MID, 340, 400],
}

const STAGES = [
  { key: 'claim', title: 'Your claim', focus: ['claim'], nodes: ['claim'] },
  { key: 'plan', title: 'Plan the search', focus: ['claim', 'plan'], nodes: ['plan'] },
  { key: 'search', title: 'Search six sources at once', focus: ['plan', ...SOURCE_ROWS.map((s) => `src_${s.key}`)], nodes: SOURCE_ROWS.map((s) => `src_${s.key}`) },
  { key: 'merge', title: 'Remove duplicates', focus: ['src_openalex', 'src_open_data', 'merge'], nodes: ['merge'] },
  { key: 'rank', title: 'Rank: three opinions, one list', focus: ['merge', 'bm25', 'order', 'rrf', 'rerank'], nodes: ['bm25', 'embed', 'order', 'rrf', 'rerank'] },
  { key: 'read', title: 'Read every passage', focus: ['rerank', 'read'], nodes: ['read'] },
  { key: 'verdict', title: 'Verdict by formula, not by AI', focus: ['read', 'verdict'], nodes: ['verdict'] },
  { key: 'write', title: 'Write it, then check it', focus: ['verdict', 'write'], nodes: ['write'] },
  { key: 'tone', title: 'Your tone, facts locked', focus: ['write', 'tone'], nodes: ['tone'] },
  { key: 'all', title: 'The whole pipeline', focus: Object.keys(NODES), nodes: [] },
]
const NODE_STAGE = Object.fromEntries(STAGES.flatMap((s, i) => s.nodes.map((n) => [n, i])))

const EDGES = [
  ['claim', 'plan'],
  ...SOURCE_ROWS.map((s) => ['plan', `src_${s.key}`]),
  ...SOURCE_ROWS.map((s) => [`src_${s.key}`, 'merge']),
  ['merge', 'bm25'], ['merge', 'embed'], ['merge', 'order'],
  ['bm25', 'rrf'], ['embed', 'rrf'], ['order', 'rrf'],
  ['rrf', 'rerank'], ['rerank', 'read'], ['read', 'verdict'], ['verdict', 'write'], ['write', 'tone'],
]

const CHECK_LABELS = {
  citations_exist: 'Every citation points to a real source',
  has_citations: 'The answer is cited',
  numbers_grounded: 'Every number appears in a source',
  quotes_verbatim: 'Every quote is word for word',
}

const STACK = [
  ['Python', '/logos/python.svg'], ['FastAPI', '/logos/fastapi.svg'], ['OpenAI', '/logos/openai.svg'],
  ['Upstash Redis', '/logos/upstash.svg'], ['Vercel', '/logos/vercel.svg'],
]

function edgePath(from, to) {
  const [x1, y1, w1] = NODES[from]
  const [x2, y2, w2] = NODES[to]
  const sx = x1 + w1 / 2
  const ex = x2 - w2 / 2
  const dx = Math.max(40, (ex - sx) * 0.5)
  return `M ${sx} ${y1} C ${sx + dx} ${y1}, ${ex - dx} ${y2}, ${ex} ${y2}`
}

function focusBox(keys) {
  const xs = keys.flatMap((k) => [NODES[k][0] - NODES[k][2] / 2, NODES[k][0] + NODES[k][2] / 2])
  const ys = keys.flatMap((k) => [NODES[k][1] - NODES[k][3] / 2, NODES[k][1] + NODES[k][3] / 2])
  const pad = 60
  return { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + pad * 2, h: Math.max(...ys) - Math.min(...ys) + pad * 2 }
}

/** Fit a focus box into the screen's aspect ratio, leaving room for the top bar and the narration card. */
function cameraFor(box, aspect, topShare, bottomShare) {
  const usable = 1 - topShare - bottomShare
  let h = box.h / usable
  let w = h * aspect
  if (w < box.w) {
    w = box.w
    h = w / aspect
  }
  const cx = box.x + box.w / 2
  const cy = box.y + box.h / 2 + (h * (bottomShare - topShare)) / 2
  return { x: cx - w / 2, y: cy - h / 2, w, h }
}

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

function summarise(result) {
  if (!result) return null
  const step = (name) => result.steps?.find((s) => s.step === name)?.data || {}
  const rank = step('rank')
  const weights = /Support weight ([\d.]+) vs refute weight ([\d.]+)/.exec(result.verdict?.explanation || '')
  const answer = result.styled_answer || result.answer
  return {
    claim: result.claim,
    queries: result.plan?.queries || [],
    perSource: step('search').per_source || {},
    candidates: rank.candidates,
    unique: rank.unique,
    evidence: (result.evidence || []).map((e) => ({ stance: e.stance, type: e.passage?.study_type, title: e.passage?.title, year: e.passage?.year })),
    verdict: result.verdict?.label,
    confidence: result.verdict?.confidence,
    support: weights ? Number(weights[1]) : null,
    refute: weights ? Number(weights[2]) : null,
    checks: result.verification?.checks || [],
    short: answer?.short || answer?.text,
    seconds: (result.latency_ms || 0) / 1000,
    cost: result.cost_usd,
  }
}

function countFor(run, key) {
  if (!run) return undefined
  if (key === 'open_data') {
    const values = [run.perSource.world_bank, run.perSource.open_food_facts]
    if (values.some((v) => typeof v === 'number')) return values.reduce((a, v) => a + (typeof v === 'number' ? v : 0), 0)
    return values.find((v) => typeof v === 'string')
  }
  return run.perSource[key]
}

function narration(stageKey, run) {
  const total = run ? Object.values(run.perSource).filter((v) => typeof v === 'number').reduce((a, b) => a + b, 0) : null
  const stances = run ? run.evidence.reduce((acc, e) => ({ ...acc, [e.stance]: (acc[e.stance] || 0) + 1 }), {}) : {}
  switch (stageKey) {
    case 'claim':
      return {
        text: run ? `It all starts with a claim: “${run.claim}”. This is exactly what happened to it, step by step.` : 'It all starts with a claim. This is what happens to it in the next ~15 seconds.',
        tech: ['every step streams live to your screen'],
      }
    case 'plan':
      return {
        text: `A fast AI model rewrites the claim the way scientists write about it and picks where to look.${run?.queries?.length ? ` It searched for “${run.queries.slice(0, 3).join('”, “')}”.` : ''} One search always targets the strongest kind of evidence: trials and meta-analyses.`,
        tech: ['GPT-5.6 Luna', 'structured JSON output'],
      }
    case 'search':
      return {
        text: `All the sources are searched at the same time. ${total ? `This time they returned ${total} passages.` : 'Together they usually return 25 to 65 passages.'} If one is down (red), the others carry on.`,
        tech: ['parallel async requests', 'timeouts and retries'],
      }
    case 'merge':
      return {
        text: `The same paper often arrives through two catalogues. It's kept only once, from the copy with the most details.${run?.unique ? ` ${run.candidates} passages became ${run.unique} unique ones.` : ''}`,
        tech: ['dedupe by DOI and title'],
      }
    case 'rank':
      return {
        text: 'Three different rankings vote: which passages share the claim\'s words, which mean the same thing, and what each source ranked first. Reciprocal Rank Fusion turns the three into one list, then an AI reads the shortlist and keeps the best 8, at most two per paper.',
        tech: ['BM25', 'OpenAI embeddings', 'Reciprocal Rank Fusion', 'AI reranker'],
      }
    case 'read':
      return {
        text: `A stronger model reads each passage and decides: does it support the claim, refute it, or just give context? It must copy the exact sentence that proves it. If that sentence isn't really in the paper, the passage doesn't count.${run?.evidence?.length ? ` Here: ${stances.refutes || 0} refute, ${stances.supports || 0} support, ${stances.neutral || 0} context.` : ''}`,
        tech: ['GPT-5.6 Terra', 'no exact quote, no vote', 'correlation ≠ causation'],
      }
    case 'verdict':
      return {
        text: `No AI decides the verdict: a formula does. Evidence for and against is weighed by study quality (a meta-analysis counts more than a single observational study). Too little evidence gives “not enough evidence”.${run?.verdict ? ` Result: ${VERDICTS[run.verdict]?.label || run.verdict}, ${Math.round((run.confidence || 0) * 100)}% confidence.` : ''}`,
        tech: ['deterministic', 'you can see why'],
      }
    case 'write':
      return {
        text: 'The answer is written with a source on every sentence. Then plain code checks it before you see it. If any check fails, it gets rewritten with the errors pointed out.',
        tech: ['4 automatic checks', 'auto-retry'],
      }
    case 'tone':
      return {
        text: 'Last, your tone. Mic Drop can roast the myth, but it only changes the wording: if the rewrite touches a number or a source, it is thrown away. The jokes never change the facts.',
        tech: ['facts locked'],
      }
    default:
      return {
        text: `That's the whole pipeline${run?.seconds ? `, in ${run.seconds.toFixed(1)} s and about ${((run.cost || 0) * 100).toFixed(1)} cents of AI` : ''}. It is tested on every change and evaluated on hand-labelled myths and a public scientific dataset.`,
        tech: [],
      }
  }
}

const FOLLOW_UPS = [
  ['How do you stop made-up citations?', "Three checks in plain code, not an AI judging another AI: each quote must appear word for word in its passage, the answer can only cite passages it was given, and every number in the answer must exist in a source. Anything that fails is rewritten or dropped."],
  ['How is it tested?', 'About fifty automated tests run on every change, with no internet and no keys: the AI and every source are simulated. On top, an evaluation on 30 hand-labelled myths and facts in English and Spanish, and on SciFact, a public set of scientific claims with the paper that settles each one.'],
  ['What stops abuse?', 'Hard limits before anything is spent: one check per person per hour, 50 checks a day for everyone together, a cap on checks running at once and a daily budget. Visitors are identified only by a scrambled (hashed) IP, claims already checked come from a cache for free, and if the limiter is down nothing runs.'],
]

/* ---------- pieces ---------- */

function Card({ id, active, done, dim, children, accent = '#818cf8' }) {
  const [x, y, w, h] = NODES[id]
  const stroke = active ? accent : done ? 'rgba(129,140,248,0.55)' : 'rgba(71,85,105,0.7)'
  return (
    <g style={{ opacity: dim ? 0.38 : active || done ? 1 : 0.3, transition: 'opacity 600ms' }}>
      <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx="24" fill="#0f172a" stroke={stroke} strokeWidth={active ? 4 : 2}
        style={{ filter: active ? `drop-shadow(0 0 24px ${accent}99)` : 'none', transition: 'all 600ms' }} />
      <foreignObject x={x - w / 2 + 20} y={y - h / 2 + 16} width={w - 40} height={h - 32}>
        <div xmlns="http://www.w3.org/1999/xhtml" className="flex h-full w-full flex-col overflow-hidden text-slate-200">{children}</div>
      </foreignObject>
    </g>
  )
}

function Logo({ src, size = 44, alt = '' }) {
  return (
    <span className="flex flex-shrink-0 items-center justify-center rounded-xl bg-white p-1.5 shadow" style={{ width: size, height: size }}>
      <img src={src} alt={alt} className="h-full w-full object-contain" />
    </span>
  )
}

function Header({ logo, title, sub }) {
  return (
    <div className="flex items-center gap-3">
      {logo && <Logo src={logo} />}
      <div className="min-w-0">
        <p className="truncate text-[23px] font-extrabold leading-tight text-white">{title}</p>
        {sub && <p className="truncate text-[16px] text-indigo-300">{sub}</p>}
      </div>
    </div>
  )
}

const STANCE_STYLE = {
  refutes: ['Refutes', 'bg-red-500/20 text-red-200 border-red-400/40'],
  supports: ['Supports', 'bg-emerald-500/20 text-emerald-200 border-emerald-400/40'],
  neutral: ['Context', 'bg-slate-600/30 text-slate-300 border-slate-500/40'],
}

function Packets({ d, count, dur, color }) {
  return Array.from({ length: count }, (_, i) => (
    <circle key={i} r="7" fill={color} opacity="0.95">
      <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${(i * dur) / count}s`} path={d} />
    </circle>
  ))
}

export default function PipelineShow({ open, onOpen, onClose, lastResult, example }) {
  return (
    <>
      {!open && (
        <button onClick={onOpen}
          className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-indigo-400/50 bg-slate-900/90 px-4 py-2.5 text-sm font-semibold text-indigo-200 shadow-xl shadow-indigo-500/20 backdrop-blur transition hover:border-indigo-300 hover:text-white">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-indigo-400 opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-indigo-400" />
          </span>
          How it works
        </button>
      )}
      {open && <Show onClose={onClose} result={lastResult || example} isReplay={Boolean(lastResult)} />}
    </>
  )
}

function Show({ onClose, result, isReplay }) {
  const run = useMemo(() => summarise(result), [result])
  const [reduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  const [stage, setStage] = useState(0)
  const [playing, setPlaying] = useState(!reduced)
  const [answer, setAnswer] = useState(null)
  const svg = useRef(null)
  const wrap = useRef(null)
  const camera = useRef(null)

  const go = useCallback((next) => {
    setAnswer(null)
    setStage((s) => Math.max(0, Math.min(STAGES.length - 1, typeof next === 'function' ? next(s) : next)))
  }, [])

  // Camera: tween the viewBox to the current stage's focus area.
  useEffect(() => {
    const el = svg.current
    const box = wrap.current
    if (!el || !box) return
    const place = (animate) => {
      const aspect = box.clientWidth / Math.max(1, box.clientHeight)
      const narrow = box.clientWidth < 768
      const topShare = 64 / Math.max(1, box.clientHeight)
      const bottomShare = Math.min(0.5, (narrow ? 250 : 210) / Math.max(1, box.clientHeight))
      // On narrow screens frame only the active nodes, so wide stages stay readable.
      const keys = narrow && STAGES[stage].nodes.length ? STAGES[stage].nodes : STAGES[stage].focus
      const target = cameraFor(focusBox(keys), aspect, topShare, bottomShare)
      const from = camera.current || target
      const start = performance.now()
      const duration = animate && !reduced ? 1100 : 0
      let frame
      const apply = (v) => {
        camera.current = v
        el.setAttribute('viewBox', `${v.x} ${v.y} ${v.w} ${v.h}`)
      }
      const tick = (now) => {
        const t = duration ? Math.min(1, (now - start) / duration) : 1
        const k = ease(t)
        apply({
          x: from.x + (target.x - from.x) * k, y: from.y + (target.y - from.y) * k,
          w: from.w + (target.w - from.w) * k, h: from.h + (target.h - from.h) * k,
        })
        if (t < 1) frame = requestAnimationFrame(tick)
      }
      frame = requestAnimationFrame(tick)
      // Background tabs pause requestAnimationFrame: make sure the camera still lands on the right stage.
      const fallback = setTimeout(() => { cancelAnimationFrame(frame); apply(target) }, duration + 80)
      return () => { cancelAnimationFrame(frame); clearTimeout(fallback) }
    }
    const stop = place(true)
    const onResize = () => place(false)
    window.addEventListener('resize', onResize)
    return () => { stop(); window.removeEventListener('resize', onResize) }
  }, [stage, reduced])

  // Auto-play: next stage after the narration has had time to be read.
  useEffect(() => {
    if (!playing || stage >= STAGES.length - 1) return
    const words = narration(STAGES[stage].key, run).text.split(' ').length
    const timer = setTimeout(() => go((s) => s + 1), Math.max(5500, words * 330))
    return () => clearTimeout(timer)
  }, [playing, stage, run, go])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowRight') { setPlaying(false); go((s) => s + 1) }
      else if (e.key === 'ArrowLeft') { setPlaying(false); go((s) => s - 1) }
      else if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, onClose])

  const current = STAGES[stage]
  const story = narration(current.key, run)
  const isActive = (id) => current.key !== 'all' && NODE_STAGE[id] === stage
  const isDone = (id) => current.key === 'all' || NODE_STAGE[id] < stage
  const v = run ? VERDICTS[run.verdict] : null
  const verdictColor = { emerald: '#34d399', red: '#f87171', amber: '#fbbf24', slate: '#94a3b8' }[v?.tone] || '#94a3b8'
  const sourceState = (key) => {
    const count = countFor(run, key)
    if (typeof count === 'number') return { kind: 'ok', count }
    if (typeof count === 'string') return { kind: 'down' }
    return run ? { kind: 'skipped' } : { kind: 'unknown' }
  }
  const sourceOfEdge = (a, b) => (b.startsWith('src_') ? b : a.startsWith('src_') ? a : '').slice(4)
  const evidence = run?.evidence?.length ? run.evidence.slice(0, 6) : []

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 text-slate-100" role="dialog" aria-label="How FactSlap works">
      <div className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(1200px 650px at 50% 35%, rgba(79,70,229,0.2), transparent 70%)' }} />

      <div ref={wrap} className="absolute inset-0">
        <svg ref={svg} className="h-full w-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
          <defs>
            <pattern id="grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="1.6" fill="#1e293b" />
            </pattern>
          </defs>
          <rect x={-3000} y={-3000} width={W + 6000} height={H + 6000} fill="url(#grid)" />

          {EDGES.map(([a, b]) => {
            const d = edgePath(a, b)
            const src = sourceOfEdge(a, b)
            const state = src ? sourceState(src).kind : 'ok'
            const reached = current.key === 'all' || NODE_STAGE[b] <= stage
            const live = reached && state !== 'skipped'
            const down = reached && state === 'down'
            return (
              <g key={`${a}-${b}`}>
                <path d={d} fill="none" stroke={down ? '#7f1d1d' : live ? '#4f46e5' : '#1e293b'} strokeWidth={live ? 3.5 : 2}
                  strokeDasharray={down || state === 'skipped' ? '10 12' : undefined} style={{ transition: 'stroke 600ms' }} />
                {live && !down && !reduced && <Packets d={d} count={src ? 2 : 3} dur={src ? 2.4 : 1.8} color="#a5b4fc" />}
              </g>
            )
          })}

          <Card id="claim" active={isActive('claim')} done={isDone('claim')}>
            <p className="text-[16px] font-bold uppercase tracking-widest text-indigo-300">You asked</p>
            <p className="mt-2 text-[28px] font-bold leading-snug text-white">“{run?.claim || 'Cracking your knuckles causes arthritis'}”</p>
          </Card>

          <Card id="plan" active={isActive('plan')} done={isDone('plan')}>
            <Header logo="/logos/openai.svg" title="Plan the search" sub="GPT-5.6 Luna" />
            <p className="mt-3 text-[16px] text-slate-400">Searches it wrote:</p>
            <ul className="mt-2 space-y-2">
              {(run?.queries?.length ? run.queries : ['knuckle cracking osteoarthritis', 'habitual knuckle cracking cohort study']).slice(0, 3).map((q) => (
                <li key={q} className="truncate rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-1.5 text-[17px] text-indigo-100">🔎 {q}</li>
              ))}
            </ul>
          </Card>

          {SOURCE_ROWS.map((s) => {
            const st = sourceState(s.key)
            return (
              <Card key={s.key} id={`src_${s.key}`} active={isActive(`src_${s.key}`)} done={isDone(`src_${s.key}`)}
                dim={st.kind === 'skipped' && (isActive(`src_${s.key}`) || isDone(`src_${s.key}`))} accent={st.kind === 'down' ? '#f87171' : '#818cf8'}>
                <div className="flex h-full items-center gap-3">
                  <Logo src={s.logo} size={52} alt={s.label} />
                  {s.logo2 && <Logo src={s.logo2} size={52} alt="" />}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[22px] font-bold text-white">{s.label}</p>
                    <p className="truncate text-[15px] text-slate-400">{s.note}</p>
                  </div>
                  {st.kind === 'ok' && (
                    <span className="flex flex-col items-center rounded-xl bg-indigo-500/20 px-3 py-1 text-indigo-100">
                      <span className="font-mono text-[24px] font-bold leading-none">{st.count}</span>
                      <span className="text-[12px]">passages</span>
                    </span>
                  )}
                  {st.kind === 'down' && <span className="rounded-xl bg-red-500/15 px-3 py-2 text-[15px] font-semibold text-red-300">offline</span>}
                  {st.kind === 'skipped' && <span className="text-[14px] text-slate-500">not needed</span>}
                </div>
              </Card>
            )
          })}

          <Card id="merge" active={isActive('merge')} done={isDone('merge')}>
            <Header title="Remove duplicates" sub="one copy per paper" />
            <div className="mt-4 flex items-end justify-center gap-4">
              <div className="text-center"><p className="font-mono text-[44px] font-bold leading-none text-white">{run?.candidates ?? '—'}</p><p className="text-[14px] text-slate-400">found</p></div>
              <p className="pb-5 text-[32px] text-indigo-300">→</p>
              <div className="text-center"><p className="font-mono text-[44px] font-bold leading-none text-white">{run?.unique ?? '—'}</p><p className="text-[14px] text-slate-400">unique</p></div>
            </div>
          </Card>

          {[
            ['bm25', '🔤 Same words', 'keyword search (BM25)', null],
            ['embed', 'Same meaning', 'OpenAI embeddings', '/logos/openai.svg'],
            ['order', '📚 Source\'s choice', "each catalogue's own ranking", null],
          ].map(([id, title, sub, logo]) => (
            <Card key={id} id={id} active={isActive(id)} done={isDone(id)}>
              <div className="flex h-full items-center"><Header logo={logo} title={title} sub={sub} /></div>
            </Card>
          ))}

          <Card id="rrf" active={isActive('rrf')} done={isDone('rrf')}>
            <p className="text-center text-[25px] font-extrabold text-white">3 rankings → 1</p>
            <div className="mt-2 flex justify-center gap-1.5">
              {['bg-sky-400', 'bg-violet-400', 'bg-amber-400'].map((c) => <span key={c} className={`h-3 w-10 rounded-full ${c}`} />)}
            </div>
            <p className="mt-3 text-center text-[16px] text-indigo-300">Reciprocal Rank Fusion</p>
            <p className="text-center text-[14px] text-slate-400">items ranked well everywhere win</p>
          </Card>

          <Card id="rerank" active={isActive('rerank')} done={isDone('rerank')}>
            <Header logo="/logos/openai.svg" title="AI reranker" sub="GPT-5.6 Luna" />
            <p className="mt-4 text-center font-mono text-[40px] font-bold text-white">best 8</p>
            <p className="text-center text-[15px] text-slate-400">max 2 passages per paper</p>
          </Card>

          <Card id="read" active={isActive('read')} done={isDone('read')}>
            <Header logo="/logos/openai.svg" title="Read every passage" sub="GPT-5.6 Terra" />
            <ul className="mt-3 space-y-1.5">
              {(evidence.length ? evidence : [
                { stance: 'refutes', type: 'observational', title: 'Knuckle cracking and hand osteoarthritis' },
                { stance: 'refutes', type: 'review', title: 'Clinical anatomy of knuckle cracking' },
                { stance: 'neutral', type: 'observational', title: 'Can observers detect changes?' },
              ]).map((e, i) => {
                const [label, cls] = STANCE_STYLE[e.stance] || STANCE_STYLE.neutral
                return (
                  <li key={i} className="flex items-center gap-2">
                    <span className={`w-[92px] flex-shrink-0 rounded-md border px-2 py-0.5 text-center text-[14px] font-bold ${cls}`}>{label}</span>
                    <span className="truncate text-[15px] text-slate-300">{e.title}</span>
                  </li>
                )
              })}
            </ul>
            <p className="mt-auto pt-2 text-[15px] text-emerald-300">✓ each quote found word for word</p>
          </Card>

          <Card id="verdict" active={isActive('verdict')} done={isDone('verdict')} accent={verdictColor}>
            <Header title="Verdict = formula" sub="no AI involved" />
            {[['Evidence for', run?.support ?? 0, 'bg-emerald-400'], ['Evidence against', run?.refute ?? 0, 'bg-red-400']].map(([label, value, color]) => (
              <div key={label} className="mt-3">
                <div className="flex justify-between text-[15px] text-slate-400"><span>{label}</span><span className="font-mono">{Number(value).toFixed(2)}</span></div>
                <div className="mt-1 h-3.5 rounded-full bg-slate-800">
                  <div className={`h-3.5 rounded-full ${color}`} style={{ width: `${Math.min(100, (Number(value) / 3) * 100)}%`, transition: 'width 1s' }} />
                </div>
              </div>
            ))}
            <p className="mt-auto text-[30px] font-extrabold leading-tight" style={{ color: verdictColor }}>{v?.label || 'Refuted'}</p>
            <p className="text-[15px] text-slate-400">{run?.confidence !== undefined ? `${Math.round(run.confidence * 100)}% confidence` : 'weighted by study quality'}</p>
          </Card>

          <Card id="write" active={isActive('write')} done={isDone('write')}>
            <Header title="Write it, then check it" sub="plain code, before you see it" />
            <ul className="mt-3 space-y-2">
              {(run?.checks?.length ? run.checks : Object.keys(CHECK_LABELS).map((name) => ({ name, passed: true }))).map((c) => (
                <li key={c.name} className="flex items-start gap-2 text-[16px] leading-snug">
                  <span className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${c.passed ? 'bg-emerald-500 text-white' : 'bg-red-500 text-white'}`}>{c.passed ? '✓' : '✗'}</span>
                  <span className="text-slate-200">{CHECK_LABELS[c.name] || c.name}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card id="tone" active={isActive('tone')} done={isDone('tone')}>
            <Header title="Your tone 🔒" sub="wording changes, facts don't" />
            <p className="mt-3 line-clamp-6 rounded-xl bg-slate-800/80 p-3 text-[17px] leading-snug text-slate-100">
              {run?.short || 'Your knuckles can relax: decades of studies found no link with arthritis [1][2].'}
            </p>
          </Card>
        </svg>
      </div>

      <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-white sm:text-base">How FactSlap checks a claim</p>
          <p className="truncate text-[11px] text-slate-400">{isReplay ? 'Replaying your last check, with its real numbers' : 'A real check, replayed step by step'}</p>
        </div>
        <button onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-slate-500 hover:text-white" aria-label="Close">Close ✕</button>
      </div>

      <div className="absolute inset-x-0 bottom-0 p-3 sm:p-6">
        <div className="mx-auto max-w-3xl rounded-2xl border border-slate-700/80 bg-slate-900/90 p-4 shadow-2xl backdrop-blur sm:p-5">
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-[12px] font-semibold uppercase tracking-widest text-indigo-300">
              Step {Math.min(stage + 1, STAGES.length - 1)} of {STAGES.length - 1} · {current.title}
            </p>
            <div className="flex items-center gap-1">
              <button onClick={() => { setPlaying(false); go((s) => s - 1) }} disabled={stage === 0} className="rounded-md px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-30" aria-label="Previous step">◀</button>
              <button onClick={() => setPlaying((p) => !p)} className="rounded-md px-2 py-1 text-slate-300 hover:bg-slate-800" aria-label={playing ? 'Pause' : 'Play'}>{playing ? '❚❚' : '▶'}</button>
              <button onClick={() => { setPlaying(false); go((s) => s + 1) }} disabled={stage === STAGES.length - 1} className="rounded-md px-2 py-1 text-slate-300 hover:bg-slate-800 disabled:opacity-30" aria-label="Next step">▶▶</button>
            </div>
          </div>
          <p key={`${stage}-${answer ? 'a' : 's'}`} className="animate-fade-in text-[14px] leading-relaxed text-slate-200 sm:text-[15px]">{answer || story.text}</p>
          {!answer && story.tech.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {story.tech.map((t) => <span key={t} className="rounded border border-indigo-500/30 bg-indigo-500/10 px-1.5 py-0.5 font-mono text-[10px] text-indigo-300">{t}</span>)}
            </div>
          )}
          {(current.key === 'claim' || current.key === 'all') && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-slate-500">Built with</span>
              {STACK.map(([name, src]) => (
                <span key={name} className="flex items-center gap-1.5 rounded-full bg-white/95 py-0.5 pl-1 pr-2.5 text-[11px] font-semibold text-slate-800">
                  <img src={src} alt="" className="h-4 w-4 object-contain" /> {name}
                </span>
              ))}
            </div>
          )}
          {current.key === 'all' && (
            <div className="mt-3 flex flex-wrap gap-2">
              {FOLLOW_UPS.map(([q, a]) => (
                <button key={q} onClick={() => setAnswer(a)} className="rounded-full border border-indigo-500/40 px-3 py-1 text-[12px] text-indigo-200 hover:bg-indigo-500/15">{q}</button>
              ))}
              <button onClick={() => { go(0); setPlaying(true) }} className="rounded-full border border-slate-700 px-3 py-1 text-[12px] text-slate-400 hover:text-slate-200">↻ Replay</button>
            </div>
          )}
          <div className="mt-3 flex gap-1">
            {STAGES.map((s, i) => (
              <button key={s.key} onClick={() => { setPlaying(false); go(i) }} aria-label={s.title}
                className={`h-1.5 flex-1 rounded-full transition-colors ${i <= stage ? 'bg-indigo-400' : 'bg-slate-700'}`} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

