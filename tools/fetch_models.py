"""
Fetch the model weights named in models/manifest.toml, from their original upstream source.

Deliberately stdlib-only (Python 3.12): CI runs this before the Python service is installed, and
a contributor should be able to run it on a fresh checkout with nothing but Python.

    python tools/fetch_models.py              # fetch anything missing, verify everything
    python tools/fetch_models.py --verify     # verify what is on disk, fetch nothing
    python tools/fetch_models.py --cache-key  # print the Actions cache key and exit

Why upstream and not a mirror of our own: the SegFormer checkpoint is published under a
non-commercial research licence. Downloading it for development is fine; re-hosting it is
redistribution. So CI restores from the Actions cache and, on a miss, fetches from the publisher —
never from a Release we control. See docs/design-decisions.md §9b.
"""

import argparse
import hashlib
import shutil
import sys
import tomllib
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.toml"
MODELS_DIR = REPO_ROOT / "models"

# Big files over a slow runner link. Generous, but not unbounded.
TIMEOUT_SECONDS = 300
CHUNK_BYTES = 1024 * 1024


def display(path):
    """Repo-relative where possible, absolute otherwise.

    A manifest outside the repository is a legitimate thing to point at, not an error.
    """
    try:
        return Path(path).resolve().relative_to(REPO_ROOT)
    except ValueError:
        return Path(path).resolve()


def load_manifest(path=MANIFEST_PATH):
    with open(path, "rb") as f:
        return tomllib.load(f)["model"]


def cache_key(models):
    """A key that changes when, and only when, the pinned weights change.

    Keyed on the model versions themselves rather than on the manifest file, so editing a comment
    or a purpose line does not throw away a warm cache full of gigabytes.
    """
    identity = "\n".join(
        f"{m['id']}@{m['revision']}:{m['sha256']}" for m in sorted(models, key=lambda m: m["id"])
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def target_path(model):
    return MODELS_DIR / model["id"] / model["file"]


def source_url(model):
    return f"https://huggingface.co/{model['repo']}/resolve/{model['revision']}/{model['file']}"


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def download(model, destination):
    """Download to a temporary file and only then move it into place.

    A half-written weight that looks present is worse than one that is plainly absent — it would
    be cached, and every later run would restore the corruption.
    """
    url = source_url(model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")

    megabytes = model["size_bytes"] / 1_000_000
    print(f"  fetching {url}  ({megabytes:.0f} MB)")
    request = urllib.request.Request(url, headers={"User-Agent": "SpectraPaint-CI"})
    with (
        urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response,
        open(partial, "wb") as f,
    ):
        shutil.copyfileobj(response, f, CHUNK_BYTES)

    actual = sha256_of(partial)
    if actual != model["sha256"]:
        partial.unlink(missing_ok=True)
        raise SystemExit(
            f"  FAIL {model['id']}: downloaded file has sha256 {actual},\n"
            f"       manifest pins {model['sha256']}.\n"
            "       This is not the weight whose licence was reviewed. Refusing to keep it."
        )
    partial.replace(destination)


def process(model, verify_only):
    path = target_path(model)
    print(f"{model['id']}  [{model['licence']}]")

    if path.exists():
        actual = sha256_of(path)
        if actual == model["sha256"]:
            print(f"  ok, present and verified: {display(path)}")
            return True
        print(f"  sha256 mismatch on disk (found {actual})")
        if verify_only:
            return False
        path.unlink()

    if verify_only:
        print(f"  MISSING: {display(path)}")
        return False

    download(model, path)
    print(f"  ok, fetched and verified: {display(path)}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch pinned model weights from upstream.")
    parser.add_argument(
        "--verify", action="store_true", help="Verify what is on disk without downloading"
    )
    parser.add_argument(
        "--cache-key", action="store_true", help="Print the Actions cache key and exit"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    models = load_manifest(args.manifest)

    if args.cache_key:
        print(cache_key(models))
        return 0

    if not models:
        print("No models pinned in the manifest yet — nothing to fetch.")
        return 0

    print(f"{len(models)} model(s) pinned in {display(args.manifest)}\n")
    results = [process(model, args.verify) for model in models]
    print()

    if all(results):
        print("All weights present and matching the manifest.")
        return 0
    print("Some weights are missing or do not match the manifest.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
