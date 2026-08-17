/**
 * IPC channel names, in one place.
 *
 * Kept free of any Electron import so the preload bundle, the main process and the tests can all
 * share them — a channel name duplicated as a string literal is a bug that only shows up at
 * runtime, in the one place nobody is watching.
 */

export const SERVICE_REQUEST_CHANNEL = 'spectrapaint:request';
export const BOOT_STATUS_CHANNEL = 'spectrapaint:boot-status';
export const BOOT_STATUS_GET_CHANNEL = 'spectrapaint:boot-status:get';
export const BOOT_STATUS_RETRY_CHANNEL = 'spectrapaint:boot-status:retry';
