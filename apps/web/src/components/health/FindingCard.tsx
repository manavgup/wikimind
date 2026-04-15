import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useWebSocketStore } from "../../store/websocket";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { useDismissFinding } from "../../hooks/useLint";
import {
  getResolutionOptions,
  recompileArticle,
  resolveContradiction,
} from "../../api/lint";
import type {
  LintContradictionFinding,
  LintFinding,
  LintOrphanFinding,
  LintSeverity,
  LintStructuralFinding,
  ResolutionOption,
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

function useResolutionOptions() {
  return useQuery<ResolutionOption[]>({
    queryKey: ["contradiction-resolutions"],
    queryFn: getResolutionOptions,
    staleTime: Infinity,
  });
}

/* ------------------------------------------------------------------ */
/*  ResolveDropdown                                                    */
/* ------------------------------------------------------------------ */

function ResolveDropdown({ finding, resolution }: { finding: LintContradictionFinding; resolution?: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const { data: options = [] } = useResolutionOptions();

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
            {options.map((opt) => (
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
  const [scheduled, setScheduled] = useState(false);
  const lastEvent = useWebSocketStore((s) => s.lastEvent);

  const recompile = useMutation({
    mutationFn: () => recompileArticle(articleId),
    onSuccess: () => setScheduled(true),
  });

  // Reset when WebSocket reports this article's recompile is done
  useEffect(() => {
    if (
      scheduled &&
      lastEvent &&
      lastEvent.event === "article.recompiled" &&
      "article_id" in lastEvent &&
      lastEvent.article_id === articleId
    ) {
      setScheduled(false);
    }
  }, [lastEvent, articleId, scheduled]);

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

function StructuralDetail({ finding }: { finding: LintStructuralFinding }) {
  const typeColors: Record<string, string> = {
    source_no_concepts: "bg-red-100 text-red-700",
    concept_insufficient_synthesizes: "bg-amber-100 text-amber-700",
    missing_inverse_link: "bg-blue-100 text-blue-700",
  };
  const color =
    typeColors[finding.violation_type] ?? "bg-slate-100 text-slate-700";

  return (
    <div className="mt-2 space-y-1 text-sm">
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-xs font-medium ${color}`}
        >
          {finding.violation_type.replace(/_/g, " ")}
        </span>
        {finding.auto_repaired && (
          <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-700">
            Auto-fixed
          </span>
        )}
      </div>
      <p className="text-slate-600">{finding.detail}</p>
    </div>
  );
}

function StructuralActions({ finding }: { finding: LintStructuralFinding }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Link
        to={`/wiki/${finding.article_id}`}
        className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
      >
        View Article
      </Link>
      {!finding.auto_repaired && (
        <RecompileButton articleId={finding.article_id} />
      )}
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
      ) : finding.kind === "structural" ? (
        <>
          <StructuralDetail finding={finding as LintStructuralFinding} />
          <StructuralActions finding={finding as LintStructuralFinding} />
        </>
      ) : (
        <>
          <OrphanDetail finding={finding as LintOrphanFinding} />
          <OrphanActions finding={finding as LintOrphanFinding} />
        </>
      )}
    </Card>
  );
}
