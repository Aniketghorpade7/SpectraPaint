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
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
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
/** A command the application menu sends into the renderer (issue #50). */
export type MenuCommand = 'undo' | 'redo';

/** What the renderer tells the menu about Undo/Redo availability, so the items enable honestly. */
export interface MenuState {
  canUndo: boolean;
  canRedo: boolean;
}
/**
 * One Wall Plane, in the form the renderer can draw: its id, how much of the photo it covers, the
 * box it occupies, and its Alpha Matte as a PNG data URL.
 *
 * The matte arrives as a data URL rather than as pixel data because the renderer's job is to draw
 * it, and a browser decodes a PNG far faster than JavaScript can unpack an array — the same
 * reasoning that makes the repaint a data URL.
 */
export interface WallPlaneOverlay {
  planeId: string;
  /** Paintable Plane surface — wall or ceiling (CONTEXT.md). */
  surface: 'wall' | 'ceiling';
  coverage: number;
  photoWidth: number;
  photoHeight: number;
  bounds: { left: number; top: number; right: number; bottom: number } | null;
  matteDataUrl: string;
}

/**
 * The walls found in a photo, or a failure carrying the service's own message — "no wall could be
 * found in that photo" being the case worth passing through verbatim.
 *
 * `note` is the service's plain-language explanation for an empty `planes` — automatic detection
 * found nothing at all (ticket #10) — and `null` the rest of the time; never shown as an error,
 * since the photo is still reachable through the correction surface's Add tool. `photoWidth`/
 * `photoHeight` are top-level rather than read off `planes[0]`, because they must still be known
 * when `planes` is empty: turning a tap into a point in the photo's own pixel space is exactly
 * what the Add tool needs to do in that case.
 *
 * `qualityNote` (issue #15) is unrelated to `note`: it is the service's plain-language warning
 * about the photo itself — dark, blurred, heavily clipped — never a reason preparation refuses it,
 * and never cleared by a correction, which only ever changes the planes.
 */
export type WallsResult =
  | {
      status: 'ready';
      planes: WallPlaneOverlay[];
      note: string | null;
      qualityNote: string | null;
      photoWidth: number;
      photoHeight: number;
    }
  | { status: 'failed'; code: string; message: string };

/** Which correction tool made the tap — Add, Split, Merge, or Add Ceiling (ticket #39). */
export type CorrectionTool = 'add' | 'add-ceiling' | 'split' | 'merge';

/** Where the Dealer tapped, in the prepared photo's own pixel space — the same space
 * `WallsResult`'s `photoWidth`/`photoHeight` describe. */
export interface TapPoint {
  x: number;
  y: number;
}

export type RenderResult =
  | { status: 'ready'; imageDataUrl: string; executionProfile: string }
  | { status: 'failed'; code: string; message: string };

/**
 * One stored image from the library (issue #11): a Consultation's photo as prepared, or one of its
 * saved renders — always exactly the bytes that were written, as a data URL the renderer can draw.
 */
