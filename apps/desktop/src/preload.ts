import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import type {
  BootStatus,
  CorrectionTool,
  CreateConsultationResult,
  ExportResult,
  MenuCommand,
  MenuState,
  ProgressStreamEvent,
  RenderResult,
  ServiceRequest,
  ServiceResponse,
  SpectraPaintBridge,
  StoredImageResult,
  TapPoint,
  WallsResult,
} from './bridge-types';
import {
  BOOT_STATUS_CHANNEL,
  BOOT_STATUS_GET_CHANNEL,
  BOOT_STATUS_RETRY_CHANNEL,
  CORRECTIONS_CHANNEL,
  CREATE_CONSULTATION_CHANNEL,
  DISK_CHANNEL,
  EXECUTION_PROFILE_GET_CHANNEL,
  EXECUTION_PROFILE_SET_CHANNEL,
  EXPORT_CHANNEL,
  MENU_COMMAND_CHANNEL,
  MENU_STATE_CHANNEL,
  PROGRESS_EVENT_CHANNEL,
  PROGRESS_STREAM_START_CHANNEL,
  PROGRESS_STREAM_STOP_CHANNEL,
  QUALITY_TIER_GET_CHANNEL,
  QUALITY_TIER_SET_CHANNEL,
  RENDER_CHANNEL,
  SERVICE_REQUEST_CHANNEL,
  STORAGE_CHANNEL,
  STORED_IMAGE_CHANNEL,
  WALLS_CHANNEL,
} from './channels';

/**
 * The only path between the renderer and everything else.
 *
 * `contextIsolation` is on and `nodeIntegration` is off, so this is the entire surface the React
 * app can see. Ten methods, deliberately: enough to call the contract, follow boot progress,
 * stream preparation progress, show which walls were found, correct them by tapping (ticket #10),
 * repaint one and read back a stored image (ticket #11), and nothing that hands out the secret,
 * the port, a filesystem handle or an arbitrary fetch.
 *
 * Note what is *not* here: no `getSecret()`, and no `baseUrl`. Exposing either would put the
 * secret one `console.log` away from a screenshot, and would break the moment a restart moves the
 * port.
 */

const bridge: SpectraPaintBridge = {
  request<T>(request: ServiceRequest): Promise<ServiceResponse<T>> {
    return ipcRenderer.invoke(SERVICE_REQUEST_CHANNEL, request) as Promise<ServiceResponse<T>>;
  },

  createConsultation(): Promise<CreateConsultationResult> {
    return ipcRenderer.invoke(CREATE_CONSULTATION_CHANNEL) as Promise<CreateConsultationResult>;
  },

  onProgress(sessionId: string, listener: (event: ProgressStreamEvent) => void): () => void {
    const handler = (
      _event: IpcRendererEvent,
      payload: { sessionId: string; event: ProgressStreamEvent },
    ) => {
      if (payload.sessionId === sessionId) listener(payload.event);
    };
    ipcRenderer.on(PROGRESS_EVENT_CHANNEL, handler);
    void ipcRenderer.invoke(PROGRESS_STREAM_START_CHANNEL, sessionId);
    return () => {
      ipcRenderer.off(PROGRESS_EVENT_CHANNEL, handler);
      void ipcRenderer.invoke(PROGRESS_STREAM_STOP_CHANNEL, sessionId);
    };
  },

  onMenuCommand(listener: (command: MenuCommand) => void): () => void {
    const handler = (_event: IpcRendererEvent, command: MenuCommand) => listener(command);
    ipcRenderer.on(MENU_COMMAND_CHANNEL, handler);
    return () => {
      ipcRenderer.off(MENU_COMMAND_CHANNEL, handler);
    };
  },

  setMenuState(state: MenuState): void {
    ipcRenderer.send(MENU_STATE_CHANNEL, state);
  },

  onBootStatus(listener: (status: BootStatus) => void): () => void {
    const handler = (_event: IpcRendererEvent, status: BootStatus) => listener(status);
    ipcRenderer.on(BOOT_STATUS_CHANNEL, handler);
    return () => {
      ipcRenderer.off(BOOT_STATUS_CHANNEL, handler);
    };
  },

  render(
    sessionId: string,
    shadeCodeOrAssignments: string | Record<string, string>,
    mode: 'realistic' | 'true_colour' = 'realistic',
  ): Promise<RenderResult> {
    return ipcRenderer.invoke(
      RENDER_CHANNEL,
      sessionId,
      shadeCodeOrAssignments,
      mode,
    ) as Promise<RenderResult>;
  },

  walls(sessionId: string): Promise<WallsResult> {
    return ipcRenderer.invoke(WALLS_CHANNEL, sessionId) as Promise<WallsResult>;
  },

  correctWalls(sessionId: string, tool: CorrectionTool, point: TapPoint): Promise<WallsResult> {
    return ipcRenderer.invoke(CORRECTIONS_CHANNEL, sessionId, tool, point) as Promise<WallsResult>;
  },

  bootStatus(): Promise<BootStatus> {
    return ipcRenderer.invoke(BOOT_STATUS_GET_CHANNEL) as Promise<BootStatus>;
  },

  retryBoot(): Promise<void> {
    return ipcRenderer.invoke(BOOT_STATUS_RETRY_CHANNEL) as Promise<void>;
  },

  storedImage(consultationId: string, target: 'photo' | string): Promise<StoredImageResult> {
    return ipcRenderer.invoke(
      STORED_IMAGE_CHANNEL,
      consultationId,
      target,
    ) as Promise<StoredImageResult>;
  },

  export(
    sessionId: string,
    shadeCodeOrAssignments: string | Record<string, string>,
    mode: 'realistic' | 'true_colour' = 'realistic',
  ): Promise<ExportResult> {
    return ipcRenderer.invoke(
      EXPORT_CHANNEL,
      sessionId,
      shadeCodeOrAssignments,
      mode,
    ) as Promise<ExportResult>;
  },

  storage() {
    return ipcRenderer.invoke(STORAGE_CHANNEL, { path: '/storage', method: 'GET' }) as Promise<
      ServiceResponse<{
        bundles: import('./bridge-types').BundleStorage[];
        disk: import('./bridge-types').DiskInfo;
      }>
    >;
  },

  deleteConsultation(consultationId: string) {
    return ipcRenderer.invoke(STORAGE_CHANNEL, {
      path: `/consultations/${consultationId}`,
      method: 'DELETE',
    }) as Promise<ServiceResponse>;
  },

  disk() {
    return ipcRenderer.invoke(DISK_CHANNEL) as Promise<import('./bridge-types').DiskProbe>;
  },

  // Execution profile and quality tier methods
  getExecutionProfile(): Promise<string> {
    return ipcRenderer.invoke(EXECUTION_PROFILE_GET_CHANNEL);
  },

  setExecutionProfile(profile: string): Promise<void> {
    return ipcRenderer.invoke(EXECUTION_PROFILE_SET_CHANNEL, profile);
  },

  getQualityTier(): Promise<string> {
    return ipcRenderer.invoke(QUALITY_TIER_GET_CHANNEL);
  },

  setQualityTier(tier: string): Promise<void> {
    return ipcRenderer.invoke(QUALITY_TIER_SET_CHANNEL, tier);
  },
};

contextBridge.exposeInMainWorld('spectrapaint', bridge);
