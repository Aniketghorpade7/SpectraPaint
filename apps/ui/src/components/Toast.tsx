import { Button } from './Button';

/**
 * A transient notice beside an action just taken — "Bundle deleted", with the Undo that makes it
 * safe to have acted without a confirmation step (docs/ui-guidelines.md: act, then let it be
 * undone, since a confirmation is a tap the interaction budget cannot afford).
 *
 * No auto-dismiss timer: the Dealer is at a counter with a Customer waiting, and a toast that
 * vanishes on its own could take the one way to undo a mistake with it. It stays on screen until
 * the Dealer acts on it, or the caller clears or replaces it.
 */
export function Toast({
  message,
  actionLabel,
  onAction,
}: {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="toast" role="status">
      <span className="toast__message">{message}</span>
      {actionLabel && onAction ? (
        <Button className="toast__action" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
