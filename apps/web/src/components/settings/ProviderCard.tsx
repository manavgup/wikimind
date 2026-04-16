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
    if (testState.kind === "success") return `✓ ${testState.latency_ms}ms`;
    if (testState.kind === "error") return `✗ ${testState.message}`;
    return "Test";
  }

  return (
    <Card
      className={`p-4 ${isDefault ? "border-l-4 border-l-brand-300" : ""}`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-800 capitalize">{name}</span>
          {isDefault && <Badge tone="info">Default</Badge>}
        </div>
        <Badge tone={info.enabled ? "success" : "neutral"}>
          {info.enabled ? "Enabled" : "Disabled"}
        </Badge>
      </div>

      <p className="mb-3 text-sm text-slate-500">{info.model}</p>

      <div className="mb-3">
        {info.configured ? (
          <Badge tone="success">Configured</Badge>
        ) : (
          <Badge tone="neutral">Not configured</Badge>
        )}
      </div>

      <div className="flex gap-2">
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
