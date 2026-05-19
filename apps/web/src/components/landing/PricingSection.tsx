interface PricingSectionProps {
  onSignIn: () => void;
}

interface PlanCard {
  name: string;
  price: string;
  interval: string;
  description: string;
  features: string[];
  cta: string;
  highlighted: boolean;
}

const PLANS: PlanCard[] = [
  {
    name: "Free",
    price: "$0",
    interval: "forever",
    description: "For personal exploration and light use.",
    features: [
      "Up to 25 sources",
      "Up to 50 wiki articles",
      "30 queries per day",
      "100 MB storage",
      "3 active share links",
      "PDF & Markdown export",
    ],
    cta: "Get started",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$12",
    interval: "/month",
    description: "For power users and serious research.",
    features: [
      "Unlimited sources",
      "Unlimited wiki articles",
      "Unlimited queries",
      "10 GB storage",
      "Unlimited share links",
      "All export formats",
      "MCP server access",
      "Bring your own API key",
    ],
    cta: "Start free, upgrade anytime",
    highlighted: true,
  },
];

export function PricingSection({ onSignIn }: PricingSectionProps) {
  return (
    <section className="border-b border-slate-200 py-20" id="pricing">
      <div className="mx-auto max-w-[1120px] px-8">
        <div className="mb-12 text-center">
          <div
            className="text-[11px] font-semibold uppercase text-brand-700"
            style={{ letterSpacing: "0.08em" }}
          >
            pricing
          </div>
          <h2
            className="mx-auto mt-3 font-bold text-slate-900"
            style={{
              fontSize: "clamp(28px, 3.6vw, 42px)",
              lineHeight: "1.1",
              letterSpacing: "-0.02em",
              textWrap: "balance",
              maxWidth: "24ch",
            }}
          >
            Simple, transparent pricing
          </h2>
          <p
            className="mx-auto mt-4 text-[17px] text-slate-700"
            style={{ lineHeight: "1.55", maxWidth: "48ch", textWrap: "pretty" }}
          >
            Start for free. Upgrade when you need more capacity.
          </p>
        </div>

        <div className="mx-auto grid max-w-[720px] gap-6 sm:grid-cols-2">
          {PLANS.map((plan) => (
            <div
              key={plan.name}
              className={`flex flex-col rounded-xl border p-6 ${
                plan.highlighted
                  ? "border-brand-300 bg-brand-50/30 shadow-md"
                  : "border-slate-200 bg-white shadow-sm"
              }`}
            >
              {plan.highlighted && (
                <div
                  className="mb-4 inline-flex self-start rounded-full bg-brand-700 px-2.5 py-0.5 text-[10px] font-semibold uppercase text-white"
                  style={{ letterSpacing: "0.06em" }}
                >
                  Most popular
                </div>
              )}
              <h3
                className="text-[22px] font-bold text-slate-900"
                style={{ letterSpacing: "-0.01em" }}
              >
                {plan.name}
              </h3>
              <div className="mt-2 flex items-baseline gap-1">
                <span
                  className="text-[36px] font-bold text-slate-900"
                  style={{ letterSpacing: "-0.02em" }}
                >
                  {plan.price}
                </span>
                <span className="text-[14px] text-slate-500">{plan.interval}</span>
              </div>
              <p className="mt-2 text-[14px] text-slate-600">{plan.description}</p>

              <ul className="mt-6 flex flex-1 flex-col gap-2.5">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2 text-[13px] text-slate-700">
                    <span className="mt-0.5 text-emerald-600">&#10003;</span>
                    {feature}
                  </li>
                ))}
              </ul>

              <button
                type="button"
                onClick={onSignIn}
                className={`mt-8 w-full rounded-md px-4 py-2.5 text-[14px] font-medium transition-colors duration-100 ${
                  plan.highlighted
                    ? "bg-brand-700 text-white hover:bg-brand-800"
                    : "border border-slate-300 bg-white text-slate-700 hover:border-brand-300 hover:text-slate-900"
                }`}
              >
                {plan.cta}
              </button>
            </div>
          ))}
        </div>

        <p className="mt-8 text-center text-[13px] text-slate-500">
          Prefer to self-host?{" "}
          <a
            href="https://github.com/manavgup/wikimind"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-800"
          >
            Self-host for free
          </a>{" "}
          with no limits.
        </p>
      </div>
    </section>
  );
}
