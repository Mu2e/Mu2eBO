#!/bin/bash
# Operator-facing skin over core/paths.py. Mirrors muse's verbs:
#   --status   ~ muse status
#   --backing  ~ muse backing
#
#   source setup.sh          export the resolved roots into this shell, so a
#                            campaign's children cannot have them shift
#   ./setup.sh --status      print the resolved roots + venv, and their origins
#   ./setup.sh --backing P   link P as the artifact backing (local wins)
#   ./setup.sh --backing -r  remove the link
#   ./setup.sh --venv [P]    link P (default: the site venv) as .venv
#   ./setup.sh --venv -r     remove the .venv link
#
# --venv defaults to a named area and --backing does not, deliberately.
# Borrowing a venv gives you a library stack that requirements.txt already
# pins; borrowing a BACKING silently changes your physics results, so that
# one stays explicit.
#
# Deliberately does NOT activate the venv and does NOT touch PYTHONPATH:
# the test suite depends on `PYTHONPATH=` being empty, and this script has
# one job. Resolution itself lives in core/paths.py -- this is a view over
# it, never a second implementation.
_SOURCED=0
[[ "${BASH_SOURCE[0]}" != "$0" ]] && _SOURCED=1
# Strict mode only when EXECUTED. When sourced this runs in the operator's own
# shell and is never restored, so `set -u` would leak into their session and
# turn a later bare `echo $UNSET_VAR` into a fatal error. Every parameter
# expansion below already carries a `${x:-}` default, so nothing here relies
# on `set -u`.
(( _SOURCED )) || set -uo pipefail

_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The interpreter that resolves the roots. Prefer the one `activate.sh`
# resolved, so --status reports roots derived by the SAME python that will
# run the chain; `.venv` and a bare python3 are fallbacks for a shell that
# has not sourced activate.sh yet. Any of them works -- core/paths.py is
# stdlib-only by contract -- but reporting from a different interpreter than
# the one about to run is the kind of near-miss that hides a real one.
_PY="${AUTORESEARCH_PYTHON:-}"
[[ -n "$_PY" && -x "$_PY" ]] || _PY="$_HERE/.venv/bin/python"
[[ -x "$_PY" ]] || _PY="python3"

# The reference venv of this deployment, used when --venv is given no path.
# Deliberately NOT in core/paths.py: nothing the code resolves depends on it,
# and paths.py must stay a pure resolver. Another deployment overrides it with
# $AUTORESEARCH_SITE_VENV rather than editing this file.
_SITE_VENV="${AUTORESEARCH_SITE_VENV:-/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv}"  # personal-path-ok: naming the site venv IS the feature

_usage() {
    cat <<'EOF'
usage:
  source setup.sh              export resolved roots into this shell
  ./setup.sh --status          print the roots + venv and their provenance
  ./setup.sh --backing PATH    link PATH as the artifact backing
  ./setup.sh --backing -r      remove the backing link
  ./setup.sh --venv [PATH]     link PATH as .venv (default: the site venv)
  ./setup.sh --venv -r         remove the .venv link

Roots resolve from core/paths.py:
  REPO_ROOT      this file's location (never configurable)
  DATA_ROOT      $AUTORESEARCH_DATA_ROOT      or /exp/mu2e/data/users/$USER
  ARTIFACT_ROOT  $AUTORESEARCH_ARTIFACT_ROOT  or /exp/mu2e/app/users/$USER
  BACKING        the `backing` symlink, else $AUTORESEARCH_BACKING

--venv has a default and --backing does not: a borrowed venv gives you a
stack requirements.txt already pins, a borrowed backing changes your results.
EOF
}

# One python call prints everything; the shell never re-derives a path.
_dump() {
    PYTHONPATH= "$_PY" - "$_HERE" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "core"))
import paths

def why(env_var):
    return "env" if os.environ.get(env_var) else "default ($USER)"

print(f"REPO_ROOT     {paths.REPO_ROOT}   (this file's location)")
print(f"DATA_ROOT     {paths.DATA_ROOT}   ({why('AUTORESEARCH_DATA_ROOT')})")
print(f"ARTIFACT_ROOT {paths.ARTIFACT_ROOT}   "
      f"({why('AUTORESEARCH_ARTIFACT_ROOT')})")
if paths.BACKING is None:
    print("BACKING       (none)   -- ./setup.sh --backing <path> to set one")
else:
    src = "symlink" if (paths.REPO_ROOT / "backing").is_symlink() else "env"
    print(f"BACKING       {paths.BACKING}   ({src})")
