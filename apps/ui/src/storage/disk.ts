/**
 * Low-disk helpers used by App and the consultations flow (issue #13).
 *
 * The threshold mirrors the service's LOW_DISK_BYTES / LOW_DISK_RATIO so
 * the banner and the service agree on what "low" means. The service is
 * the authority (it holds the storage directory); the shell probe is the
 * fallback that keeps a warning visible even when the service is down.
 */

export interface DiskStatus {
  freeBytes: number;
  totalBytes: number;
  low: boolean;
  warning: string | null;
}

/** Plain-language warning, shown as-is — says what to do. */
export const DISK_WARNING_MESSAGE =
  'Your disk is getting full. Open Storage to delete old Bundles — otherwise new photos may fail to save.';
