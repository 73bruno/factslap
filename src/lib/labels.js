// Display names shared by the result view, the live steps and the "How it works" chat.

export const STEPS = [
  { key: 'plan', label: 'Plan', short: 'Plan' },
  { key: 'search', label: 'Search', short: 'Search' },
  { key: 'rank', label: 'Rank', short: 'Rank' },
  { key: 'evidence', label: 'Read', short: 'Read' },
  { key: 'verdict', label: 'Verdict', short: 'Verdict' },
  { key: 'verify', label: 'Write & verify', short: 'Verify' },
  { key: 'tone', label: 'Tone', short: 'Tone' },
]

export const STEP_HINTS = {
  cache: 'Same claim checked recently: served from the cache',
  plan: 'Splitting the claim and writing scientific search queries',
  search: 'Searching papers, fact-checks and encyclopedias in parallel',
  rank: 'Hybrid ranking: keywords + embeddings, then an AI reranker',
  evidence: 'Reading each passage: supports, refutes or neutral?',
  verdict: 'Weighing the evidence by study quality',
  verify: 'Writing the answer and checking every citation',
  tone: 'Rewording it in your tone (facts locked)',
}

export const VERDICTS = {
  supported: { label: 'Supported', tone: 'emerald', blurb: 'The evidence backs this claim.' },
  refuted: { label: 'Refuted', tone: 'red', blurb: 'The evidence goes against this claim.' },
  mixed: { label: 'Mixed evidence', tone: 'amber', blurb: 'Studies disagree on this one.' },
  not_enough_evidence: { label: 'Not enough evidence', tone: 'slate', blurb: "We couldn't find enough solid evidence either way." },
}

export const STANCES = {
  supports: { label: 'Supports', className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  refutes: { label: 'Refutes', className: 'bg-red-500/15 text-red-300 border-red-500/40' },
  neutral: { label: 'Context', className: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
}

export const SOURCES = {
  semantic_scholar: 'Semantic Scholar',
  openalex: 'OpenAlex',
  europe_pmc: 'Europe PMC',
  fact_check: 'Google Fact Check',
  wikipedia: 'Wikipedia',
  world_bank: 'World Bank',
  open_food_facts: 'Open Food Facts',
  index: 'FactSlap index',
}

export const STUDY_TYPES = {
  meta_analysis: 'Meta-analysis',
  systematic_review: 'Systematic review',
  rct: 'Randomised trial',
  observational: 'Observational study',
  review: 'Review',
  fact_check: 'Fact-check',
  encyclopedia: 'Encyclopedia',
  data: 'Open data',
  other: 'Study',
}

export const DISCLAIMER =
  'The verdict is decided first, from the evidence alone. The tone only changes the wording, never the verdict or the sources. FactSlap summarises published research and can be wrong; it is not medical, legal or financial advice.'
