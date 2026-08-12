"""Single source of truth for every filesystem root this project uses.

Stdlib only, and it imports nothing from the rest of the project, so the
botorch venv subprocess and the test suite can import it with no path games
(the same rule core/leaderboard.py follows).

Resolution is string math over the environment. Importing this module never
raises for a missing path and never requires /exp/mu2e to exist. The only
filesystem access at import is canonicalising this file's own location and a
single lstat probe of the `backing` symlink; nothing under DATA_ROOT or
ARTIFACT_ROOT is touched. Only artifact() and verify() stat those -- which is
what keeps the suite green on a machine with no /exp/mu2e.

Layout borrowed from Mu2e's own build system (see museSetup.sh /
museBacking.sh on cvmfs): location is identity, a `backing` link supplies
what you have not built yourself, and a setup-time gate refuses a backing
that cannot deliver. Full rationale, including what we deliberately do NOT
copy from muse (cwd-as-identity), is in
docs/superpowers/specs/2026-08-11-portable-paths-design.md.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathsError(RuntimeError):
    """A root could not be resolved, or verify() found a missing input."""


# Deliberately NOT configurable: this is not a preference, it is where the
# code is. An env override could only ever let the two disagree. Verified
# equal to the old hardcoded constant before this module existed.
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

# Per-operator runtime volumes. Everything the runner writes derives from
# DATA_ROOT: grid work trees, parent/child logs, and this operator's own
# appendable leaderboards.
GRID_DATA_ROOT = DATA_ROOT / "autoresearch_grid"
GRAPH_DATA = DATA_ROOT / "autoresearch_graph_data"
LEADERBOARD_LIVE = DATA_ROOT / "autoresearch_leaderboards"


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

    Total -- never raises for a missing file. A miss returns the INTENDED
    local path, so a caller's error message names where the operator meant
    to put it. verify() is the single place that turns a miss into a
    failure, which is why spec loading at import cannot explode in a bare
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
    the basename survives -- which is why core/mode_json.py enforces
    uniqueness on the basename rather than the whole relative path."""
    return LEADERBOARD_LIVE / _relative(rel, "leaderboard 'file'").name


def verify(specs, *, extra=(), make_dirs: bool = True) -> None:
    """Fail at launch, not three hours into a grid chain.

    `specs` is any iterable of objects carrying .name, .musing and
    .grid_tarball -- pass core.modes.SPECS.values(). `extra` is an iterable
    of (path, description) for artifacts that are not per-mode ModeSpec
    fields -- pass core.harvest.REQUIRED_ARTIFACTS. Both are injected rather
    than imported so this module stays project-import-free.

    Modelled on museSetup.sh:502, which refuses to proceed when the backing
    build cannot supply what is needed. Both prodtarget-env-divergence and
    foilsflash-tarball-mode-key-omission were "preflight used a patched
    local environment while the grid shipped an unpatched tarball"; both
    become unrepresentable once these resolve through one function.

    Deliberately does NOT validate leaderboard headers -- that would need an
    import of leaderboard.py, breaking the stdlib-only rule. Leaderboard's
    own SchemaMismatch and tests/test_live_leaderboard_headers.py already
    cover it twice over.
    """
    for spec in specs:
        for field in ("musing", "grid_tarball"):
            p = Path(getattr(spec, field))
            if not p.exists():
                raise PathsError(
                    f"mode {spec.name!r}: {field} not found at {p}\n"
                    f"  ARTIFACT_ROOT = {ARTIFACT_ROOT}\n"
                    f"  BACKING       = {BACKING if BACKING else '(none)'}\n"
                    f"Point at an operator who has it:\n"
                    f"    ./setup.sh --backing /exp/mu2e/app/users/<them>\n"
                    f"or build your own (see README, 'Artifacts').")
    for path, what in extra:
        p = Path(path)
        if not p.exists():
            raise PathsError(
                f"{what} not found at {p}\n"
                f"  ARTIFACT_ROOT = {ARTIFACT_ROOT}\n"
                f"  BACKING       = {BACKING if BACKING else '(none)'}\n"
                f"Every mode's harvest needs it. Point at an operator who "
                f"has it:\n"
                f"    ./setup.sh --backing /exp/mu2e/app/users/<them>")
    if make_dirs:
        for d in (GRID_DATA_ROOT, GRAPH_DATA, LEADERBOARD_LIVE):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise PathsError(f"cannot create {d}: {e}") from e
