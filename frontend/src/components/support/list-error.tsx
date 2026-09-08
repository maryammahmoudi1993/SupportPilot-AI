import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

/**
 * A network/server failure — explicitly distinct from an empty result set
 * (see frontend/README.md, "List states"). Never collapsed into "nothing
 * here": the message and the Retry affordance are what tell an operator
 * their request failed rather than genuinely returned zero rows.
 */
export function ListError({
  message,
  onRetry,
  isRetrying = false,
}: {
  message: string;
  onRetry: () => void;
  isRetrying?: boolean;
}) {
  return (
    <Alert variant="danger" title="Something went wrong">
      <div className="flex flex-col items-start gap-3">
        <p>{message}</p>
        <Button variant="secondary" size="sm" onClick={onRetry} isLoading={isRetrying}>
          Retry
        </Button>
      </div>
    </Alert>
  );
}
