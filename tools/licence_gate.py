"""
Fail the build when an unapproved licence appears among dependencies or shipped weights.

    python tools/licence_gate.py            # everything: npm, python, weights
    python tools/licence_gate.py --list     # print every licence found, and pass regardless

Run it with the service environment active so the Python dependencies are visible — from
services/inference, which is where that environment lives:

    cd services/inference
    uv run python ../../tools/licence_gate.py

The policy lives in tools/approved-licences.toml, deliberately separate from this file: the list of
licences we accept is a business decision that should be reviewable without reading code.

Three things are checked:

  1. npm dependencies       — from `npm ls --all --json --long`
  2. Python dependencies    — from the metadata of the running interpreter's environment, split
                              into what ships and what is only ever build-time tooling
  3. Model weights          — from models/manifest.toml, including whether any weight we are not
                              allowed to redistribute has been committed to the repository

The gate exists to protect one thing: what leaves here on a Dealer's machine. So it holds the
**shipped** set to the commercial bar and build-time tooling to a looser one — the same
distinction it has always drawn for weights via `shipped`, now drawn for Python packages too
(ticket #6).

Which Python packages ship is not a list anyone maintains here. It is derived from the service's
own `pyproject.toml`: `dependencies` ship, and dependency *groups* (`dev`, `export`) do not. That
is what makes torch admissible — it turns checkpoints into `.onnx` files on a developer's machine
and is never installed on a Dealer's (see the `export` group's own comment).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = Path(__file__).resolve().with_name("approved-licences.toml")
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.toml"

# Free-text licence names, as they actually appear in package metadata, mapped to SPDX. Package
# authors write these by hand, so the variety is upstream's, not ours.
FREE_TEXT_TO_SPDX = {
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache-2": "Apache-2.0",
    "apache 2.0 license": "Apache-2.0",  # transformers writes it this way
    "bsd license": "BSD-3-Clause",
    "bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",  # protobuf writes it this way
    "simplified bsd license": "BSD-2-Clause",
    "mit license": "MIT",
    "the mit license": "MIT",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "mozilla public license 2.0": "MPL-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "the unlicense": "Unlicense",
    "the unlicense (unlicense)": "Unlicense",
    "zlib/libpng license": "Zlib",
}

# A `License:` field long enough to be the licence text itself, not its name. Some packages paste
# the whole document in there; the classifiers are more reliable in that case.
MAX_SENSIBLE_LICENCE_LENGTH = 120

UNKNOWN = "UNKNOWN"


def normalise(raw):
    """Map one licence string to an SPDX-ish identifier, as best it can be mapped."""
    if not raw:
        return UNKNOWN
    text = raw.strip().strip('"')
    if len(text) > MAX_SENSIBLE_LICENCE_LENGTH:
        return UNKNOWN
    return FREE_TEXT_TO_SPDX.get(text.lower(), text)


def licence_from_classifiers(classifiers):
    """`License :: OSI Approved :: MIT License` → MIT."""
    for classifier in classifiers:
        if not classifier.startswith("License ::"):
            continue
        name = classifier.split("::")[-1].strip()
        mapped = normalise(name)
        if mapped != UNKNOWN:
            return mapped
    return UNKNOWN


def is_approved(expression, approved):
    """Evaluate an SPDX expression against the approved set.

    Handles the forms that occur in practice: a bare identifier, `(A OR B)`, `A AND B`, and
    `Apache-2.0 WITH LLVM-exception`. An OR passes if either side does; an AND needs both.
    """
    if expression == UNKNOWN:
        return False

    text = expression.replace("(", " ").replace(")", " ").strip()
    text = re.sub(r"\s+WITH\s+\S+", "", text, flags=re.IGNORECASE)

    or_parts = re.split(r"\s+OR\s+", text, flags=re.IGNORECASE)
    if len(or_parts) > 1:
        return any(is_approved(part.strip(), approved) for part in or_parts)

    and_parts = re.split(r"\s+AND\s+", text, flags=re.IGNORECASE)
    if len(and_parts) > 1:
        return all(is_approved(part.strip(), approved) for part in and_parts)

    return normalise(text) in approved


def npm_dependencies():
    """Every npm package in the tree, with its declared licence.

    Our own workspace packages are private and unpublished, so they declare no licence and are
    skipped — the gate is about what we bring in, not about what we wrote.
    """
    npm = shutil.which("npm")
    if npm is None:
        print("npm not found — skipping the npm dependencies.", file=sys.stderr)
        return []

    result = subprocess.run(
        [npm, "ls", "--all", "--json", "--long"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout.strip():
        raise SystemExit(f"`npm ls` produced no output:\n{result.stderr}")

    tree = json.loads(result.stdout)
    found = {}
    absent = []
    not_installed_here = []

    def walk(node):
        for name, info in (node.get("dependencies") or {}).items():
            key = (name, info.get("version"))
            if key in found:
                continue
            if info.get("missing"):
                # Declared but not installed at all: the tree has not been installed.
                absent.append(name)
                continue
            if not info.get("version"):
                # An optional dependency for another platform — esbuild ships one prebuilt binary
                # per OS and architecture, and npm resolves only ours. Nothing is on disk to check.
                not_installed_here.append(name)
                continue
            if info.get("private") or str(name).startswith("@spectrapaint/"):
                found[key] = None
            else:
                found[key] = normalise(info.get("license"))
            walk(info)

    walk(tree)

    if absent:
        # Reporting these as "licence unknown" would be a lie: they are not installed, so nothing
        # about them has been checked at all.
        raise SystemExit(
            f"{len(absent)} npm package(s) are declared but not installed, so their licences "
            f"cannot be checked: {', '.join(sorted(absent)[:5])}"
            f"{' ...' if len(absent) > 5 else ''}\nRun `npm ci` first."
        )

    if not_installed_here:
        print(
            f"note: {len(not_installed_here)} optional package(s) target another platform and are "
            "not installed here, so they are not checked."
        )

    # Every npm package is treated as shipping. Splitting npm's dev tree from the bundled one is
    # a larger job than this ticket needs, and holding tooling to the stricter bar errs in the
    # safe direction — it can only refuse something, never wave it through.
    return [
        ("npm", name, version, licence, True)
        for (name, version), licence in sorted(found.items())
        if licence is not None
    ]


SERVICE_DIR = REPO_ROOT / "services" / "inference"


def canonical(name):
    """PyPI names compared the way PyPI compares them: case- and separator-insensitive."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def shipped_python_packages():
    """The Python packages that reach a Dealer's machine, or None if that cannot be determined.

    Derived by asking uv to resolve the service's `dependencies` with every dependency group
    excluded, so the answer comes from `pyproject.toml` rather than from a second list here that
    could drift away from it.

    Returning None means "could not tell" — and the caller then treats *everything* as shipped.
    A gate that cannot work out what ships must get stricter, never quieter.
    """
    uv = shutil.which("uv")
    if uv is None:
        print("uv not found — every Python package will be held to the shipping bar.")
        return None

    result = subprocess.run(
        [uv, "export", "--no-default-groups", "--no-hashes", "--no-annotate", "--no-header"],
        cwd=SERVICE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "note: `uv export` failed, so the shipped set is unknown and every Python package is\n"
            f"      held to the shipping bar.\n{result.stderr.strip()}"
        )
        return None

    shipped = set()
    for line in result.stdout.splitlines():
        requirement = line.split(";")[0].strip()
        if not requirement or requirement.startswith(("#", "-")):
            continue
        shipped.add(canonical(requirement.split("==")[0]))
    return shipped or None


