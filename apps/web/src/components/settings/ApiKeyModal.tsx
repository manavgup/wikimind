import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "../shared/Button";
import { setApiKey, updateSettings } from "../../api/settings";
import type { ProviderInfo } from "../../api/settings";

interface ApiKeyModalProps {
  provider: string;
  providerInfo?: ProviderInfo;
  onClose: () => void;
}

export function ApiKeyModal({ provider, providerInfo, onClose }: ApiKeyModalProps) {
  const [value, setValue] = useState("");
  const [baseUrl, setBaseUrl] = useState(providerInfo?.base_url ?? "");
  const [model, setModel] = useState(providerInfo?.model ?? "");
  const queryClient = useQueryClient();

  const isOpenAICompatible = provider === "openai_compatible";
  const trimmedBaseUrl = baseUrl.trim();
  const trimmedModel = model.trim();
  const trimmedKey = value.trim();
  const settingsChanged =
    isOpenAICompatible &&
    (trimmedBaseUrl !== (providerInfo?.base_url ?? "") || trimmedModel !== (providerInfo?.model ?? ""));

  const mutation = useMutation({
    mutationFn: async () => {
      if (isOpenAICompatible) {
        const settingsUpdate: {
          openai_compatible_base_url?: string;
          openai_compatible_model?: string;
        } = {};

        if (trimmedBaseUrl !== (providerInfo?.base_url ?? "")) {
          settingsUpdate.openai_compatible_base_url = trimmedBaseUrl;
        }
        if (trimmedModel !== (providerInfo?.model ?? "")) {
          settingsUpdate.openai_compatible_model = trimmedModel;
        }
        if (Object.keys(settingsUpdate).length > 0) {
          await updateSettings(settingsUpdate);
        }
      }
      if (trimmedKey) {
        await setApiKey(provider, trimmedKey);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
  });
  const canSave =
    !mutation.isPending &&
    (isOpenAICompatible
      ? Boolean(trimmedBaseUrl && trimmedModel && (trimmedKey || (providerInfo?.configured && settingsChanged)))
      : Boolean(trimmedKey));

  const displayName =
    provider === "openai_compatible" ? "OpenAI-compatible" : provider.charAt(0).toUpperCase() + provider.slice(1);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-slate-800">
          Set API Key — {displayName}
        </h2>

        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Paste your API key here"
          className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />

        {isOpenAICompatible && (
          <div className="mb-4 rounded-md border border-slate-200 bg-slate-50 p-3">
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Base URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://openrouter.ai/api/v1"
              className="mb-3 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <label className="mb-1 block text-sm font-medium text-slate-700">
              Model
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="openai/gpt-4o-mini"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!canSave}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
