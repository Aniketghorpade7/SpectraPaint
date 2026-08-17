/**
 * A line of plain-language progress.
 *
 * `aria-live` so the message is announced as it changes, since a Dealer watching a slow start has
 * nothing else to tell them the app is alive.
 */
export function ProgressMessage({ children }: { children: React.ReactNode }) {
  return (
    <p className="progress-message" aria-live="polite">
      {children}
    </p>
  );
}
