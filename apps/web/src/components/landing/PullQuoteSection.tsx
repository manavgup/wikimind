export function PullQuoteSection() {
  return (
    <section className="border-b border-slate-200 bg-brand-50 py-20" id="quote">
      <div className="mx-auto max-w-[760px] px-8 text-center">
        <div
          className="font-serif-italic text-slate-900"
          style={{
            fontSize: "clamp(26px, 3.4vw, 38px)",
            lineHeight: "1.25",
            letterSpacing: "-0.005em",
            maxWidth: "24ch",
            textWrap: "balance",
            margin: "0 auto",
          }}
        >
          &#x201c;The tedious part of maintaining a knowledge base is not the reading or the
          thinking — it&#x2019;s the bookkeeping.&#x201d;
        </div>
        <div
          className="mt-6 text-[12px] font-medium uppercase text-slate-500"
          style={{ fontFamily: "Inter, sans-serif", fontStyle: "normal", letterSpacing: "0.04em" }}
        >
          — Andrej Karpathy · the original LLM Wiki gist
        </div>
      </div>
    </section>
  );
}
