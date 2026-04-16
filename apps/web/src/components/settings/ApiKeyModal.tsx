import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "../shared/Button";
import { setApiKey } from "../../api/settings";

interface ApiKeyModalProps {
  provider: string;
  onClose: () => void;
}

export function ApiKeyModal({ provider, onClose }: ApiKeyModalProps) {
  const [value, setValue] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => setApiKey(provider, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      onClose();
    },
  });

  const displayName = provider.charAt(0).toUpperCase() + provider.slice(1);

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

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={value.trim() === "" || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
