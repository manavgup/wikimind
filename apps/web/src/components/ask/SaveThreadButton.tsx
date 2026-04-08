interface Props {
  isFiledBack: boolean;
  isSaving: boolean;
  onClick: () => void;
}

export function SaveThreadButton({ isFiledBack, isSaving, onClick }: Props) {
  const label = isSaving
    ? isFiledBack
      ? "Updating…"
      : "Saving…"
    : isFiledBack
      ? "Update wiki article"
      : "Save thread to wiki";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isSaving}
      className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
    >
      {label}
    </button>
  );
}
