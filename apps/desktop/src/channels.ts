/**
 * IPC channel names, in one place.
 *
 * Kept free of any Electron import so the preload bundle, the main process and the tests can all
 * share them — a channel name duplicated as a string literal is a bug that only shows up at
 * runtime, in the one place nobody is watching.
 */

export const SERVICE_REQUEST_CHANNEL = 'spectrapaint:request';
export const CREATE_CONSULTATION_CHANNEL = 'spectrapaint:create-consultation';
export const BOOT_STATUS_CHANNEL = 'spectrapaint:boot-status';
export const BOOT_STATUS_GET_CHANNEL = 'spectrapaint:boot-status:get';
export const BOOT_STATUS_RETRY_CHANNEL = 'spectrapaint:boot-status:retry';
export const PROGRESS_EVENT_CHANNEL = 'spectrapaint:progress';
export const PROGRESS_STREAM_START_CHANNEL = 'spectrapaint:progress:start';
export const PROGRESS_STREAM_STOP_CHANNEL = 'spectrapaint:progress:stop';
export const RENDER_CHANNEL = 'spectrapaint:render';
export const WALLS_CHANNEL = 'spectrapaint:walls';
export const STORED_IMAGE_CHANNEL = 'spectrapaint:stored-image';