export type StoredImageResult =
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
   * Subscribe to application-menu commands (issue #50). A menu click or its accelerator lands here;
   * the renderer decides whether the command is paint — undo/redo a Shade snapshot — or text
   * editing in the focused field, which the browser already handles. Returns an unsubscribe
   * function, the same shape as `onBootStatus`.
   */
  onMenuCommand(listener: (command: MenuCommand) => void): () => void;

  /**
   * Report whether Undo/Redo have anything to act on, so the menu items enable and disable
   * with the Consultation's history rather than sitting grey forever.
   */
  setMenuState(state: MenuState): void;

  /**
   * Subscribe to boot progress. Returns an unsubscribe function.
   */
  onBootStatus(listener: (status: BootStatus) => void): () => void;

  /**
   * Repaint the Wall Planes and return the repainted photo as a data URL.
   *
   * Main builds the request: it names the Wall Planes and holds the secret,
   * so the renderer asks for a Shade (or a Shade per plane for an Accent
   * Wall) and gets back an image — it never touches the wire shape or a file.
   * A refusal comes back as a `failed` result whose message is the service's
   * own, safe to show as-is.
   *
   * A string Shade Code paints every plane the photo has; a map paints each
   * plane in its own Shade. `mode` selects realistic (default) or true_colour.
   */
  render(
    sessionId: string,
    shadeCodeOrAssignments: string | Record<string, string>,
    mode?: 'realistic' | 'true_colour',
  ): Promise<RenderResult>;

  /**
   * The Wall Planes found in this photo, each with its Alpha Matte as a data URL to draw.
   *
   * Resolves once preparation has finished, because the service waits rather than answering "not
   * ready" — so the renderer asks once and does not poll.
   */
  walls(sessionId: string): Promise<WallsResult>;

  /**
   * Correct the detected Wall Planes by tapping — Add, Split or Merge (ticket #10). `point` is
   * the tapped pixel in the photo's own space (`WallsResult.photoWidth`/`photoHeight`); main
   * resolves which plane(s) it affects, so the renderer never names a plane id for this. Returns
   * the updated plane list in the exact shape `walls()` does, so a correction's result is handled
   * exactly like a fresh load. A tap that does not satisfy its tool's precondition — already
   * covered, not on a plane, not near a seam — comes back as a `failed` result carrying the
   * service's own message, safe to show as-is; the existing planes are untouched.
   */
  correctWalls(sessionId: string, tool: CorrectionTool, point: TapPoint): Promise<WallsResult>;

  /**
   * The status right now. Read on mount, because the service can become ready before the boot
   * screen has finished loading and subscribed.
   */
  bootStatus(): Promise<BootStatus>;

  /** Try starting the service again after a failure, so an error is never a dead end. */
  retryBoot(): Promise<void>;

  /**
   * A stored image from the library (issue #11): `'photo'` for the Consultation's photo as
   * preparation left it, or a render id for one of its saved renders. Main fetches the PNG with
   * the secret in its header — the same rule as every image in this app — and returns a data URL.
   */
  storedImage(consultationId: string, target: 'photo' | string): Promise<StoredImageResult>;

  /**
   * Export the current repaint at full resolution as a JPEG and hand it to
   * the OS share sheet (issue #12). The stored PNG archive is never handed
   * out directly; a fresh JPEG is rendered and saved via the native dialog.
   * The filename carries the Shade Code and name.
   */
  export(
    sessionId: string,
    shadeCodeOrAssignments: string | Record<string, string>,
    mode?: 'realistic' | 'true_colour',
  ): Promise<ExportResult>;

  /**
   * Bundles by bytes + disk free (issue #13).
   */
  storage(): Promise<ServiceResponse<{ bundles: BundleStorage[]; disk: DiskInfo }>>;

  /** Delete a Consultation and its files (issue #13). */
  deleteConsultation(consultationId: string): Promise<ServiceResponse>;

  /** The shell's own low-disk probe (issue #13) — works even when the service is down. */
  disk(): Promise<DiskProbe>;

  // Execution profile and quality tier methods
  /** Get the current execution profile (e.g., "gpu-better", "cpu-faster"). */
  getExecutionProfile(): Promise<string>;

  /** Set the execution profile (format: "hardware-quality", e.g., "gpu-better"). */
  setExecutionProfile(profile: string): Promise<void>;

  /** Get the current quality tier ("faster" or "better"). */
  getQualityTier(): Promise<string>;

  /** Set the quality tier ("faster" or "better"). */
  setQualityTier(tier: string): Promise<void>;
}

export type ExportResult =
  | { status: 'ready'; filePath: string; filename: string; executionProfile: string }
  | { status: 'cancelled' }
  | { status: 'failed'; code: string; message: string };

export interface BundleStorage {
  bundle_id: string;
  name: string;
  created_at: string;
  consultation_count: number;
  is_default: number;
  bytes: number;
}

export interface DiskInfo {
  free_bytes: number;
  total_bytes: number;
  low: boolean;
  warning: string | null;
}

export interface DiskProbe {
  freeBytes: number;
  totalBytes: number;
  low: boolean;
}
