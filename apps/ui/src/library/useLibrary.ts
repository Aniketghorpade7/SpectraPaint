import { useCallback, useEffect, useState } from 'react';

import type { BundleSummary, ConsultationSummary, RenderRecord } from './types';
import { shadesOf } from './types';

/**
 * The Dealer's library, over the generic request bridge (issue #11).
 *
 * Every call goes through `window.spectrapaint.request`, which adds the secret in main — the
 * renderer never holds it. Images are the exception: they arrive as data URLs through
 * `storedImage`, because the request bridge reads JSON only.
 *
 * Never dead-end (docs/ui-guidelines.md): a failed load leaves a message with a way to retry,
 * and every action that can fail reports itself rather than vanishing.
 */

export interface ReopenedConsultation {
  consultationId: string;
  sessionId: string;
  imageDataUrl: string;
}

export function useLibrary() {
  const [bundles, setBundles] = useState<BundleSummary[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const [consultations, setConsultations] = useState<ConsultationSummary[] | null>(null);
  const [openBundleId, setOpenBundleId] = useState<string | null>(null);

  const [renders, setRenders] = useState<RenderRecord[] | null>(null);
  const [photoDataUrl, setPhotoDataUrl] = useState<string | null>(null);
  const [openConsultationId, setOpenConsultationId] = useState<string | null>(null);
  const [reopening, setReopening] = useState(false);

  const request = useCallback(
    async (path: string, method?: 'POST' | 'PATCH' | 'DELETE', body?: unknown) =>
      window.spectrapaint.request({
        path,
        ...(method ? { method } : {}),
        ...(body !== undefined ? { body } : {}),
      }),
    [],
  );

  const loadBundles = useCallback(async () => {
    setMessage(null);
    const response = await request('/bundles');
    if (!response.ok) {
      setMessage('Your saved consultations could not be loaded. Please try again.');
      return;
    }
    setBundles((response.body as { bundles: BundleSummary[] }).bundles ?? []);
  }, [request]);

  // Loading the library happens once, on mount. The work sits inside the effect rather than in a
  // callback it calls, so the first thing that happens is the await — the same shape
  // useCatalogue uses, and for the same reason.
  useEffect(() => {
    let abandoned = false;

    void (async () => {
      const response = await request('/bundles');
      if (abandoned) return;
      if (!response.ok) {
        setMessage('Your saved consultations could not be loaded. Please try again.');
        return;
      }
      setBundles((response.body as { bundles: BundleSummary[] }).bundles ?? []);
    })();

    return () => {
      abandoned = true;
    };
  }, [request]);

  const openBundle = useCallback(
    async (bundleId: string) => {
      setMessage(null);
      setOpenBundleId(bundleId);
      setConsultations(null);
      const response = await request(`/bundles/${bundleId}/consultations`);
      if (!response.ok) {
        setMessage('The consultations in this bundle could not be loaded. Please try again.');
        return;
      }
      setConsultations(
        (response.body as { consultations: ConsultationSummary[] }).consultations ?? [],
      );
    },
    [request],
  );

  const backToBundles = useCallback(() => {
    setOpenBundleId(null);
    setConsultations(null);
    void loadBundles();
  }, [loadBundles]);

  const openConsultation = useCallback(
    async (consultationId: string) => {
      setMessage(null);
      setOpenConsultationId(consultationId);
      setRenders(null);
      setPhotoDataUrl(null);

      const history = await request(`/consultations/${consultationId}/renders`);
      setRenders(history.ok ? ((history.body as { renders: RenderRecord[] }).renders ?? []) : []);

      const image = await window.spectrapaint.storedImage(consultationId, 'photo');
      setPhotoDataUrl(image.status === 'ready' ? image.imageDataUrl : null);
    },
    [request],
  );

  const backToBundle = useCallback(() => {
    setOpenConsultationId(null);
    setRenders(null);
    setPhotoDataUrl(null);
  }, []);

  const createBundle = useCallback(
    async (name: string) => {
      setMessage(null);
      const response = await request('/bundles', 'POST', { name });
      if (!response.ok) {
        setMessage('The bundle could not be created. Please try again.');
        return false;
      }
      await loadBundles();
      return true;
    },
    [request, loadBundles],
  );

  const renameBundle = useCallback(
    async (bundleId: string, name: string) => {
      const response = await request(`/bundles/${bundleId}`, 'PATCH', { name });
      if (!response.ok) {
        setMessage('The bundle could not be renamed. Please try again.');
        return;
      }
      await loadBundles();
    },
    [request, loadBundles],
  );

  const deleteBundle = useCallback(
    async (bundleId: string) => {
      // Deleting a bundle moves its consultations to the default bundle; nothing is destroyed.
      const response = await request(`/bundles/${bundleId}`, 'DELETE');
      if (!response.ok) {
        setMessage('The bundle could not be deleted. Please try again.');
        return;
      }
      if (openBundleId === bundleId) {
        backToBundles();
      } else {
        await loadBundles();
      }
    },
    [request, openBundleId, backToBundles, loadBundles],
  );

  const reopen = useCallback(async (): Promise<ReopenedConsultation | null> => {
    if (!openConsultationId) return null;
    setReopening(true);
    try {
      const response = await request(`/consultations/${openConsultationId}/reopen`, 'POST');
      if (!response.ok) {
        const body = response.body as { message?: string };
        setMessage(body?.message ?? 'This consultation could not be reopened. Please try again.');
        return null;
      }
      const { session_id } = response.body as { session_id: string };
      const image = await window.spectrapaint.storedImage(openConsultationId, 'photo');
      if (image.status !== 'ready') {
        setMessage('This consultation could not be reopened. Please try again.');
        return null;
      }
      return {
        consultationId: openConsultationId,
        sessionId: session_id,
        imageDataUrl: image.imageDataUrl,
      };
    } finally {
      setReopening(false);
    }
  }, [request, openConsultationId]);

  return {
    bundles,
    consultations,
    renders,
    photoDataUrl,
    shadesOf,
    openBundleId,
    openConsultationId,
    reopening,
    message,
    refreshBundles: loadBundles,
    openBundle,
    backToBundles,
    backToBundle,
    openConsultation,
    createBundle,
    renameBundle,
    deleteBundle,
    reopen,
  };
}

export type Library = ReturnType<typeof useLibrary>;
