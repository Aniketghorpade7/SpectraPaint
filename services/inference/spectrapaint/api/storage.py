"""Storage view and low-disk warning (issue #13).

    GET    /storage                       bundles by bytes + disk free
    DELETE /consultations/{id}            delete one Consultation and its files

The Storage view is what makes manual deletion informed — bundles sorted
largest first, with their bytes on disk. The disk probe is the early
warning: well before the disk is critically full, not at the point of
failure (docs/design-decisions.md §9).
"""

import shutil

from fastapi import APIRouter, Request, status

from spectrapaint.api.errors import CONSULTATION_NOT_FOUND, ServiceError

router = APIRouter(tags=["storage"])

# Well before critical: 2 GB or 10 % remaining, whichever is larger in
# absolute terms. Tunable, per conventions.md §4 — if shops fill faster,
# lower the floor rather than hiding the warning.
LOW_DISK_BYTES = 2 * 1024 * 1024 * 1024
LOW_DISK_RATIO = 0.10

_MESSAGE_CONSULTATION_NOT_FOUND = "That consultation is not in your library."
_MESSAGE_STORAGE_LOW = (
    "Your disk is getting full. Open Storage to delete old Bundles — "
    "otherwise new photos may fail to save."
)


def _store(request: Request):
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise ServiceError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="storage_unavailable",
            message="Saved consultations are unavailable in this service.",
        )
    return store


def _disk_info(store) -> dict:
    """Free/total for the volume holding the library, and whether it is low."""
    try:
        usage = shutil.disk_usage(str(store.directory))
        free = int(usage.free)
        total = int(usage.total)
    except OSError:
        # If we cannot probe, do not claim the disk is low — the warning
        # would be noise and the failure would still be caught on write.
        return {"free_bytes": 0, "total_bytes": 0, "low": False, "warning": None}
    low = free < LOW_DISK_BYTES or (total > 0 and free / total < LOW_DISK_RATIO)
    return {
        "free_bytes": free,
        "total_bytes": total,
        "low": low,
        "warning": _MESSAGE_STORAGE_LOW if low else None,
    }


@router.get("/storage")
async def read_storage(request: Request) -> dict:
    """Bundles sorted by bytes, largest first, plus the disk probe."""
    store = _store(request)
    bundles = store.storage_overview()
    disk = _disk_info(store)
    return {"bundles": bundles, "disk": disk}


@router.get("/storage/disk")
async def read_disk(request: Request) -> dict:
    """The disk probe alone — for the global banner without loading the whole view."""
    store = _store(request)
    return _disk_info(store)


@router.delete("/consultations/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_consultation(request: Request, consultation_id: str) -> None:
    """Delete a Consultation: its photos, mattes, renders and database rows."""
    store = _store(request)
    if not store.consultation_exists(consultation_id):
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=CONSULTATION_NOT_FOUND,
            message=_MESSAGE_CONSULTATION_NOT_FOUND,
        )
    deleted = store.delete_consultation(consultation_id)
    if not deleted:
        raise ServiceError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=CONSULTATION_NOT_FOUND,
            message=_MESSAGE_CONSULTATION_NOT_FOUND,
        )
