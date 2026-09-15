import { app } from 'electron';
import path from 'node:path';
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

/**
 * The execution profile (issue #14): which hardware the service runs on, and which quality tier
 * the Dealer chose in Settings.
 *
 * A module of its own rather than part of main: the render and export bridges stamp the profile
 * on every result, and a bridge test that imported main would otherwise pull in the window, the
 * boot-status hub and the sidecar supervisor just to read a string — and on a dev machine with a
 * synced venv, start a real service process. Here the bridge's import graph reaches node modules
 * and nothing else.
 */

const QUALITY_TIERS = ['faster', 'better'] as const;
const SETTINGS_FILE = 'settings.json';

/** Auto-detected once, at boot: a machine's hardware does not change while the app is open. */
function detectDefaultHardwareProfile(): string {
  try {
    // Try to run nvidia-smi and see if it succeeds
    execFileSync('nvidia-smi', [], { stdio: 'ignore' });
    return 'gpu';
  } catch {
    return 'cpu';
  }
}

let hardwareProfile: string = detectDefaultHardwareProfile();
let qualityTier: string = 'better';

let onProfileChange: (() => void) | null = null;

/** The composite the Dealer-facing UI reads, e.g. ``cpu-better``. */
export function getExecutionProfile(): string {
  return `${hardwareProfile}-${qualityTier}`;
}

export function getQualityTier(): string {
  return qualityTier;
}

export function getHardwareProfile(): string {
  return hardwareProfile;
}

/** main's one hook into a profile change: the sidecar must restart to pick up new settings. */
export function setOnProfileChange(handler: () => void): void {
  onProfileChange = handler;
}

export function setQualityTier(tier: string): void {
  // Only the two tiers the Catalogue sells are accepted: a malformed IPC call must not write a
  // value the restore path would then have to distrust.
  if (!(QUALITY_TIERS as readonly string[]).includes(tier)) return;
  if (qualityTier === tier) return;
  qualityTier = tier;
  persistQualityTier();
  onProfileChange?.();
}

export function setHardwareProfile(profile: string): void {
  if (hardwareProfile === profile) return;
  hardwareProfile = profile;
  onProfileChange?.();
}

// The Dealer's quality-tier choice survives restarts (issue #14 AC3): a tiny JSON file in the
// per-user application data directory — the one place the shell already owns on every platform.
// Only the tier persists; the hardware profile is re-detected at every boot (AC1), so a Dealer
// who moves machines does not drag a GPU choice into a CPU-only one.

function settingsPath(): string {
  return path.join(app.getPath('userData'), SETTINGS_FILE);
}

export function restoreQualityTier(): void {
  try {
    const saved = JSON.parse(fs.readFileSync(settingsPath(), 'utf8')) as { qualityTier?: string };
    if (saved.qualityTier && (QUALITY_TIERS as readonly string[]).includes(saved.qualityTier)) {
      qualityTier = saved.qualityTier;
    }
  } catch {
    // First run, or a file the machine mangled: the default tier is the right answer, and a
    // boot that refuses to start over its own settings file is worse than a silent reset.
  }
}

function persistQualityTier(): void {
  try {
    fs.mkdirSync(app.getPath('userData'), { recursive: true });
    fs.writeFileSync(settingsPath(), JSON.stringify({ qualityTier }));
  } catch (error) {
    // A write that fails (full disk, permissions) must not fail the tier change: the choice is
    // in effect for this session either way, and quiet recovery without a log hides the fault
    // (docs/conventions.md §5).
    console.error('[settings] failed to persist the quality tier:', error);
  }
}
