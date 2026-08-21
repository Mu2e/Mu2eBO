#!/bin/bash
# Resolve this project's Python and export it as $AUTORESEARCH_PYTHON.
# Source it; do not execute it.
#
#   source activate.sh
#
# Default is the PUBLISHED Mu2e env on /cvmfs -- immutable, reproducible, the
# same interpreter on every node. Override for development:
#
#   AUTORESEARCH_VENV=/path/to/venv source activate.sh   # a writable venv
#   AUTORESEARCH_PYENV="ana 2.9.0"  source activate.sh   # a different release
#
# Why a published env: a personal /exp venv is one operator's directory, so a
# second person, a cron job, or a fresh node has nothing to point at.
# requirements.lock pins WHAT we depend on; this pins the interpreter those
# pins were verified against.
#
# The version is ALWAYS explicit. `pyenv ana` with no version silently means
# 2.7.0 (pyenv.sh:40) and `current` is 2.6.1 -- both ship numpy 1.26, which
# torch and botorch will not run on.
#
# NOTE this exports an interpreter PATH and deliberately does NOT activate
# the environment. `pyenv.sh` does three things we must not inherit: it
# `export -f`s wrappers for python/pip/jupyter/conda/mamba, and those
# wrappers re-run its setup on EVERY call, which re-prepends the env's
# site-packages to PYTHONPATH and its lib/ to LD_LIBRARY_PATH. Exported bash
# functions cross into every child process (they are why
# wiki/incidents/sourced-env-drops-muse-function-local-jobs.md exists), so an
# activated shell would push a second ROOT/XRootD binding and a second
# libstdc++ into the harvest steps that run PyROOT under `muse setup` --
# precisely the shadowing behind
# wiki/incidents/uproot-cannot-read-steppointmc.md. An absolute interpreter
# has none of that: no PATH edit, no PYTHONPATH, no LD_LIBRARY_PATH, nothing
# for a subprocess to inherit.

: "${AUTORESEARCH_PYENV:=ana 2.8.0}"
_MU2E="${MU2E:-/cvmfs/mu2e.opensciencegrid.org}"

if [[ -n "${AUTORESEARCH_VENV:-}" ]]; then
    if [[ ! -x "$AUTORESEARCH_VENV/bin/python" ]]; then
        echo "activate: AUTORESEARCH_VENV=$AUTORESEARCH_VENV has no" \
             "bin/python -- not a venv" >&2
        return 1
    fi
    export AUTORESEARCH_PYTHON="$AUTORESEARCH_VENV/bin/python"
    export AUTORESEARCH_PYTHON_SOURCE="venv $AUTORESEARCH_VENV"
else
    # "NAME VERSION" -> the published prefix, the same layout pyenv.sh builds
    # (pyenv.sh:50). Read directly rather than sourced, for the reasons above.
    read -r _name _version <<< "$AUTORESEARCH_PYENV"
    if [[ -z "$_version" ]]; then
        echo "activate: AUTORESEARCH_PYENV must be \"NAME VERSION\" (got" \
             "'$AUTORESEARCH_PYENV') -- an implicit version resolves to a" \
             "numpy-1.26 release that cannot run torch." >&2
        unset _name _version
        return 1
    fi
    _prefix="$_MU2E/env/$_name/$_version"
    if [[ ! -x "$_prefix/bin/python" ]]; then
        echo "activate: no interpreter at $_prefix/bin/python -- is /cvmfs" \
             "mounted, and is '$_name $_version' published? Set" \
             "AUTORESEARCH_VENV to a local venv to work without it." >&2
        unset _name _version _prefix
        return 1
    fi
    export AUTORESEARCH_PYTHON="$_prefix/bin/python"
    export AUTORESEARCH_PYTHON_SOURCE="pyenv $_name $_version"
    unset _name _version _prefix
fi

# Fail here rather than three subprocesses deep, and with PYTHONPATH empty --
# the contract the suite and every driver already run under.
if ! PYTHONPATH= "$AUTORESEARCH_PYTHON" -c 'import sys' 2>/dev/null; then
    echo "activate: $AUTORESEARCH_PYTHON is not a working interpreter" \
         "($AUTORESEARCH_PYTHON_SOURCE)" >&2
    return 1
fi
