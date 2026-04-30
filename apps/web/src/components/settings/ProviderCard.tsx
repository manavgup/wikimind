import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import type { ProviderInfo } from "../../api/settings";
import { testProvider, setDefaultProvider } from "../../api/settings";

interface ProviderCardProps {
  name: string;
  info: ProviderInfo;
  isDefault: boolean;
  onSetKey: (provider: string) => void;
}

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "success"; latency_ms: number }
  | { kind: "error"; message: string };

const NO_KEY_PROVIDERS = new Set(["ollama", "mock"]);

function formatProviderName(name: string): string {
  if (name === "openai_compatible") return "OpenAI-compatible";
  if (name === "openai") return "OpenAI";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function HealthDot({ state }: { state: TestState; enabled: boolean }) {
  if (state.kind === "testing") {
    return (
      <span className="relative flex h-3 w-3">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500" />
      </span>
    );
  }
  if (state.kind === "success") {
    return <span className="inline-flex h-3 w-3 rounded-full bg-emerald-500" title="Healthy" />;
  }
  if (state.kind === "error") {
    return <span className="inline-flex h-3 w-3 rounded-full bg-red-500" title={state.message} />;
  }
  return <span className="inline-flex h-3 w-3 rounded-full bg-slate-300" title="Not tested" />;
}

export function ProviderCard({ name, info, isDefault, onSetKey }: ProviderCardProps) {
  const [testState, setTestState] = useState<TestState>({ kind: "idle" });
  const queryClient = useQueryClient();

  const makeDefault = useMutation({
    mutationFn: () => setDefaultProvider(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const testMutation = useMutation({
    mutationFn: () => testProvider(name),
    onMutate: () => setTestState({ kind: "testing" }),
    onSuccess: (result) => {
      if (result.status === "ok") {
        setTestState({ kind: "success", latency_ms: result.latency_ms ?? 0 });
      } else {
        setTestState({ kind: "error", message: result.error ?? "Unknown error" });
      }
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : "Test failed";
      setTestState({ kind: "error", message });
    },
  });

  const needsKey = !NO_KEY_PROVIDERS.has(name.toLowerCase());

  function getTestLabel(): string {
    if (testState.kind === "testing") return "Testing...";
    if (testState.kind === "success") return `${testState.latency_ms}ms`;
    if (testState.kind === "error") return "Failed";
    return "Test";
  }

  return (
    <Card
      className={`relative overflow-hidden p-4 ${isDefault ? "ring-2 ring-brand-300" : ""}`}
    >
      {isDefault && (
        <div className="absolute right-0 top-0 rounded-bl bg-brand-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-white">
          Default
        </div>
      )}

      <div className="mb-3 flex items-center gap-2.5">
        <HealthDot state={testState} enabled={info.enabled} />
        <span className="text-base font-semibold text-slate-800">{formatProviderName(name)}</span>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-600">
          {info.model}
        </span>
        <Badge tone={info.enabled ? "success" : "neutral"}>
          {info.enabled ? "Enabled" : "Disabled"}
        </Badge>
      </div>

      <div className="mb-3 flex items-center gap-2">
        {info.configured ? (
          <span className="flex items-center gap-1 text-xs text-emerald-600">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            </svg>
            API key set
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-slate-400">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
            </svg>
            Not configured
          </span>
        )}
        {testState.kind === "success" && (
          <span className="text-xs text-emerald-600">{testState.latency_ms}ms</span>
        )}
        {testState.kind === "error" && (
          <span className="truncate text-xs text-red-500" title={testState.message}>
            {testState.message}
          </span>
        )}
      </div>

      <div className="flex gap-2 border-t border-slate-100 pt-3">
        {needsKey && (
          <Button variant="ghost" size="sm" onClick={() => onSetKey(name)}>
            Set Key
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          disabled={testState.kind === "testing"}
          onClick={() => testMutation.mutate()}
        >
          {getTestLabel()}
        </Button>
        {info.enabled && info.configured && !isDefault && (
          <Button
            variant="ghost"
            size="sm"
            disabled={makeDefault.isPending}
            onClick={() => makeDefault.mutate()}
          >
            {makeDefault.isPending ? "Setting..." : "Make Default"}
          </Button>
        )}
      </div>
    </Card>
  );
}
