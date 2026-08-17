import { Button } from './Button';

/**
 * Never a dead end (docs/ui-guidelines.md): an error state always offers an action. The action is
 * required, not optional, so a caller cannot render a message the Dealer can only stare at.
 */
export function ErrorState({
  message,
  actionLabel,
  onAction,
}: {
  message: string;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <p className="error-state__message">{message}</p>
      <Button onClick={onAction}>{actionLabel}</Button>
    </div>
  );
}
