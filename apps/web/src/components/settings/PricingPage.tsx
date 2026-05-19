import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { getPlans, createCheckout } from "../../api/billing";
import type { PlanInfo } from "../../api/billing";

export function PricingPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState<string | null>(null);

  const { data: plans, isLoading } = useQuery({
    queryKey: ["billing-plans"],
    queryFn: getPlans,
  });

  async function handleSelectPlan(plan: PlanInfo) {
    if (plan.price_cents === 0) {
      navigate("/settings/billing");
      return;
    }
    setLoading(plan.id);
    try {
      const { checkout_url } = await createCheckout(plan.id);
      window.location.href = checkout_url;
    } catch {
      setLoading(null);
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl p-6">
        <h1 className="mb-2 text-2xl font-bold text-slate-900">Plans & Pricing</h1>
        <p className="mb-8 text-sm text-slate-500">
          Choose the plan that fits your needs. Upgrade or downgrade anytime.
        </p>

        <div className="grid gap-6 sm:grid-cols-2">
          {(plans ?? []).map((plan) => {
            const isFree = plan.price_cents === 0;
            const highlighted = !isFree;
            return (
              <Card
                key={plan.id}
                className={`flex flex-col p-6 ${highlighted ? "border-brand-300 shadow-md" : ""}`}
              >
                <h3 className="text-xl font-bold text-slate-900">{plan.display_name}</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="text-3xl font-bold text-slate-900">
                    ${(plan.price_cents / 100).toFixed(plan.price_cents % 100 === 0 ? 0 : 2)}
                  </span>
                  {plan.billing_interval && (
                    <span className="text-sm text-slate-500">/{plan.billing_interval}</span>
                  )}
                </div>

                <ul className="mt-5 flex flex-1 flex-col gap-2 text-sm text-slate-700">
                  <li>Up to {plan.max_sources ?? "unlimited"} sources</li>
                  <li>Up to {plan.max_articles ?? "unlimited"} articles</li>
                  <li>{plan.max_queries_per_day ?? "unlimited"} queries/day</li>
                  <li>{plan.max_active_shares ?? "unlimited"} share links</li>
                  <li>{plan.allowed_exports.length} export format{plan.allowed_exports.length !== 1 ? "s" : ""}</li>
                  {plan.mcp_enabled && <li>MCP server access</li>}
                  {plan.byok_allowed && <li>Bring your own API key</li>}
                </ul>

                <Button
                  className="mt-6 w-full"
                  variant={highlighted ? "primary" : "secondary"}
                  onClick={() => handleSelectPlan(plan)}
                  disabled={loading === plan.id}
                >
                  {loading === plan.id
                    ? "Redirecting..."
                    : isFree
                      ? "Current plan"
                      : "Upgrade to Pro"}
                </Button>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
