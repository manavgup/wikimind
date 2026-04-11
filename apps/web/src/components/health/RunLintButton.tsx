import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { useRunLint } from "../../hooks/useLint";

export function RunLintButton() {
  const { mutate, isPending } = useRunLint();

  return (
    <Button
      variant="primary"
      size="sm"
      disabled={isPending}
      onClick={() => mutate()}
    >
      {isPending ? (
        <>
          <Spinner size={14} /> Running...
        </>
      ) : (
        "Run lint now"
      )}
    </Button>
  );
}