def python_dependencies():
    """Every distribution installed in the environment running this script."""
    found = {}
    for dist in distributions():
        metadata = dist.metadata
        name = metadata["Name"]
        if not name or name in found:
            continue
        licence = normalise(metadata.get("License-Expression")) or UNKNOWN
        if licence == UNKNOWN:
            licence = normalise(metadata.get("License"))
        if licence == UNKNOWN:
            licence = licence_from_classifiers(metadata.get_all("Classifier") or [])
        found[name] = (dist.version, licence)
    shipped = shipped_python_packages()
    return [
        ("python", name, version, licence, shipped is None or canonical(name) in shipped)
        for name, (version, licence) in sorted(found.items())
    ]


def weights():
    """Every weight in the manifest, as (ecosystem, id, revision, licence, shipped)."""
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, "rb") as f:
        models = tomllib.load(f).get("model", [])
    return [
        ("weight", m["id"], m["revision"][:12], m["licence"], m.get("shipped", False), m)
        for m in models
    ]


def committed_weight_files():
    """Weight files tracked by git — always a violation, regardless of licence.

    Weights are fetched, never committed. For the SegFormer checkpoint specifically, committing or
    mirroring it would be redistribution of a non-commercially-licensed file.
    """
    result = subprocess.run(
        ["git", "ls-files", "models/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    allowed = {"models/README.md", "models/manifest.toml"}
    return [line for line in result.stdout.split() if line and line not in allowed]


def load_policy():
    with open(POLICY_PATH, "rb") as f:
        policy = tomllib.load(f)
    exceptions = {(e["ecosystem"], e["name"]): e for e in policy.get("exception", [])}
    return set(policy["approved"]), set(policy["development_only"]), exceptions


def _print_licence_counts(heading, rows):
    counts = {}
    for _, _, _, licence, _ in rows:
        counts[licence] = counts.get(licence, 0) + 1
    print(heading)
    for licence, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {count:>4}  {licence}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Fail on unapproved dependency or weight licences."
    )
    parser.add_argument(
        "--list", action="store_true", help="Print every licence found and pass regardless"
    )
    args = parser.parse_args()

    approved, development_only, exceptions = load_policy()
    violations = []

    print("SpectraPaint licence gate")
    print(f"policy: {POLICY_PATH.relative_to(REPO_ROOT)}")
    print()

    # ---- dependencies ---------------------------------------------------
    # Two bars, one rule: anything that reaches a Dealer's machine must carry a licence approved
    # for commercial distribution; build-time tooling may also carry a development-only licence,
    # because it is not distributed at all. Tooling that would fail *both* still fails.
    packages = npm_dependencies() + python_dependencies()
    for ecosystem, name, version, licence, ships in packages:
        if (ecosystem, name) in exceptions:
            continue
        permitted = approved if ships else approved | development_only
        if not is_approved(licence, permitted):
            where = "" if ships else " (build-time only)"
            violations.append(
                f"{ecosystem}: {name} {version}{where} — {licence}"
                + (" (no licence declared upstream)" if licence == UNKNOWN else "")
            )

    shipping = [row for row in packages if row[4]]
    tooling = [row for row in packages if not row[4]]
    _print_licence_counts(f"{len(shipping)} shipped dependencies checked (npm + python):", shipping)
    if tooling:
        _print_licence_counts(
            f"{len(tooling)} build-time dependencies checked (never distributed):", tooling
        )

    # ---- model weights --------------------------------------------------
    weight_rows = weights()
    print(f"{len(weight_rows)} model weight(s) checked:")
    for _, model_id, revision, licence, shipped, model in weight_rows:
        label = "shipped" if shipped else "development only"
        print(f"  {model_id} @{revision} — {licence} ({label})")
        if shipped:
            if not is_approved(licence, approved):
                violations.append(
                    f"weight: {model_id} is marked shipped but its licence ({licence}) is not "
                    "approved for distribution"
                )
        elif licence not in development_only and not is_approved(licence, approved):
            violations.append(
                f"weight: {model_id} carries an unlisted licence ({licence}). Add it to "
                "approved or development_only in the policy, deliberately."
            )
        if shipped and not model.get("redistribute", False):
            violations.append(
                f"weight: {model_id} is marked shipped but redistribute = false. Shipping a file "
                "we may not redistribute is exactly the mistake this gate exists to catch."
            )
    print()

    committed = committed_weight_files()
    for path in committed:
        violations.append(
            f"weight: {path} is committed to the repository. Weights are fetched from upstream, "
            "never committed or mirrored (design-decisions.md §9b)."
        )

    # ---- verdict --------------------------------------------------------
    if args.list:
        for ecosystem, name, version, licence, ships in packages:
            label = "shipped" if ships else "build-time"
            print(f"{ecosystem:<7} {name:<45} {version:<14} {label:<11} {licence}")
        return 0

    if not violations:
        print("PASS — everything shipped carries a licence approved for distribution.")
        return 0

    print(f"FAIL — {len(violations)} licence violation(s):")
    print()
    for violation in violations:
        print(f"  - {violation}")
    print()
    print(
        "Either drop the dependency, or add its licence to tools/approved-licences.toml as a\n"
        "deliberate decision — to `approved` if the thing is distributed, to `development_only`\n"
        "if it is build-time tooling that never leaves this repository. Do not add one to make\n"
        "the build green: SpectraPaint ships as a commercial binary to dealerships, and that is\n"
        "the standard every entry is judged against."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
