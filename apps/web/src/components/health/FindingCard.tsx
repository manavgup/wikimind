import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { useDismissFinding } from "../../hooks/useLint";
import {
  recompileArticle,
  resolveContradiction,
} from "../../api/lint";
import type {
  LintContradictionFinding,
  LintFinding,
  LintOrphanFinding,
  LintSeverity,
} from "../../api/lint";

interface Props {
  finding: LintFinding;
  resolutions?: Record<string, string>;
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

const RESOLUTION_OPTIONS = [
  { value: "source_a_wins", label: "Source A wins" },
  { value: "source_b_wins", label: "Source B wins" },
  { value: "both_valid", label: "Both valid" },
  { value: "superseded", label: "Superseded" },
] as const;

/* ------------------------------------------------------------------ */
/*  ResolveDropdown                                                    */
/* ------------------------------------------------------------------ */

function ResolveDropdown({ finding, resolution }: { finding: LintContradictionFinding; resolution?: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");

  const resolve = useMutation({
    mutationFn: (res: string) =>
      resolveContradiction(
        finding.article_a_id,
        finding.article_b_id,
        res,
        note || undefined,
      ),
    onSuccess: () => {
      setOpen(false);
      queryClient.invalidateQueries({ queryKey: ["lint"] });
    },
  });

  if (resolution) {
    return (
      <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
        {resolution.replace(/_/g, " ")}
      </span>
    );
  }

  return (
    <div className="relative">
      <button
        type="button"
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
        onClick={() => setOpen((prev) => !prev)}
      >
        Resolve
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
          <div className="mb-2 space-y-1">
            {RESOLUTION_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={resolve.isPending}
                className="block w-full rounded px-2 py-1 text-left text-xs text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                onClick={() => resolve.mutate(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <input
            type="text"
            placeholder="Optional note..."
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded border border-slate-200 px-2 py-1 text-xs text-slate-700 placeholder:text-slate-400 focus:border-sky-300 focus:outline-none"
          />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  RecompileButton                                                    */
/* ------------------------------------------------------------------ */

function RecompileButton({ articleId }: { articleId: string }) {
  const queryClient = useQueryClient();
  const [scheduled, setScheduled] = useState(false);

  const recompile = useMutation({
    mutationFn: () => recompileArticle(articleId),
    onSuccess: () => {
      setScheduled(true);
      queryClient.invalidateQueries({ queryKey: ["lint"] });
    },
  });

  return (
    <button
      type="button"
      disabled={recompile.isPending || scheduled}
      className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
      onClick={() => recompile.mutate()}
    >
      {recompile.isPending
        ? "Scheduling..."
        : scheduled
          ? "Recompiling..."
          : "Recompile"}
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Detail sub-components                                              */
/* ------------------------------------------------------------------ */

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

/* ------------------------------------------------------------------ */
/*  Action rows per finding kind                                       */
/* ------------------------------------------------------------------ */

function ContradictionActions({
  finding,
  resolution,
}: {
  finding: LintContradictionFinding;
  resolution?: string;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Link
        to={`/wiki/${finding.article_a_id}`}
        className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
      >
        View Article A
      </Link>
      <Link
        to={`/wiki/${finding.article_b_id}`}
        className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
      >
        View Article B
      </Link>
      <RecompileButton articleId={finding.article_a_id} />
      <ResolveDropdown finding={finding} resolution={resolution} />
    </div>
  );
}

function OrphanActions({ finding }: { finding: LintOrphanFinding }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Link
        to={`/wiki/${finding.article_id}`}
        className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
      >
        View Article
      </Link>
      <RecompileButton articleId={finding.article_id} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  FindingCard (exported)                                             */
/* ------------------------------------------------------------------ */

export function FindingCard({ finding, resolutions }: Props) {
  const dismiss = useDismissFinding();

  const resolution =
    finding.kind === "contradiction" && resolutions
      ? resolutions[`${finding.article_a_id}|${finding.article_b_id}`]
      : undefined;

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
        <>
          <ContradictionDetail finding={finding} />
          <ContradictionActions finding={finding} resolution={resolution} />
        </>
      ) : (
        <>
          <OrphanDetail finding={finding} />
          <OrphanActions finding={finding} />
        </>
      )}
    </Card>
  );
}
