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

/**
 * One frame of a session's preparation stream, delivered by main as it is parsed.
 *
 * `progress` events carry a plain-language message the UI may show as-is. Exactly one terminal event
 * — `done` or `failed` — arrives last, after which the stream closes.
 */
export type ProgressStreamPhase = 'progress' | 'done' | 'failed';

export interface ProgressStreamEvent {
  phase: ProgressStreamPhase;
  message?: string;
}

/**
 * What a new-Consultation attempt comes back as. The Dealer either changed their mind, or has a
 * photo on screen, or was refused with a message the UI may show as-is. Cancellation is a result,
 * not an error — walking away is not a failure.
 */
export type CreateConsultationResult =
  | { status: 'cancelled' }
  | { status: 'ready'; sessionId: string; imageDataUrl: string }
  | { status: 'failed'; code: string; message: string };

/**
 * What a repaint request comes back as. A refusal — service down, unknown Shade Code, an assignment
 * naming a wall the photo does not have — is a result carrying the service's own message, so the UI
 * can show it as-is rather than inventing one.
 */
export type RenderResult =
  { status: 'ready'; imageDataUrl: string } | { status: 'failed'; code: string; message: string };

export interface SpectraPaintBridge {
  /**
   * Call the inference service. The secret and the current base URL are added in the main
   * process; a caller supplies only a path within the contract.
   */
  request<T = unknown>(request: ServiceRequest): Promise<ServiceResponse<T>>;

  /**
   * Open the native photo dialog, upload the chosen file to create a new Consultation, and return
   * the session id plus the photo for display. All filesystem and secret handling stays in main.
   */
  createConsultation(): Promise<CreateConsultationResult>;

  /**
   * Subscribe to a session's preparation progress. Main opens a fetch-based stream to the service
   * with the secret in a header — never a query string, which is exactly why the browser's
   * `EventSource` (which cannot set headers) is not used. The listener hears `progress` events,
   * then exactly one terminal `done` or `failed` event. Returns an unsubscribe function.
   */
  onProgress(sessionId: string, listener: (event: ProgressStreamEvent) => void): () => void;

  /**
   * Subscribe to boot progress. Returns an unsubscribe function.
   */
  onBootStatus(listener: (status: BootStatus) => void): () => void;

  /**
   * Repaint the Wall Plane in a Shade Code and return the repainted photo as a data URL.
   *
   * Main builds the request: it names the Wall Plane and holds the secret, so the renderer asks for
   * a Shade and gets back an image — it never touches the wire shape or a file. A refusal comes back
   * as a `failed` result whose message is the service's own, safe to show as-is.
   */
  render(sessionId: string, shadeCode: string): Promise<RenderResult>;

  /**
   * The status right now. Read on mount, because the service can become ready before the boot
   * screen has finished loading and subscribed.
   */
  bootStatus(): Promise<BootStatus>;

  /** Try starting the service again after a failure, so an error is never a dead end. */
  retryBoot(): Promise<void>;
}
