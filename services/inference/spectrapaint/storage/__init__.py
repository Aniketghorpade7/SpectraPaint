"""What is kept when the process ends: the library of Bundles, Consultations and Renders.

    from spectrapaint.storage import Store, resolve_storage_dir

    store = Store(resolve_storage_dir())

One call, because there is one right order — resolve the directory, create it, open the database —
and a caller who assembles it themselves is a caller who can get it wrong. See storage/README.md
for what is kept, and what deliberately never is.
"""

from spectrapaint.storage.location import STORAGE_DIR_ENV_VAR, resolve_storage_dir
from spectrapaint.storage.store import DEFAULT_BUNDLE_NAME, Store

__all__ = [
    "DEFAULT_BUNDLE_NAME",
    "STORAGE_DIR_ENV_VAR",
    "Store",
    "resolve_storage_dir",
]
