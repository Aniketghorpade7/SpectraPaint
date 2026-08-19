"""The Catalogue: the Shades a Dealer sells.

    from spectrapaint.catalogue import open_catalogue

    catalogue = open_catalogue()          # resolve the file, validate it, index it
    catalogue.find_by_code("AP-2140")

One call, because there is one right order to do this in — resolve the path, validate the whole
file, build the index — and a caller who assembles it themselves is a caller who can get it wrong.
"""

from collections.abc import Mapping

from spectrapaint.catalogue.database import build_catalogue_database
from spectrapaint.catalogue.loader import CatalogueFileInvalid, Lab, Shade, read_catalogue_file
from spectrapaint.catalogue.location import CatalogueFileMissing, resolve_catalogue_path
from spectrapaint.catalogue.queries import Catalogue

__all__ = [
    "Catalogue",
    "CatalogueFileInvalid",
    "CatalogueFileMissing",
    "Lab",
    "Shade",
    "open_catalogue",
]


def open_catalogue(environ: Mapping[str, str] | None = None) -> Catalogue:
    """Load the Catalogue the service should serve.

    Raises ``CatalogueFileMissing`` or ``CatalogueFileInvalid``, both of which carry a
    plain-language ``message`` for the Dealer and a ``detail`` for the log. Both are fatal at
    launch: a service that starts without a Catalogue looks healthy and cannot do the one thing it
    exists for.
    """

    catalogue_file = read_catalogue_file(resolve_catalogue_path(environ))
    return Catalogue(catalogue_file, build_catalogue_database(catalogue_file))
