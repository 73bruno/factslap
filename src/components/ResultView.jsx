import { useState } from 'react'
import { shareUrl } from '../lib/api'
import { DISCLAIMER, SOURCES, STANCES, STUDY_TYPES, VERDICTS } from '../lib/labels'

const VERDICT_STYLES = {
  emerald: { ring: 'border-emerald-500/50', glow: 'shadow-emerald-500/20' },
  red: { ring: 'border-red-500/50', glow: 'shadow-red-500/20' },
  amber: { ring: 'border-amber-500/50', glow: 'shadow-amber-500/20' },
  slate: { ring: 'border-slate-500/50', glow: 'shadow-slate-500/20' },
}

// The word on the rubber stamp and its ink (same as the share card, factslap/share.py)
const STAMPS = {
  supported: { word: 'SUPPORTED', ink: '#16a34a' },
  refuted: { word: 'REFUTED', ink: '#dc2839' },
  mixed: { word: 'MIXED', ink: '#e28400' },
  not_enough_evidence: { word: 'UNPROVEN', ink: '#3456c4' },
}

function Stamp({ label, sources }) {
  const { word, ink } = STAMPS[label] || STAMPS.not_enough_evidence
  return (
    <div className="stamp animate-stamp" style={{ '--ink': ink }}>
      <div className="stamp-inner">
        <span aria-hidden>★ FACTSLAP ★</span>
        <span className="stamp-word">{word}</span>
        <span>{sources ? `${sources} SOURCES CITED` : 'NO SOLID SOURCES'}</span>
      </div>
    </div>
  )
}

/** Turn "text [1][2]" into text with clickable citation chips. */
function WithCitations({ text, onCite }) {
  const parts = text.split(/(\[\d+\])/g)
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/)
    if (!match) return <span key={i}>{part}</span>
    const ref = Number(match[1])
    return (
      <button
        key={i}
        type="button"
        onClick={() => onCite(ref)}
        className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-indigo-500/20 px-1 align-text-top text-[11px] font-bold text-indigo-300 hover:bg-indigo-500/40"
        aria-label={`Go to source ${ref}`}
      >
        {ref}
      </button>
    )
  })
}

