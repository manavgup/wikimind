import { useState, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  listArticles,
  previewSynthesis,
  refineSynthesis,
  confirmSynthesis,
} from "../../api/wiki";
import type {
  SynthesisType,
  SynthesisPreviewResponse,
  SynthesisResponse,
} from "../../api/wiki";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { Badge } from "../shared/Badge";
import { Spinner } from "../shared/Spinner";

const SYNTHESIS_TYPES: {
  value: SynthesisType;
  label: string;
  description: string;
}[] = [
  {
    value: "comparative",
    label: "Comparative",
    description:
      "Compare and contrast key ideas, methods, or findings across selected articles.",
  },
  {
    value: "chronological",
    label: "Chronological",
    description:
      "Trace the evolution of ideas or developments over time across your sources.",
  },
  {
    value: "thematic",
    label: "Thematic",
    description:
      "Identify and organize recurring themes, patterns, and connections.",
  },
  {
    value: "gap_analysis",
    label: "Gap Analysis",
    description:
      "Find contradictions, missing perspectives, and areas needing further research.",
  },
];

type WizardStep = 1 | 2 | 3 | 4;

interface SynthesisWizardProps {
  onCreated: (resp: SynthesisResponse) => void;
  onCancel?: () => void;
}

export function SynthesisWizard({ onCreated, onCancel }: SynthesisWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [synthesisType, setSynthesisType] = useState<SynthesisType | null>(
    null,
  );
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [guidance, setGuidance] = useState("");
  const [preview, setPreview] = useState<SynthesisPreviewResponse | null>(null);
  const [feedback, setFeedback] = useState("");

  const { data: articles, isLoading: articlesLoading } = useQuery({
    queryKey: ["articles", { page_type: "source" }],
    queryFn: () => listArticles({ page_type: "source", limit: 200 }),
  });

  const filteredArticles = useMemo(() => {
    if (!articles) return [];
    if (!searchQuery.trim()) return articles;
    const q = searchQuery.toLowerCase();
    return articles.filter(
      (a) =>
        a.title.toLowerCase().includes(q) ||
        (a.summary && a.summary.toLowerCase().includes(q)),
    );
  }, [articles, searchQuery]);

  const previewMutation = useMutation({
    mutationFn: previewSynthesis,
    onSuccess: (data) => {
      setPreview(data);
      setStep(4);
    },
  });

  const refineMutation = useMutation({
    mutationFn: refineSynthesis,
    onSuccess: (data) => {
      setPreview(data);
      setFeedback("");
    },
  });

  const confirmMutation = useMutation({
    mutationFn: confirmSynthesis,
    onSuccess: (data) => onCreated(data),
  });

  const toggleArticle = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const handlePreview = () => {
    if (!synthesisType || selectedIds.length < 2) return;
    previewMutation.mutate({
      synthesis_type: synthesisType,
      article_ids: selectedIds,
      guidance: guidance.trim() || undefined,
    });
  };

  const handleRefine = () => {
    if (!preview || !feedback.trim()) return;
    refineMutation.mutate({
      preview_id: preview.preview_id,
      feedback: feedback.trim(),
    });
  };

  const handleConfirm = () => {
    if (!preview) return;
    confirmMutation.mutate({ preview_id: preview.preview_id });
  };

  const canAdvance = (): boolean => {
    switch (step) {
      case 1:
        return synthesisType !== null;
      case 2:
        return selectedIds.length >= 2;
      case 3:
        return true;
      case 4:
        return preview !== null;
    }
  };

  const stepLabels = ["Type", "Articles", "Guidance", "Review"];

  return (
    <div className="space-y-6">
      {/* Progress indicator */}
      <nav aria-label="Wizard progress" className="flex items-center gap-2">
        {stepLabels.map((label, idx) => {
          const stepNum = (idx + 1) as WizardStep;
          const isActive = step === stepNum;
          const isComplete = step > stepNum;
          return (
            <div key={label} className="flex items-center gap-2">
              {idx > 0 && (
                <div
                  className={`h-px w-6 ${isComplete ? "bg-indigo-400" : "bg-slate-200"}`}
                />
              )}
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium ${
                  isActive
                    ? "bg-indigo-600 text-white"
                    : isComplete
                      ? "bg-indigo-100 text-indigo-700"
                      : "bg-slate-100 text-slate-400"
                }`}
              >
                {isComplete ? (
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2.5}
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M4.5 12.75l6 6 9-13.5"
                    />
                  </svg>
                ) : (
                  stepNum
                )}
              </div>
              <span
                className={`text-xs font-medium ${isActive ? "text-slate-800" : "text-slate-400"}`}
              >
                {label}
              </span>
            </div>
          );
        })}
      </nav>

      {/* Step 1: Select synthesis type */}
      {step === 1 && (
        <div className="space-y-3" data-testid="wizard-step-type">
          <p className="text-sm text-slate-600">
            Choose the type of synthesis to create.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {SYNTHESIS_TYPES.map((t) => (
              <Card
                key={t.value}
                className={`p-4 ${synthesisType === t.value ? "border-indigo-500 ring-1 ring-indigo-500" : ""}`}
                onClick={() => setSynthesisType(t.value)}
              >
                <div className="flex items-start gap-2">
                  <input
                    type="radio"
                    name="synthesis-type"
                    checked={synthesisType === t.value}
                    onChange={() => setSynthesisType(t.value)}
                    className="mt-0.5 text-indigo-600 focus:ring-indigo-500"
                  />
                  <div>
                    <span className="text-sm font-medium text-slate-800">
                      {t.label}
                    </span>
                    <p className="mt-0.5 text-xs text-slate-500">
                      {t.description}
                    </p>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {/* Step 2: Select articles */}
      {step === 2 && (
        <div className="space-y-3" data-testid="wizard-step-articles">
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-600">
              Select at least 2 articles to synthesize.
            </p>
            <Badge tone={selectedIds.length >= 2 ? "success" : "neutral"}>
              {selectedIds.length} selected
            </Badge>
          </div>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search articles..."
            className="block w-full rounded-lg border border-slate-300 px-4 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            data-testid="article-search-input"
          />
          <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-slate-200 bg-white p-3">
            {articlesLoading ? (
              <div className="flex items-center gap-2 py-4 text-sm text-slate-500">
                <Spinner size={14} /> Loading articles...
              </div>
            ) : filteredArticles.length > 0 ? (
              filteredArticles.map((article) => (
                <label
                  key={article.id}
                  className={`flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50 ${
                    selectedIds.includes(article.id) ? "bg-indigo-50" : ""
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(article.id)}
                    onChange={() => toggleArticle(article.id)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="truncate text-slate-700">
                    {article.title}
                  </span>
                  <span className="ml-auto shrink-0 text-xs text-slate-400">
                    {article.page_type}
                  </span>
                </label>
              ))
            ) : (
              <p className="py-4 text-center text-sm text-slate-400">
                {articles && articles.length === 0
                  ? "No source articles found. Ingest some sources first."
                  : "No articles match your search."}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Step 3: Guidance */}
      {step === 3 && (
        <div className="space-y-3" data-testid="wizard-step-guidance">
          <p className="text-sm text-slate-600">
            Optionally provide guidance to focus the synthesis. Leave blank for a
            general synthesis.
          </p>
          <textarea
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            placeholder='e.g. "Focus on methodology differences" or "Highlight areas of disagreement"'
            rows={4}
            className="block w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            data-testid="guidance-input"
          />
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <h4 className="text-xs font-medium text-slate-600">Summary</h4>
            <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
              <li>
                Type:{" "}
                <span className="font-medium text-slate-700">
                  {SYNTHESIS_TYPES.find((t) => t.value === synthesisType)
                    ?.label ?? ""}
                </span>
              </li>
              <li>
                Articles:{" "}
                <span className="font-medium text-slate-700">
                  {selectedIds.length} selected
                </span>
              </li>
            </ul>
          </div>
        </div>
      )}

      {/* Step 4: Review draft */}
      {step === 4 && (
        <div className="space-y-4" data-testid="wizard-step-review">
          {previewMutation.isPending ? (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
              <Spinner size={16} /> Generating synthesis preview...
            </div>
          ) : previewMutation.isError ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
              {(previewMutation.error as Error)?.message ||
                "Failed to generate preview."}
            </div>
          ) : preview ? (
            <>
              <div>
                <h3 className="text-base font-semibold text-slate-800">
                  {preview.title}
                </h3>
                <div className="mt-1 flex flex-wrap gap-1">
                  {preview.themes.map((theme) => (
                    <Badge key={theme} tone="brand">
                      {theme}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                <pre className="whitespace-pre-wrap font-sans">
                  {preview.draft_markdown}
                </pre>
              </div>
              <div className="space-y-2">
                <label className="block text-sm font-medium text-slate-700">
                  Refinement feedback (optional)
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Add more detail on methodology..."
                    className="block flex-1 rounded-lg border border-slate-300 px-4 py-2 text-sm shadow-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                    disabled={refineMutation.isPending}
                    data-testid="refine-input"
                  />
                  <Button
                    variant="secondary"
                    onClick={handleRefine}
                    disabled={
                      !feedback.trim() || refineMutation.isPending
                    }
                  >
                    {refineMutation.isPending ? (
                      <Spinner size={14} />
                    ) : null}
                    Refine
                  </Button>
                </div>
                {refineMutation.isError && (
                  <p className="text-xs text-rose-600">
                    {(refineMutation.error as Error)?.message ||
                      "Refinement failed."}
                  </p>
                )}
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Error for preview generation shown in step 3 context */}
      {step === 3 && previewMutation.isError && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {(previewMutation.error as Error)?.message ||
            "Failed to generate preview."}
        </div>
      )}

      {/* Navigation buttons */}
      <div className="flex items-center justify-between border-t border-slate-200 pt-4">
        <div>
          {step > 1 && step < 4 && (
            <Button
              variant="ghost"
              onClick={() => setStep((step - 1) as WizardStep)}
            >
              Back
            </Button>
          )}
          {step === 4 && !confirmMutation.isPending && (
            <Button variant="ghost" onClick={() => setStep(3)}>
              Back
            </Button>
          )}
          {onCancel && step === 1 && (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {step < 3 && (
            <Button
              variant="primary"
              disabled={!canAdvance()}
              onClick={() => setStep((step + 1) as WizardStep)}
            >
              Next
            </Button>
          )}
          {step === 3 && (
            <Button
              variant="primary"
              disabled={previewMutation.isPending}
              onClick={handlePreview}
            >
              {previewMutation.isPending ? (
                <Spinner size={14} />
              ) : null}
              Generate Preview
            </Button>
          )}
          {step === 4 && preview && (
            <Button
              variant="primary"
              disabled={confirmMutation.isPending}
              onClick={handleConfirm}
              data-testid="confirm-synthesis-btn"
            >
              {confirmMutation.isPending ? (
                <Spinner size={14} />
              ) : null}
              {confirmMutation.isPending ? "Creating..." : "Confirm & Create"}
            </Button>
          )}
        </div>
      </div>

      {confirmMutation.isError && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {(confirmMutation.error as Error)?.message ||
            "Failed to create synthesis."}
        </div>
      )}
    </div>
  );
}
