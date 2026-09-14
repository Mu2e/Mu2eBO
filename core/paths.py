"""Single source of truth for every filesystem root this project uses.

Stdlib only, no project imports. Importing never raises for a missing path
and never requires /exp/mu2e to exist: only artifact() and verify() stat
anything under the roots, which keeps the suite green on a machine with no
/exp/mu2e. Full rationale:
docs/superpowers/specs/2026-08-11-portable-paths-design.md.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathsError(RuntimeError):
    """A root could not be resolved, or verify() found a missing input."""


# Deliberately NOT configurable: an env override could only ever let this
# disagree with where the code is.
REPO_ROOT = Path(__file__).resolve().parents[1]


def _root_from_env_or_user(env_var: str, volume: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override)
    user = os.environ.get("USER")
    if not user:
        raise PathsError(
            f"cannot resolve the /exp/mu2e/{volume} root: $USER is unset and "
            f"${env_var} is not set. Export ${env_var} explicitly -- cron and "
            f"service accounts routinely have no $USER, and inventing a path "
            f"here would silently create an empty tree (see "
            f"wiki/incidents/touched-leaderboard-headerless-history-loss.md "
            f"for what an empty leaderboard costs).")
    return Path(f"/exp/mu2e/{volume}/users/{user}")


DATA_ROOT = _root_from_env_or_user("AUTORESEARCH_DATA_ROOT", "data")
ARTIFACT_ROOT = _root_from_env_or_user("AUTORESEARCH_ARTIFACT_ROOT", "app")


def _resolve_backing() -> Path | None:
    """A `backing` symlink in the repo root wins over the env var, so the
    operator's explicit `./setup.sh --backing` beats a stale export."""
    link = REPO_ROOT / "backing"
    if link.is_symlink():
        return Path(os.path.realpath(link))
    env = os.environ.get("AUTORESEARCH_BACKING")
    return Path(env) if env else None


BACKING = _resolve_backing()

# Per-operator runtime volumes; everything the runner writes derives from
# DATA_ROOT.
GRID_DATA_ROOT = DATA_ROOT / "autoresearch_grid"
GRAPH_DATA = DATA_ROOT / "autoresearch_graph_data"
LEADERBOARD_LIVE = DATA_ROOT / "autoresearch_leaderboards"
# propose/preflight scratch: runtime OUTPUT, so /data -- under REPO_ROOT it
# made `propose` die with PermissionError for anyone running from a checkout
# they do not own.
BO_WORK = DATA_ROOT / "autoresearch_bo_work"

# Concrete example beats a "<them>" placeholder; same value the README prints.
_EXAMPLE_BACKING = "/exp/mu2e/app/users/oksuzian"  # personal-path-ok: the published artifact area, see README


def _relative(rel: str, what: str) -> Path:
    p = Path(rel)
    if p.is_absolute():
        raise PathsError(
            f"{what} must be relative, got {rel!r}: pathlib's '/' operator "
            f"silently DISCARDS the left side when the right side is "
            f"absolute, so an absolute value escapes the root instead of "
            f"erroring.")
    return p


def artifact(rel: str) -> Path:
    """Muse's link order in one function: local wins, backing fills in.

    TOTAL -- a miss returns the INTENDED local path; verify() alone turns a
    miss into a failure, so spec loading at import cannot explode in a bare
    environment.
    """
    p = _relative(rel, "artifact() path")
    local = ARTIFACT_ROOT / p
    if local.exists():
        return local
    if BACKING is not None:
        backed = BACKING / p
        if backed.exists():
            return backed
    return local


def leaderboard_archive(rel: str) -> Path:
    """The committed read-only priors, at their repo-relative path."""
    return REPO_ROOT / _relative(rel, "leaderboard 'file'")


def leaderboard_live(rel: str) -> Path:
    """This operator's own appendable board. The live tree is FLAT, so only
    the basename survives -- why core/mode_json.py enforces basename
    uniqueness."""
    return LEADERBOARD_LIVE / _relative(rel, "leaderboard 'file'").name


def prodtools_root() -> Path:
    """The prodtools checkout from $AUTORESEARCH_PRODTOOLS; checked for
    bin/json2jobdef so a typo fails at the seam, not three subprocesses deep.
    """
    root = os.environ.get("AUTORESEARCH_PRODTOOLS")
    if not root:
        raise SystemExit(
            "AUTORESEARCH_PRODTOOLS is not set -- export it to the "
            "prodtools checkout (the directory holding bin/json2jobdef)")
    root = Path(root)
    if not (root / "bin" / "json2jobdef").exists():
        raise SystemExit(
            f"AUTORESEARCH_PRODTOOLS={root} has no bin/json2jobdef -- "
            f"not a prodtools checkout")
    return root


def _operator_hint() -> str:
    """Shared remediation tail; reads the roots at raise time so a test that
    patches them sees its own values."""
    return (f"  ARTIFACT_ROOT = {ARTIFACT_ROOT}\n"
            f"  BACKING       = {BACKING if BACKING else '(none)'}\n"
            f"Point at an operator who has it -- copy-paste "
            f"either line:\n"
            f"    ./setup.sh --backing {_EXAMPLE_BACKING}\n"
            f"    export AUTORESEARCH_BACKING={_EXAMPLE_BACKING}"
            f"   # if the checkout is not yours to write")


def require(path, what: str, *, tail: str = "") -> Path:
    """Stat one artifact; a miss is a named PathsError, not an rc=1.

    Exists because a direct `pipeline.py submit` never runs preflight, and
    bash answers a missing `source` target with rc=1 -- indistinguishable
    from a cvmfs flake, so the sourced_env retry loop burned four retries
    and named no cause (wiki/incidents/sourced-env-stderr-swallowed.md).
    """
    p = Path(path)
    if not p.exists():
        raise PathsError(f"{what} not found at {p}\n" + _operator_hint() + tail)
    return p


def verify(specs, *, extra=(), make_dirs: bool = True) -> None:
    """Fail at launch, not three hours into a grid chain.

    `specs`: iterable with .name/.musing/.grid_tarball (pass
    core.modes.SPECS.values()); `extra`: (path, description) pairs -- both
    injected, not imported, to stay project-import-free. Both
    prodtarget-env-divergence and foilsflash-tarball-mode-key-omission were
    "preflight used a patched local environment while the grid shipped an
    unpatched tarball"; unrepresentable once these resolve through one
    function. Leaderboard headers are deliberately NOT validated here
    (stdlib-only rule; SchemaMismatch covers it).
    """
    for spec in specs:
        for field in ("musing", "grid_tarball"):
            require(getattr(spec, field), f"mode {spec.name!r}: {field}",
                    tail="\nor build your own (see README, 'Artifacts').")
    for path, what in extra:
        require(path, what, tail="\nEvery mode's harvest needs it.")
    if make_dirs:
        for d in (GRID_DATA_ROOT, GRAPH_DATA, LEADERBOARD_LIVE):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise PathsError(f"cannot create {d}: {e}") from e
