import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { ApiError } from "../../api/client";
import { setApiKey, testProvider, setDefaultProvider, completeOnboarding } from "../../api/settings";
import { ingestUrl } from "../../api/sources";
import { useWebSocketStore } from "../../store/websocket";
import type { WSEvent } from "../../types/api";

const STEPS = ["Welcome", "Configure LLM", "Add Source", "Compiling", "Done"];

const EXAMPLE_URLS = [
  "https://en.wikipedia.org/wiki/Large_language_model",
  "https://en.wikipedia.org/wiki/Knowledge_management",
  "https://en.wikipedia.org/wiki/Personal_knowledge_management",
];

export function OnboardingWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0);
  const queryClient = useQueryClient();

  const dismissMutation = useMutation({
    mutationFn: completeOnboarding,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["onboarding-status"] });
      onComplete();
    },
  });

  const handleDismiss = () => {
    dismissMutation.mutate();
  };

  const lastStep = STEPS.length - 1;

  const handleSkip = (currentStep: number) => {
    if (currentStep >= lastStep) {
      handleDismiss();
    } else {
      setStep(currentStep + 1);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60">
      <Card className="relative w-full max-w-lg p-0">
        <button
          type="button"
          onClick={handleDismiss}
          disabled={dismissMutation.isPending}
          className="absolute right-3 top-3 z-10 flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
          aria-label="Skip onboarding"
        >
          &#x2715;
        </button>
        <StepIndicator current={step} steps={STEPS} />
        <div className="p-6">
          {step === 0 && (
            <WelcomeStep
              onNext={() => setStep(1)}
              onSkip={() => handleSkip(0)}
            />
          )}
          {step === 1 && (
            <ConfigureLLMStep
              onNext={() => setStep(2)}
              onSkip={() => handleSkip(1)}
            />
          )}
          {step === 2 && (
            <AddSourceStep
              onNext={() => setStep(3)}
              onSkip={() => handleSkip(2)}
            />
          )}
          {step === 3 && (
            <CompilingStep
              onNext={() => setStep(4)}
              onSkip={() => handleSkip(3)}
            />
          )}
          {step === 4 && (
            <DoneStep
              onComplete={onComplete}
              onSkip={handleDismiss}
            />
          )}
        </div>
      </Card>
    </div>
  );
}

