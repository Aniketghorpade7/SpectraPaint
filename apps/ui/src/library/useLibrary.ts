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
  // True once the first fetch of `bundles` has settled, success or failure — what tells
  // `BundleList` apart "still loading" from "genuinely has none yet" (issue #15: every surface
  // needs a defined loading state, not just an error and a happy path). Stays true afterwards, so
  // a rename or delete's own `loadBundles()` call never re-shows the loading state and flickers
  // the list away while it briefly re-fetches.
  const [bundlesLoaded, setBundlesLoaded] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const [consultations, setConsultations] = useState<ConsultationSummary[] | null>(null);
  const [openBundleId, setOpenBundleId] = useState<string | null>(null);

  const [renders, setRenders] = useState<RenderRecord[] | null>(null);
  const [photoDataUrl, setPhotoDataUrl] = useState<string | null>(null);
  const [openConsultationId, setOpenConsultationId] = useState<string | null>(null);

  const [lastDeleted, setLastDeleted] = useState<{
    bundleId: string;
    name: string;
    consultationIds: string[];
  } | null>(null);

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
      setBundlesLoaded(true);
      return;
    }
    setBundles((response.body as { bundles: BundleSummary[] }).bundles ?? []);
    setBundlesLoaded(true);
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
        setBundlesLoaded(true);
        return;
      }
      setBundles((response.body as { bundles: BundleSummary[] }).bundles ?? []);
      setBundlesLoaded(true);
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
      if (!history.ok) {
        setMessage(
          'The shades already tried in this consultation could not be loaded. Please try again.',
        );
        setRenders(null);
      } else {
        setRenders((history.body as { renders: RenderRecord[] }).renders ?? []);
      }

      const image = await window.spectrapaint.storedImage(consultationId, 'photo');
      if (image.status === 'ready') {
        setPhotoDataUrl(image.imageDataUrl);
      } else {
        setMessage((prev) =>
          prev
            ? prev + ' The photo for this consultation could not be loaded.'
            : 'The photo for this consultation could not be loaded. Please try again.',
        );
        setPhotoDataUrl(null);
      }
    },
    [request],
  );

  const retryConsultation = useCallback(async () => {
    if (openConsultationId) {
      await openConsultation(openConsultationId);
    } else {
      await loadBundles();
    }
  }, [openConsultation, openConsultationId, loadBundles]);

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
        const body = response.body as { code?: string; message?: string };
        if (body?.code === 'default_bundle_protected') {
          setMessage('The default bundle cannot be renamed.');
        } else {
          setMessage('The bundle could not be renamed. Please try again.');
        }
        return;
      }
      await loadBundles();
    },
    [request, loadBundles],
  );

  const deleteBundle = useCallback(
    async (bundleId: string) => {
      // Deleting a bundle moves its consultations to the default bundle; nothing is destroyed.
      // Capture which consultations will be moved so undo can put them back.
      const bundle = bundles.find((b) => b.bundle_id === bundleId);
      let consultationIds: string[] = [];
      try {
        const listed = await request(`/bundles/${bundleId}/consultations`);
        if (listed.ok) {
          consultationIds = (
            (listed.body as { consultations: ConsultationSummary[] }).consultations ?? []
          ).map((c) => c.consultation_id);
        } else {
          console.error('[library] could not list consultations before delete:', listed.body);
        }
      } catch (error) {
        console.error('[library] could not list consultations before delete:', error);
      }

      const response = await request(`/bundles/${bundleId}`, 'DELETE');
      if (!response.ok) {
        const body = response.body as { code?: string };
        if (body?.code === 'default_bundle_protected') {
          setMessage('The default bundle cannot be deleted.');
        } else {
          setMessage('The bundle could not be deleted. Please try again.');
        }
        return;
      }
      if (bundle) {
        setLastDeleted({ bundleId, name: bundle.name, consultationIds });
      }
      if (openBundleId === bundleId) {
        backToBundles();
      } else {
        await loadBundles();
      }
    },
    [request, bundles, openBundleId, backToBundles, loadBundles],
  );

  const undoDeleteBundle = useCallback(async () => {
    if (!lastDeleted) return;
    setMessage(null);
    const created = await request('/bundles', 'POST', { name: lastDeleted.name });
    if (!created.ok) {
      setMessage('The bundle could not be restored. Please try again.');
      return;
    }
    const newId = (created.body as { bundle_id: string }).bundle_id;
    let failed = false;
    for (const cid of lastDeleted.consultationIds) {
      try {
        const response = await request(`/bundles/${newId}/consultations`, 'POST', {
          consultation_id: cid,
        });
        if (!response.ok) {
          failed = true;
          console.error(
            '[library] could not restore consultation into bundle:',
            cid,
            response.body,
          );
        }
      } catch (error) {
        failed = true;
        console.error('[library] could not restore consultation into bundle:', cid, error);
      }
    }
    if (failed) {
      setMessage(
        'The bundle was restored but some consultations could not be moved back. Please try moving them manually.',
      );
      // Keep lastDeleted so the Dealer can retry; do not clear.
      await loadBundles();
      return;
    }
    setLastDeleted(null);
    await loadBundles();
  }, [request, lastDeleted, loadBundles]);

  const placeConsultation = useCallback(
    async (bundleId: string, consultationId: string) => {
      setMessage(null);
      const response = await request(`/bundles/${bundleId}/consultations`, 'POST', {
        consultation_id: consultationId,
      });
      if (!response.ok) {
        setMessage('The consultation could not be moved to that bundle. Please try again.');
        return false;
      }
      // Refresh the open bundle's listing if it is affected.
      if (openBundleId === bundleId) {
        const refreshed = await request(`/bundles/${bundleId}/consultations`);
        if (refreshed.ok) {
          setConsultations(
            (refreshed.body as { consultations: ConsultationSummary[] }).consultations ?? [],
          );
        }
      }
      await loadBundles();
      return true;
    },
    [request, openBundleId, loadBundles],
  );

  const reopen = useCallback(async (): Promise<ReopenedConsultation | null> => {
    if (!openConsultationId) return null;
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
    } catch {
      setMessage('This consultation could not be reopened. Please try again.');
      return null;
    }
  }, [request, openConsultationId]);

  return {
    bundles,
    bundlesLoaded,
    consultations,
    renders,
    photoDataUrl,
    shadesOf,
    openBundleId,
    openConsultationId,
    message,
    lastDeleted,
    refreshBundles: loadBundles,
    openBundle,
    backToBundles,
    backToBundle,
    openConsultation,
    retryConsultation,
    createBundle,
    renameBundle,
    deleteBundle,
    undoDeleteBundle,
    placeConsultation,
    reopen,
  };
}

export type Library = ReturnType<typeof useLibrary>;