print(f"  grid        {paths.GRID_DATA_ROOT}")
print(f"  logs        {paths.GRAPH_DATA}")
print(f"  live boards {paths.LEADERBOARD_LIVE}")
PY
    # Not a resolver root, so it is reported from the shell rather than from
    # core/paths.py -- but an operator reading --status wants it here. Report
    # what is ACTIVE, which since the pyenv switch is usually not `.venv`:
    # `source activate.sh` exports both of these.
    if [[ -n "${AUTORESEARCH_PYTHON:-}" ]]; then
        echo "PYTHON        $AUTORESEARCH_PYTHON   (${AUTORESEARCH_PYTHON_SOURCE:-?})"
    else
        echo "PYTHON        (not resolved)   -- 'source activate.sh' first;" \
             "default is the published cvmfs env"
    fi
    if [[ -L "$_HERE/.venv" ]]; then
        echo "  .venv       $(readlink "$_HERE/.venv")   (symlink; dev override, AUTORESEARCH_VENV)"
    elif [[ -d "$_HERE/.venv" ]]; then
        echo "  .venv       $_HERE/.venv   (real directory; dev override, AUTORESEARCH_VENV)"
    fi
}

_export() {
    local out d a
    # Same argv-passing shape as _dump: $_HERE never gets embedded in Python
    # source text, and one interpreter start instead of two.
    out="$(PYTHONPATH= "$_PY" - "$_HERE" <<'PY'
import os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "core"))
import paths
print(paths.DATA_ROOT)
print(paths.ARTIFACT_ROOT)
PY
)" || return 1
    { IFS= read -r d; IFS= read -r a; } <<< "$out"
    export AUTORESEARCH_DATA_ROOT="$d"
    export AUTORESEARCH_ARTIFACT_ROOT="$a"
    echo "exported AUTORESEARCH_DATA_ROOT=$d"
    echo "exported AUTORESEARCH_ARTIFACT_ROOT=$a"
}

_backing() {
    local target="${1:-}"
    local link="$_HERE/backing"
    if [[ -z "$target" ]]; then
        echo "ERROR - --backing needs a path (or -r to remove)" >&2
        return 1
    fi
    if [[ "$target" == "-r" || "$target" == "--rm" ]]; then
        rm -f "$link"
        echo "removed backing link"
        return 0
    fi
    if [[ ! -d "$target" ]]; then
        echo "ERROR - backing target is not a directory: $target" >&2
        return 1
    fi
    if [[ -e "$link" && ! -L "$link" ]]; then
        echo "ERROR - $link exists and is not a symlink" >&2
        return 1
    fi
    ln -sfn "$(cd "$target" && pwd)" "$link"
    echo "backing -> $(cd "$target" && pwd)"
}

_venv() {
    local target="${1:-$_SITE_VENV}"
    local link="$_HERE/.venv"
    if [[ "$target" == "-r" || "$target" == "--rm" ]]; then
        if [[ -L "$link" ]]; then
            rm -f "$link"
            echo "removed .venv link"
            return 0
        fi
        if [[ -e "$link" ]]; then
            echo "ERROR - $link is a real directory, not a link - remove it yourself" >&2
            return 1
        fi
        echo "no .venv link to remove"
        return 0
    fi
    # Never clobber: an existing .venv may be a build the operator spent
    # twenty minutes on, and `ln -sfn` over it would be silent.
    if [[ -e "$link" || -L "$link" ]]; then
        echo "ERROR - $link already exists - './setup.sh --venv -r' first if you mean to replace it" >&2
        return 1
    fi
    if [[ ! -x "$target/bin/python" ]]; then
        echo "ERROR - not a usable venv (no bin/python): $target" >&2
        # The venvs live one level down, so pointing at the containing
        # directory is the obvious near-miss. Name the fix rather than
        # making the operator guess at the tree.
        if [[ -x "$target/.venv/bin/python" ]]; then
            echo "       did you mean ${target%/}/.venv ?" >&2
        fi
        return 1
    fi
    target="$(cd "$target" && pwd)"
    ln -s "$target" "$link"
    echo ".venv -> $target"
    [[ -w "$target" ]] || echo "note: read-only for you - fine to run, but build your own before changing a pin"
}

if (( _SOURCED )); then
    _export
else
    case "${1:-}" in
        --status)  _dump ;;
        --backing) shift; _backing "${1:-}" ;;
        --venv)    shift; _venv "${1:-}" ;;
        -h|--help) _usage ;;
        "")        _usage; exit 1 ;;
        *)         echo "ERROR - unknown option: $1" >&2; _usage >&2; exit 1 ;;
    esac
fi
