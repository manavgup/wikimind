import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { useDismissFinding } from "../../hooks/useLint";
import type {
  LintContradictionFinding,
  LintFinding,
  LintOrphanFinding,
  LintSeverity,
} from "../../api/lint";

interface Props {
  finding: LintFinding;
}

const severityTone: Record<LintSeverity, BadgeTone> = {
  info: "info",
  warn: "warning",
  error: "danger",
};

const confidenceTone: Record<string, BadgeTone> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
};

function ContradictionDetail({
  finding,
}: {
  finding: LintContradictionFinding;
}) {
  return (
    <div className="mt-2 space-y-2 text-sm">
      <div className="rounded-md bg-slate-50 p-2">
        <div className="text-xs font-medium text-slate-500">Article A claim</div>
        <div className="text-slate-700">{finding.article_a_claim}</div>
      </div>
      <div className="rounded-md bg-slate-50 p-2">
        <div className="text-xs font-medium text-slate-500">Article B claim</div>
        <div className="text-slate-700">{finding.article_b_claim}</div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">LLM confidence:</span>
        <Badge tone={confidenceTone[finding.llm_confidence] ?? "neutral"}>
          {finding.llm_confidence}
        </Badge>
      </div>
    </div>
  );
}

function OrphanDetail({ finding }: { finding: LintOrphanFinding }) {
  return (
    <div className="mt-2 text-sm text-slate-600">
      Article <span className="font-medium">{finding.article_title}</span> has
      no inbound or outbound links.
    </div>
  );
}

export function FindingCard({ finding }: Props) {
  const dismiss = useDismissFinding();

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <Badge tone={severityTone[finding.severity]}>{finding.severity}</Badge>
          <span className="text-sm font-medium text-slate-800">
            {finding.description}
          </span>
        </div>
        {!finding.dismissed ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={dismiss.isPending}
            onClick={() =>
              dismiss.mutate({ kind: finding.kind, id: finding.id })
            }
          >
            Dismiss
          </Button>
        ) : (
          <Badge tone="neutral">Dismissed</Badge>
        )}
      </div>

      {finding.kind === "contradiction" ? (
        <ContradictionDetail finding={finding} />
      ) : (
        <OrphanDetail finding={finding} />
      )}
    </Card>
  );
}
