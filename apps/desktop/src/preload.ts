import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron';

import type {
  BootStatus,
  CreateConsultationResult,
  ProgressStreamEvent,
  RenderResult,
  ServiceRequest,
  ServiceResponse,
  SpectraPaintBridge,
  WallsResult,
} from './bridge-types';
import {
  BOOT_STATUS_CHANNEL,
  BOOT_STATUS_GET_CHANNEL,
  BOOT_STATUS_RETRY_CHANNEL,
  CREATE_CONSULTATION_CHANNEL,
  PROGRESS_EVENT_CHANNEL,
  PROGRESS_STREAM_START_CHANNEL,
  PROGRESS_STREAM_STOP_CHANNEL,
  RENDER_CHANNEL,
  SERVICE_REQUEST_CHANNEL,
  WALLS_CHANNEL,
} from './channels';

/**
 * The only path between the renderer and everything else.
 *
 * `contextIsolation` is on and `nodeIntegration` is off, so this is the entire surface the React
 * app can see. Eight methods, deliberately: enough to call the contract, follow boot progress,
 * stream preparation progress, show which walls were found and repaint one, and nothing that hands
 * out the secret, the port, a filesystem handle or an arbitrary fetch.
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

  onBootStatus(listener: (status: BootStatus) => void): () => void {
    const handler = (_event: IpcRendererEvent, status: BootStatus) => listener(status);
    ipcRenderer.on(BOOT_STATUS_CHANNEL, handler);
    return () => {
      ipcRenderer.off(BOOT_STATUS_CHANNEL, handler);
    };
  },

  render(sessionId: string, shadeCode: string): Promise<RenderResult> {
    return ipcRenderer.invoke(RENDER_CHANNEL, sessionId, shadeCode) as Promise<RenderResult>;
  },

  walls(sessionId: string): Promise<WallsResult> {
    return ipcRenderer.invoke(WALLS_CHANNEL, sessionId) as Promise<WallsResult>;
  },

  bootStatus(): Promise<BootStatus> {
    return ipcRenderer.invoke(BOOT_STATUS_GET_CHANNEL) as Promise<BootStatus>;
  },

  retryBoot(): Promise<void> {
    return ipcRenderer.invoke(BOOT_STATUS_RETRY_CHANNEL) as Promise<void>;
  },
};

contextBridge.exposeInMainWorld('spectrapaint', bridge);