function StepIndicator({ current, steps }: { current: number; steps: string[] }) {
  return (
    <div className="flex border-b border-slate-200 px-6 pt-5 pb-4">
      {steps.map((label, i) => (
        <div key={label} className="flex flex-1 items-center">
          <div
            className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
              i < current
                ? "bg-emerald-500 text-white"
                : i === current
                  ? "bg-brand-600 text-white"
                  : "bg-slate-200 text-slate-500"
            }`}
          >
            {i < current ? "\u2713" : i + 1}
          </div>
          {i < steps.length - 1 && (
            <div
              className={`mx-1 h-0.5 flex-1 ${
                i < current ? "bg-emerald-400" : "bg-slate-200"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function WelcomeStep({
  onNext,
  onSkip,
}: {
  onNext: () => void;
  onSkip: () => void;
}) {
  return (
    <div className="text-center">
      <h2 className="mb-3 text-xl font-bold text-slate-900">
        Welcome to WikiMind
      </h2>
      <p className="mb-2 text-sm text-slate-600">
        WikiMind is your personal knowledge OS. It ingests sources (articles,
        PDFs, videos), compiles them into a structured wiki using AI, and lets
        you ask questions against your knowledge base.
      </p>
      <p className="mb-6 text-sm text-slate-500">
        The core loop: <strong>Ingest</strong> a source, <strong>compile</strong>{" "}
        it into a wiki article, then <strong>explore</strong> and{" "}
        <strong>ask</strong> questions.
      </p>
      <div className="flex items-center justify-center gap-3">
        <Button variant="ghost" onClick={onSkip}>
          Skip for now
        </Button>
        <Button onClick={onNext}>Get Started</Button>
      </div>
    </div>
  );
}

function ConfigureLLMStep({
  onNext,
  onSkip,
}: {
  onNext: () => void;
  onSkip: () => void;
}) {
  const [provider, setProvider] = useState("anthropic");
  const [apiKey, setApiKeyValue] = useState("");
  const [testState, setTestState] = useState<
    "idle" | "saving" | "testing" | "success" | "error"
  >("idle");
  const [errorMsg, setErrorMsg] = useState("");
  const queryClient = useQueryClient();

  const handleSaveAndTest = async () => {
    if (!apiKey.trim()) return;
    setTestState("saving");
    setErrorMsg("");
    try {
      await setApiKey(provider, apiKey);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setTestState("testing");
      const result = await testProvider(provider);
      if (result.status === "ok") {
        await setDefaultProvider(provider);
        queryClient.invalidateQueries({ queryKey: ["settings"] });
        setTestState("success");
      } else {
        setTestState("error");
        setErrorMsg(result.error ?? "Connection test failed");
      }
    } catch (err) {
      setTestState("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Failed to save key");
    }
  };

  return (
    <div>
      <h2 className="mb-3 text-lg font-bold text-slate-900">
        Configure your LLM provider
      </h2>
      <p className="mb-4 text-sm text-slate-500">
        WikiMind uses an LLM to compile sources into wiki articles. Enter an API
        key for your preferred provider.
      </p>

      <label className="mb-1 block text-sm font-medium text-slate-700">
        Provider
      </label>
      <select
        value={provider}
        onChange={(e) => {
          setProvider(e.target.value);
          setTestState("idle");
          setErrorMsg("");
        }}
        className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 focus:border-brand-500 focus:outline-none"
      >
        <option value="anthropic">Anthropic</option>
        <option value="openai">OpenAI</option>
        <option value="google">Google</option>
      </select>

      <label className="mb-1 block text-sm font-medium text-slate-700">
        API Key
      </label>
      <input
        type="password"
        value={apiKey}
        onChange={(e) => {
          setApiKeyValue(e.target.value);
          if (testState !== "idle") setTestState("idle");
        }}
        placeholder="Paste your API key"
        className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />

      {testState === "error" && (
        <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800">
          {errorMsg}
        </div>
      )}

      {testState === "success" && (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-800">
          Connection successful! Your provider is ready.
        </div>
      )}

      <div className="flex justify-between">
        <Button variant="ghost" onClick={onSkip}>
          Skip for now
        </Button>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            disabled={
              !apiKey.trim() ||
              testState === "saving" ||
              testState === "testing"
            }
            onClick={handleSaveAndTest}
          >
            {testState === "saving"
              ? "Saving..."
              : testState === "testing"
                ? "Testing..."
                : "Save & Test"}
          </Button>
          {testState === "success" && (
            <Button onClick={onNext}>Next</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function AddSourceStep({
  onNext,
  onSkip,
}: {
  onNext: () => void;
  onSkip: () => void;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const mutation = useMutation({
    mutationFn: (u: string) => ingestUrl(u),
    onSuccess: () => {
      setSubmitted(true);
      onNext();
    },
    onError: (err) => {
      setError(
        err instanceof ApiError ? err.message : "Failed to ingest URL",
      );
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setError("");
    mutation.mutate(url.trim());
  };

  return (
    <div>
      <h2 className="mb-3 text-lg font-bold text-slate-900">
        Add your first source
      </h2>
      <p className="mb-4 text-sm text-slate-500">
        Paste a URL and WikiMind will ingest and compile it into a wiki article.
      </p>

      <form onSubmit={handleSubmit}>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/article"
          className="mb-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          disabled={submitted || mutation.isPending}
        />

        <p className="mb-3 text-xs text-slate-400">Try one of these:</p>
        <div className="mb-4 flex flex-col gap-1">
          {EXAMPLE_URLS.map((example) => (
            <button
              key={example}
              type="button"
              className="truncate text-left text-xs text-brand-600 hover:underline"
              onClick={() => setUrl(example)}
              disabled={submitted || mutation.isPending}
            >
              {example}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-3 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800">
            {error}
          </div>
        )}

        <div className="flex justify-between">
          <Button variant="ghost" onClick={onSkip}>
            Skip for now
          </Button>
          <Button
            type="submit"
            disabled={!url.trim() || mutation.isPending || submitted}
          >
            {mutation.isPending ? "Ingesting..." : "Ingest & Compile"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function CompilingStep({
  onNext,
  onSkip,
}: {
  onNext: () => void;
  onSkip: () => void;
}) {
  const lastEvent = useWebSocketStore((s) => s.lastEvent);
  const sourceStatus = useWebSocketStore((s) => s.sourceStatus);

  // Watch for compilation.complete or compilation.failed
  const isComplete =
    lastEvent !== null &&
    (lastEvent as WSEvent).event === "compilation.complete";
  const isFailed =
    lastEvent !== null &&
    (lastEvent as WSEvent).event === "compilation.failed";

  const statusMessages = Object.values(sourceStatus);
  const latestMessage =
    statusMessages.length > 0 ? statusMessages[statusMessages.length - 1] : null;

  return (
    <div className="text-center">
      <h2 className="mb-3 text-lg font-bold text-slate-900">
        {isComplete
          ? "Compilation complete!"
          : isFailed
            ? "Compilation failed"
            : "Compiling your first article..."}
      </h2>

      {!isComplete && !isFailed && (
        <>
          <div className="mb-4 flex justify-center">
            <Spinner size={32} />
          </div>
          {latestMessage && (
            <p className="mb-4 text-sm text-slate-500">{latestMessage}</p>
          )}
          <p className="mb-4 text-xs text-slate-400">
            This usually takes 30-60 seconds depending on the source.
          </p>
          <Button variant="ghost" onClick={onSkip}>
            Skip for now
          </Button>
        </>
      )}

      {isComplete && (
        <p className="mb-4 text-sm text-slate-500">
          Your first wiki article has been created. Let&apos;s go explore it!
        </p>
      )}

      {isFailed && (
        <p className="mb-4 text-sm text-rose-600">
          Something went wrong during compilation. You can retry from the Inbox
          later.
        </p>
      )}

      {(isComplete || isFailed) && (
        <Button onClick={onNext}>
          {isComplete ? "See my article" : "Continue"}
        </Button>
      )}
    </div>
  );
}

function DoneStep({
  onComplete,
  onSkip,
}: {
  onComplete: () => void;
  onSkip: () => void;
}) {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: completeOnboarding,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["onboarding-status"] });
      onComplete();
    },
  });

  return (
    <div className="text-center">
      <h2 className="mb-3 text-xl font-bold text-slate-900">
        You&apos;re all set!
      </h2>
      <p className="mb-6 text-sm text-slate-500">
        Your wiki is ready. Keep adding sources from the Inbox, explore your
        knowledge graph, and ask questions against your wiki.
      </p>
      <div className="flex items-center justify-center gap-3">
        <Button variant="ghost" onClick={onSkip}>
          Skip for now
        </Button>
        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Finishing..." : "Go to Wiki Explorer"}
        </Button>
      </div>
    </div>
  );
}
