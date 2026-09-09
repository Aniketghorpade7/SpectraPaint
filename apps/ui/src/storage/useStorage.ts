import { useCallback, useEffect, useState } from 'react';

interface BundleStorage {
  bundle_id: string;
  name: string;
  created_at: string;
  consultation_count: number;
  is_default: number;
  bytes: number;
}

interface DiskInfo {
  free_bytes: number;
  total_bytes: number;
  low: boolean;
  warning: string | null;
}

type StorageState = {
  bundles: BundleStorage[];
  disk: DiskInfo | null;
  loading: boolean;
  message: string | null;
};

export function useStorage() {
  const [state, setState] = useState<StorageState>({
    bundles: [],
    disk: null,
    loading: true,
    message: null,
  });

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, message: null }));
    try {
      const result = await window.spectrapaint.storage();
      if (!result.ok) {
        setState((s) => ({
          ...s,
          loading: false,
          message: 'Storage could not be loaded. Please try again.',
        }));
        return;
      }
      const body = result.body as { bundles: BundleStorage[]; disk: DiskInfo };
      setState({
        bundles: body.bundles ?? [],
        disk: body.disk ?? null,
        loading: false,
        message: null,
      });
    } catch {
      setState((s) => ({
        ...s,
        loading: false,
        message: 'Storage could not be loaded. Please try again.',
      }));
    }
  }, []);

  useEffect(() => {
    let abandoned = false;
    void (async () => {
      try {
        const result = await window.spectrapaint.storage();
        if (abandoned) return;
        if (!result.ok) {
          setState((s) => ({
            ...s,
            loading: false,
            message: 'Storage could not be loaded. Please try again.',
          }));
          return;
        }
        const body = result.body as { bundles: BundleStorage[]; disk: DiskInfo };
        setState({
          bundles: body.bundles ?? [],
          disk: body.disk ?? null,
          loading: false,
          message: null,
        });
      } catch {
        if (abandoned) return;
        setState((s) => ({
          ...s,
          loading: false,
          message: 'Storage could not be loaded. Please try again.',
        }));
      }
    })();
    return () => {
      abandoned = true;
    };
  }, []);

  const deleteBundle = useCallback(
    async (bundleId: string) => {
      const result = await window.spectrapaint.request({
        path: `/bundles/${bundleId}`,
        method: 'DELETE',
      });
      if (!result.ok) {
        const body = result.body as { code?: string };
        if (body?.code === 'default_bundle_protected') {
          setState((s) => ({ ...s, message: 'The default bundle cannot be deleted.' }));
        } else {
          setState((s) => ({
            ...s,
            message: 'The bundle could not be deleted. Please try again.',
          }));
        }
        return false;
      }
      await load();
      return true;
    },
    [load],
  );

  const deleteConsultation = useCallback(
    async (consultationId: string) => {
      const result = await window.spectrapaint.deleteConsultation(consultationId);
      if (!result.ok) {
        setState((s) => ({
          ...s,
          message: 'That consultation could not be deleted. Please try again.',
        }));
        return false;
      }
      await load();
      return true;
    },
    [load],
  );

  return { ...state, load, deleteBundle, deleteConsultation };
}

export type Storage = ReturnType<typeof useStorage>;
