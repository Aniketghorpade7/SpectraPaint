/**
 * The shape of `window.spectrapaint`.
 *
 * Types only — no runtime code, so both the preload script and the React renderer can import it
 * without either package depending on the other's build output.
 */

/** What the Dealer is told is happening, while it happens. */
export type BootPhase = 'starting' | 'ready' | 'restarting' | 'failed';

export interface BootStatus {
  phase: BootPhase;
  /** Plain language, safe to show as-is. Present only when the phase is 'failed'. */
  message?: string;
}

export interface ServiceRequest {
  path: string;
  method?: 'GET' | 'POST' | 'DELETE';
  body?: unknown;
}

export interface ServiceResponse<T = unknown> {
  status: number;
  ok: boolean;
  body: T;
}

export interface SpectraPaintBridge {
  /**
   * Call the inference service. The secret and the current base URL are added in the main
   * process; a caller supplies only a path within the contract.
   */
  request<T = unknown>(request: ServiceRequest): Promise<ServiceResponse<T>>;

  /** Subscribe to boot progress. Returns an unsubscribe function. */
  onBootStatus(listener: (status: BootStatus) => void): () => void;

  /**
   * The status right now. Read on mount, because the service can become ready before the boot
   * screen has finished loading and subscribed.
   */
  bootStatus(): Promise<BootStatus>;

  /** Try starting the service again after a failure, so an error is never a dead end. */
  retryBoot(): Promise<void>;
}
