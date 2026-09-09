import { Button } from './Button';

/**
 * Nothing to show yet — no bundles, no search results, nothing tried in this consultation.
 *
 * Distinct from ErrorState: nothing went wrong, so this is not `role="alert"`, and the action is
 * optional — some empty states have nowhere better to send the Dealer than back to what they were
 * already doing (docs/ui-guidelines.md: every surface needs its loading, empty and error state).
 */
export function EmptyState({
  message,
  actionLabel,
  onAction,
}: {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state">
      <p className="empty-state__message">{message}</p>
      {actionLabel && onAction ? <Button onClick={onAction}>{actionLabel}</Button> : null}
    </div>
  );
}
