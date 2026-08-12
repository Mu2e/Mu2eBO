#!/bin/bash
# Operator-facing skin over core/paths.py. Mirrors muse's verbs:
#   --status   ~ muse status
#   --backing  ~ muse backing
#
#   source setup.sh          export the resolved roots into this shell, so a
#                            campaign's children cannot have them shift
#   ./setup.sh --status      print the four roots and where each came from
#   ./setup.sh --backing P   link P as the artifact backing (local wins)
#   ./setup.sh --backing -r  remove the link
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
_PY="$_HERE/.venv/bin/python"
[[ -x "$_PY" ]] || _PY="python3"

_usage() {
    cat <<'EOF'
usage:
  source setup.sh              export resolved roots into this shell
  ./setup.sh --status          print the four roots and their provenance
  ./setup.sh --backing PATH    link PATH as the artifact backing
  ./setup.sh --backing -r      remove the backing link

Roots resolve from core/paths.py:
  REPO_ROOT      this file's location (never configurable)
  DATA_ROOT      $AUTORESEARCH_DATA_ROOT      or /exp/mu2e/data/users/$USER
  ARTIFACT_ROOT  $AUTORESEARCH_ARTIFACT_ROOT  or /exp/mu2e/app/users/$USER
  BACKING        the `backing` symlink, else $AUTORESEARCH_BACKING
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

if (( _SOURCED )); then
    _export
else
    case "${1:-}" in
        --status)  _dump ;;
        --backing) shift; _backing "${1:-}" ;;
        -h|--help) _usage ;;
        "")        _usage; exit 1 ;;
        *)         echo "ERROR - unknown option: $1" >&2; _usage >&2; exit 1 ;;
    esac
fi
