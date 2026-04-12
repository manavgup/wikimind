import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { useRunLint } from "../../hooks/useLint";

export function RunLintButton() {
  const { mutate, isPending, isPolling } = useRunLint();
  const busy = isPending || isPolling;

  return (
    <Button
      variant="primary"
      size="sm"
      disabled={busy}
      onClick={() => mutate()}
    >
      {busy ? (
        <>
          <Spinner size={14} />{" "}
          {isPolling ? "Analyzing articles..." : "Starting..."}
        </>
      ) : (
        "Run lint now"
      )}
    </Button>
  );
}
