const FAQ_ITEMS = [
  {
    question: "Where does my data live?",
    answer:
      "Locally. Raw sources and the wiki are plain files on your disk \u2014 a git repo, if you want version history. WikiMind never phones home. LLM calls go to whichever provider you\u2019ve configured.",
  },
  {
    question: "Which LLM does it use?",
    answerHtml: true,
    answer:
      'Bring your own. Configure any combination of <code>OpenAI</code>, <code>Anthropic</code>, <code>Google</code>, or a local <code>Ollama</code> model in Settings. You\u2019ll see the per\u2011source cost before and after ingest.',
  },
  {
    question: "How is this different from NotebookLM or ChatGPT file upload?",
    answer:
      "Those are retrieval systems. The LLM re\u2011reads your files on every query and never builds anything persistent. WikiMind compiles your sources into a wiki you can actually browse, edit, and version \u2014 and the LLM reads the wiki, not the raw files.",
  },
  {
    question: "What if I disagree with what the LLM wrote?",
    answer:
      "Every claim has a confidence tag: sourced \u00b7 mixed \u00b7 inferred \u00b7 opinion. Edits are first\u2011class \u2014 you can revise any page and the LLM will respect your version on the next compile. The wiki is yours.",
  },
  {
    question: "Does it scale?",
    answerHtml: true,
    answer:
      'To a few thousand sources, comfortably. At small scale the <code>index.md</code> catalog is enough for the LLM to navigate. As the wiki grows, an on\u2011disk BM25 + vector search kicks in automatically so the LLM always gets the right pages into context.',
  },
  {
    question: "Is it open source?",
    answerHtml: true,
    answer:
      'Yes. Everything \u2014 the compiler, the schema format, the web app \u2014 ships as <code>MIT</code> on GitHub. The desktop version is an Electron shell around the same bundle.',
  },
];

export function FaqSection() {
  return (
    <section className="border-b border-slate-200 py-20" id="faq">
      <div className="mx-auto max-w-[760px] px-8">
        <div className="mb-6">
          <div
            className="text-[11px] font-semibold uppercase text-brand-700"
            style={{ letterSpacing: "0.08em" }}
          >
            questions
          </div>
          <h2
            className="mt-3 font-bold text-slate-900"
            style={{
              fontSize: "clamp(28px, 3.6vw, 42px)",
              lineHeight: "1.1",
              letterSpacing: "-0.02em",
            }}
          >
            Before you ask.
          </h2>
        </div>

        <div className="border-t border-slate-200">
          {FAQ_ITEMS.map((item) => (
            <details key={item.question} className="qa-item border-b border-slate-200">
              <summary className="flex cursor-pointer items-center justify-between gap-4 py-[22px] text-[17px] font-semibold text-slate-900 transition-colors duration-100 hover:text-brand-700">
                {item.question}
              </summary>
              {item.answerHtml ? (
                <div
                  className="pb-[22px] text-[15px] text-slate-700"
                  style={{ lineHeight: "1.65", maxWidth: "70ch" }}
                  dangerouslySetInnerHTML={{
                    __html: item.answer.replace(
                      /<code>/g,
                      '<code style="font-family:\'JetBrains Mono\',monospace;font-size:13px;background:#f1f5f9;padding:1px 5px;border-radius:4px;color:#0f172a;">'
                    ),
                  }}
                />
              ) : (
                <div
                  className="pb-[22px] text-[15px] text-slate-700"
                  style={{ lineHeight: "1.65", maxWidth: "70ch" }}
                >
                  {item.answer}
                </div>
              )}
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
