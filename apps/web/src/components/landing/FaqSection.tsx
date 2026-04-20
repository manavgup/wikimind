import { useState } from "react";

interface FaqItem {
  question: string;
  answer: string;
}

const FAQ_ITEMS: FaqItem[] = [
  {
    question: "Is my data private?",
    answer:
      "Yes. WikiMind is designed to run locally or on your own infrastructure. Your sources, compiled wiki, and conversations never leave your machine unless you explicitly configure a remote LLM provider. Even then, only the content sent to the LLM for compilation passes through the provider API.",
  },
  {
    question: "Which LLM providers are supported?",
    answer:
      "WikiMind supports OpenAI (GPT-4o, GPT-4), Anthropic (Claude), and local models via Ollama or any OpenAI-compatible endpoint. You can switch providers at any time through the settings.",
  },
  {
    question: "Can I self-host?",
    answer:
      "Absolutely. WikiMind is a Python FastAPI application with a React frontend. You can run it on any machine with Python 3.11+ and Node.js. Docker images are also available. The default storage is SQLite, so there is no database server to set up.",
  },
  {
    question: "How does compilation work?",
    answer:
      "When you ingest a source, WikiMind extracts the content, normalizes it, and sends it to the configured LLM with instructions to synthesize it into structured wiki articles. If an article on the topic already exists, the compiler merges new information into the existing article, creating a continuously refined knowledge base.",
  },
  {
    question: "Is it free?",
    answer:
      "WikiMind itself is open source and free. The only cost is your LLM provider usage. If you run a local model via Ollama, there is no cost at all. Cloud LLM costs depend on the provider and how much content you ingest.",
  },
];

function FaqAccordionItem({ item }: { item: FaqItem }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border-b border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-5 text-left transition hover:text-zinc-200"
      >
        <span className="text-sm font-medium text-zinc-200 sm:text-base">{item.question}</span>
        <svg
          className={`h-4 w-4 shrink-0 text-zinc-500 transition-transform duration-200 ${
            open ? "rotate-180" : ""
          }`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
        </svg>
      </button>
      <div
        className={`overflow-hidden transition-all duration-200 ${
          open ? "max-h-96 pb-5" : "max-h-0"
        }`}
      >
        <p className="text-sm leading-relaxed text-zinc-400">{item.answer}</p>
      </div>
    </div>
  );
}

export function FaqSection() {
  return (
    <section className="border-t border-zinc-900 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-2xl">
        <h2 className="mb-8 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          Frequently asked questions
        </h2>
        <div className="divide-y divide-zinc-800 border-t border-zinc-800">
          {FAQ_ITEMS.map((item) => (
            <FaqAccordionItem key={item.question} item={item} />
          ))}
        </div>
      </div>
    </section>
  );
}
