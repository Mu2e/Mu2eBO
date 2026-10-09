"""Single source of truth for every filesystem root this project uses.

Stdlib only, no project imports. Importing never raises for a missing path
and never requires /exp/mu2e to exist: only artifact() stats anything under
the roots, which keeps the suite green on a machine with no /exp/mu2e. Full
rationale: docs/superpowers/specs/2026-08-11-portable-paths-design.md.
"""
from __future__ import annotations

import os
from pathlib import Path


class PathsError(RuntimeError):
    """A root could not be resolved, or a path argument is malformed."""


# Deliberately NOT configurable: an env override could only ever let this
# disagree with where the code is.
REPO_ROOT = Path(__file__).resolve().parents[1]
# The study files every runner and the MCP servers load (core/modes.py).
MODES_DIR = REPO_ROOT / "mode_specs"


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

# Sibling surrokit checkout (the generic ask/tell engine). Overridable so
# tests and other operators can point at a different checkout.
SURROKIT_ROOT = Path(os.environ.get("AUTORESEARCH_SURROKIT")
                     or REPO_ROOT.parent / "surrokit")

# The surrokit SHA this repo was parity-validated against. The suite
# asserts the checkout matches; bump DELIBERATELY after re-validating
# (run a picker smoke + the surrogate tests against the new engine).
SURROKIT_PIN_SHA = "26929f7c22bcd9c4bef0c09d453309ae35300fbe"


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

    TOTAL -- a miss returns the INTENDED local path; the kit that opens it
    turns a miss into a failure, so study loading at import cannot explode
    in a bare environment.
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
    the basename survives -- why core/study.py enforces basename
    uniqueness."""
    return LEADERBOARD_LIVE / _relative(rel, "leaderboard 'file'").name
