const PAGES = {
  privacy: {
    title: 'Privacy',
    sections: [
      ['What we receive', [
        'The claim you type, your tone and intention choices, and your IP address (needed to deliver the page and to apply fair-use limits).',
      ]],
      ['What we do with it', [
        'Your claim is sent to OpenAI to plan the search, read the evidence and write the answer, and to public research catalogues (OpenAlex, Semantic Scholar, Europe PMC, Google Fact Check Tools, Wikipedia, World Bank, Open Food Facts) as a search query.',
        'Results of checks that pass our verification are cached for up to 7 days so identical claims are answered instantly.',
        'For fair-use limits we store a salted hash of your IP address, never the address itself, for about a day.',
      ]],
      ['What we do not do', [
        'No ads, no ad trackers and no selling of data. No account is needed.',
        'We use Vercel Web Analytics, which counts page views without cookies.',
      ]],
      ['Please', [
        "Don't type personal or sensitive information into the claim box.",
      ]],
    ],
  },
  terms: {
    title: 'Terms',
    sections: [
      ['What FactSlap is', [
        'FactSlap summarises published research and fact-checks with the help of AI. It can be wrong or incomplete: always read the cited sources before relying on an answer.',
        'It is not medical, legal, financial or any other professional advice.',
      ]],
      ['Tone and intention', [
        'The verdict is decided first, from the evidence alone. The tone and intention you choose only change the wording, never the verdict or the sources.',
      ]],
      ['Fair use', [
        'Free checks are limited per visitor and per day. Automated or abusive use is not allowed and is blocked.',
      ]],
      ['Sources', [
        'Cited papers and articles belong to their authors and publishers; we link to them and quote short passages to show the evidence.',
      ]],
    ],
  },
}

export default function LegalPage({ page, onBack }) {
  const content = PAGES[page]
  return (
    <div className="min-h-screen bg-slate-900 px-4 py-8 text-slate-200">
      <div className="mx-auto max-w-2xl space-y-6">
        <button onClick={onBack} className="text-slate-400 hover:text-slate-200">← Back</button>
        <h1 className="text-3xl font-extrabold">{content.title}</h1>
        {content.sections.map(([heading, paragraphs]) => (
          <section key={heading} className="glass-card space-y-2 rounded-xl p-4">
            <h2 className="font-semibold text-slate-100">{heading}</h2>
            {paragraphs.map((p) => <p key={p} className="text-sm leading-relaxed text-slate-300">{p}</p>)}
          </section>
        ))}
        <p className="text-xs text-slate-500">© {new Date().getFullYear()} FactSlap</p>
      </div>
    </div>
  )
}