function EvidenceCard({ item, highlighted }) {
  const p = item.passage
  const stance = STANCES[item.stance] || STANCES.neutral
  const meta = [p.year, STUDY_TYPES[p.study_type] || 'Study', SOURCES[p.source] || p.source].filter(Boolean).join(' · ')
  return (
    <li
      id={`evidence-${item.ref}`}
      className={`glass-card rounded-xl p-4 transition-all duration-500 ${highlighted ? 'ring-2 ring-indigo-400' : ''}`}
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-slate-700 text-xs font-bold text-slate-200">
          {item.ref}
        </span>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${stance.className}`}>{stance.label}</span>
            <span className="text-[11px] text-slate-500">{meta}</span>
          </div>
          {p.url ? (
            <a href={p.url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-slate-100 hover:text-indigo-300 hover:underline break-words">
              {p.title}
            </a>
          ) : (
            <p className="text-sm font-semibold text-slate-100 break-words">{p.title}</p>
          )}
          {item.quote && (
            <blockquote className="mt-2 border-l-2 border-indigo-400/60 pl-3 text-sm italic text-slate-300 break-words">“{item.quote}”</blockquote>
          )}
          {item.rationale && <p className="mt-1 text-xs text-slate-500">{item.rationale}</p>}
        </div>
      </div>
    </li>
  )
}

export default function ResultView({ result, onNewCheck, shared = false }) {
  const [highlight, setHighlight] = useState(null)
  const [copied, setCopied] = useState(false)
  const verdict = VERDICTS[result.verdict.label] || VERDICTS.not_enough_evidence
  const style = VERDICT_STYLES[verdict.tone]
  const answer = result.styled_answer || result.answer
  const confidence = Math.round(result.verdict.confidence * 100)
  const passedChecks = result.verification.checks.filter((c) => c.passed).length

  const cite = (ref) => {
    setHighlight(ref)
    document.getElementById(`evidence-${ref}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setTimeout(() => setHighlight(null), 1600)
  }

  const link = result.share_id ? shareUrl(result.share_id) : 'https://www.factslap.app'
  const shareText = `${answer.short || answer.text} — checked with FactSlap`
  const copy = async (what) => {
    try {
      await navigator.clipboard.writeText(what === 'link' ? link : `${shareText}\n${link}`)
      setCopied(what)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard blocked */ }
  }

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-in-up space-y-4 pb-24">
      <button onClick={onNewCheck} className="flex items-center gap-2 text-slate-400 transition-colors hover:text-slate-200">
        <span aria-hidden>←</span> <span className="font-medium">{shared ? 'Check your own claim' : 'New check'}</span>
      </button>

      <div className="report-paper animate-thud relative z-10 rounded-sm px-5 pb-6 pt-5 font-typewriter sm:px-8 sm:pt-7">
        <div className="flex items-baseline justify-between gap-3 text-sm">
          <span>FACT-CHECK REPORT</span>
          {result.share_id && <span className="text-xs text-[#6e6860]">No. {result.share_id}</span>}
        </div>
        <div className="mt-2 border-t-2 border-dashed border-[#a39a8c]" />
        <p className="mt-3 text-xs text-[#6e6860]">CLAIM:</p>
        <p className="mt-1 text-xl leading-snug break-words sm:text-[1.7rem]">“{result.claim}”</p>
        <div className="mt-5 flex min-h-[110px] items-end justify-between gap-2 sm:min-h-[96px]">
          <div className="space-y-0.5 whitespace-nowrap text-[11px] sm:text-sm">
            <p>CONFIDENCE: {confidence}%</p>
            <p>SUPPORT: {result.verdict.supporting}</p>
            <p>REFUTE: {result.verdict.refuting}</p>
          </div>
          <div className="-mb-12 -mr-2 shrink-0 sm:-mr-6">
            <Stamp label={result.verdict.label} sources={result.evidence.length} />
          </div>
        </div>
      </div>

      <div className={`glass-card rounded-2xl border-2 ${style.ring} p-5 shadow-2xl ${style.glow}`}>
        <p className="text-[15px] leading-relaxed text-slate-200">
          <WithCitations text={answer.text} onCite={cite} />
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <button onClick={() => copy('text')} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-500">
            {copied === 'text' ? 'Copied!' : 'Copy the comeback'}
          </button>
          {result.share_id && (
            <button onClick={() => copy('link')} className="rounded-lg border border-indigo-400/60 px-3 py-1.5 text-sm font-semibold text-indigo-200 hover:bg-indigo-500/15">
              {copied === 'link' ? 'Link copied!' : 'Copy share link'}
            </button>
          )}
          <a
            href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(link)}`}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-semibold text-slate-200 hover:border-slate-400"
          >
            Share on X
          </a>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px] text-slate-400">
        <span className="rounded-full border border-slate-700 px-2 py-1">✓ {passedChecks}/{result.verification.checks.length} checks passed</span>
        <span className="rounded-full border border-slate-700 px-2 py-1">{result.evidence.length} sources cited</span>
        <span className="rounded-full border border-slate-700 px-2 py-1 font-mono">{(result.latency_ms / 1000).toFixed(1)} s</span>
      </div>

      {result.evidence.length > 0 && (
        <section>
          <h2 className="mb-2 text-xs uppercase tracking-wider text-slate-400">Evidence</h2>
          <ol className="space-y-2">
            {result.evidence.map((item) => (
              <EvidenceCard key={item.ref} item={item} highlighted={highlight === item.ref} />
            ))}
          </ol>
        </section>
      )}

      <p className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-[11px] leading-relaxed text-slate-400">
        {result.disclaimer || DISCLAIMER}
      </p>
    </div>
  )
}
