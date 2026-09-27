#!/usr/bin/env python3
"""Bayesian Optimization driver for Mu2e geometry searches.

Modes are schema-2 study files (mode_specs/<name>.json; format in
docs/superpowers/specs/2026-09-23-generic-study-design.md, how-to in
mode_specs/README.md), loaded by core/study.py into modes.STUDIES.

Subcommands:
  propose   : propose next candidate(s), render geom override file(s)
  evaluate  : parse summary.json + append to leaderboard
  preflight : run mu2e -n 1 locally to catch G4 init failures

JsonMode is the single driver class, one instance per spec; MODES is keyed
1:1 with modes.SPECS (ADR-0002). Adding a mode = drop a JSON file.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

# ModeSpec registry (ADR-0002): preflight policy flags replace the
# hand-listed mode tuples behind the preflight-mode-tuple-omission class.
import modes as _modes  # noqa: E402

from leaderboard import (  # noqa: E402  (re-exports: Point, to_py_scalars
    Leaderboard, Point, to_py_scalars,   # are public API of this module)
    _flock_ex, _flock_sh, _lock_path)

from paths import REPO_ROOT as ROOT  # single root resolver, see core/paths.py
from paths import BO_WORK, GRID_DATA_ROOT
from paths import leaderboard_archive, leaderboard_live

# Explicit-env mode stamp; see core/modes.py::stamp_mode_from_argv.
os.environ.setdefault("AUTORESEARCH_MODE", _modes.resolve_env_mode())
from runtime import PREFLIGHT_TIMEOUT_S  # noqa: E402
sys.path.insert(0, str(ROOT / "graph"))
# The geometry pre-check, shared with the engine's offline_preflight kit
# (Phase C2a). PREFLIGHT_VERDICTS stays importable from here.
from adapters import preflight_checks as pc  # noqa: E402
from adapters.preflight_checks import PREFLIGHT_VERDICTS  # noqa: E402

DEFAULT_ALPHA = 1.0e5  # mmackenz calo range 4e-8..2.5e-5; alpha=1e5 makes
                       # 1e-5 calo cost 1 unit of S/sqrt(B). Override per study.


class SpaceDim(NamedTuple):
    """One search-space dimension (the picker reads bounds off the study;
    this exists for printing)."""
    name: str
    low: float
    high: float
    is_int: bool


# --- JsonMode: the mode seam. One instance per mode_specs/*.json ----------

class JsonMode:
    """A BO mode = search space + render + leaderboard format, all read
    from the same modes.SPECS spec (TSV I/O delegated to
    core/leaderboard.py via leaderboard_io())."""
    name: str
    leaderboard: Path
    proposal_dir: Path
    preflight_dir: Path

    def __init__(self, name: str):
        spec = _modes.SPECS[name]
        if spec.geom is None:
            raise ValueError(f"{name}: JsonMode requires a geom template")
        self.name = name
        # Live rows -> operator's /data board; committed leaderboards/ are
        # read-only priors.
        self.leaderboard = leaderboard_live(spec.leaderboard_rel)
        self.leaderboard_archive = leaderboard_archive(spec.leaderboard_rel)
        self.proposal_dir = BO_WORK / "proposals" / name
        self.preflight_dir = BO_WORK / "preflight" / name

    def _geom_text(self, x) -> str:
        return _modes.SPECS[self.name].geom.render(x)

    # --- x recovery at evaluate time (the seam cmd_evaluate calls) ---
    def x_for_evaluate(self, config_name: str):
        """Recover x from the pending TSV (written at propose, cleared only
        after this call). An absent config is a HARD refusal: a guessed x
        would train the GP on a point that was never evaluated.
        """
        for name, x in self.load_pending():
            if name == config_name:
                return list(x)
        raise SystemExit(
            f"[{self.name}] cannot recover x for {config_name!r}: no such row "
            f"in {self.pending_path()}. JSON-defined modes have no geometry "
            f"parser, so the pending TSV is the ONLY record of the proposed "
            f"x; it is written by propose and cleared by a SUCCESSFUL "
            f"evaluate. Re-running evaluate for an already-recorded config "
            f"hits this. Refusing to append a row rather than guess x.")

    # KNOB_NAMES/KNOB_FMTS read modes.SPECS, the single source (ADR-0002
    # extension) -- no class-attr overrides. The leaderboard row shape
    # comes from modes.STUDIES via leaderboard_io().
    @property
    def KNOB_NAMES(self) -> tuple:
        return _modes.SPECS[self.name].knob_names

    @property
    def KNOB_FMTS(self) -> tuple:
        return _modes.SPECS[self.name].knob_fmts

    # bounds↔KNOB_NAMES must line up 1:1 -- a mismatch is a loud error,
    # never a silently-truncated space.
    def build_space(self) -> list[SpaceDim]:
        spec = _modes.SPECS[self.name]
        # names, bounds and int_dims all derive from the study's one knobs
        # list, so the zip below cannot truncate
        int_dims = set(spec.int_dims or ())
        return [
            SpaceDim(nm, float(lo), float(hi), i in int_dims)
            for i, (lo, hi, nm) in enumerate(
                zip(spec.bounds_lo, spec.bounds_hi, self.KNOB_NAMES))
        ]

    def render_proposal(self, name: str, x) -> Path:
        self.proposal_dir.mkdir(parents=True, exist_ok=True)
        out = self.proposal_dir / f"{name}_geom.txt"
        out.write_text(self._geom_text(x))
        return out

    # --- leaderboard + pending I/O: owned by core/leaderboard.py -----------
    def leaderboard_io(self) -> Leaderboard:
        lb = getattr(self, "_lb_cache", None)
        # Rebuild whenever the cached instance's paths no longer match (attr
        # patching is the standard test seam AND a runtime path): a
        # path-blind cache would keep serving a stale Leaderboard -- the
        # failure mode of
        # wiki/incidents/touched-leaderboard-headerless-history-loss.md at
        # the object-cache layer.
        archive = getattr(self, "leaderboard_archive", None)
        if lb is None or lb.path != self.leaderboard or lb.archive_path != archive:
            lb = Leaderboard.for_study(_modes.STUDIES[self.name],
                                       path=self.leaderboard,
                                       archive_path=archive)
            self._lb_cache = lb
        return lb

    def load_history(self) -> list[Point]:
        return self.leaderboard_io().load()

    def append_history(self, p: Point, context: dict):
        self.leaderboard_io().append(p, context)

    def pending_path(self) -> Path:
        return self.leaderboard_io().pending_path()

    def load_pending(self) -> list[tuple[str, list]]:
        return self.leaderboard_io().pending_load()

    def append_pending(self, name: str, x, alpha: float):
        self.leaderboard_io().pending_add(name, x, alpha)

    def remove_pending(self, name: str) -> bool:
        return self.leaderboard_io().pending_remove(name)

    def extract_metrics(self, summary: dict) -> dict:
        """summary.json -> {objective/extra-metric name: value or None}.

        Phase A: summary.json is still one flat harvest file, so a metric
        'step.key' resolves by its key. No fallback between keys: two keys
        are two different quantities (per-POT vs per-event flash differ by
        units)."""
        study = _modes.STUDIES[self.name]
        out = {}
        for item in (*study.objectives, *study.extra_metrics):
            v = summary.get(item.key)
            out[item.name] = None if v is None else float(v)
        return out


MODES: dict[str, JsonMode] = {}

# One JsonMode per spec carrying a geom template.
for _name, _spec in _modes.SPECS.items():
    if _spec.geom is not None:
        MODES[_name] = JsonMode(_name)


# --- BO ask: botorch subprocess (the single ask engine) --------------------

def botorch_ask(mode_name: str, q: int = 1, *, seed_idx: int = 0,
                picker: str = "qnehvi", pending: list | None = None,
                venv_py: Path | None = None,
                leaderboard: Path | None = None,
                timeout_s: int = 14400) -> list[list]:
    """Ask the botorch picker for q points; returns a list of x-lists.

    EVERY BO ask goes through here (CLI propose, graph propose_one,
    closed-loop picker): shells botorch_predict.py in the botorch venv,
    round-tripping picks through a temp JSON file. seed_idx -> --round-idx
    (Sobol/acq seed = 42 ^ idx), so a bumped seed_idx draws fresh points.
    `pending` x-lists ride --pending-json and are fantasized (X_pending).
    venv_py default resolves the AUTORESEARCH_BOTORCH_VENV env seam;
    leaderboard is a test/golden-only override.
    """
    import subprocess

    if venv_py is None:
        # Default to the CALLER's interpreter, so the picker's torch is the
        # torch the rest of the chain runs on; a repo-relative `.venv`
        # default silently pinned the GP fit to the old venv once the
        # launchers moved to the published cvmfs env. The env seam still
        # names a repo-relative venv directory, for a two-build picker A/B.
        ab_venv = os.environ.get("AUTORESEARCH_BOTORCH_VENV")
        venv_py = (ROOT / ab_venv / "bin" / "python") if ab_venv \
            else Path(sys.executable)
    venv_py = Path(venv_py)
    if not venv_py.exists():
        raise FileNotFoundError(
            f"[botorch_ask] picker python missing: {venv_py} "
            f"(set AUTORESEARCH_BOTORCH_VENV to a repo-relative venv, or "
            f"run under an interpreter that has botorch)")

    predict = Path(__file__).resolve().parent / "botorch_predict.py"
    with tempfile.NamedTemporaryFile(mode="r", suffix=".json", delete=False) as tf:
        out_path = Path(tf.name)
    pend_path = None
    try:
        cmd = [
            str(venv_py), str(predict),
            "--mode", mode_name, "--q", str(q),
            "--round-idx", str(seed_idx),
            "--picker", picker,
            "--emit-picks-json", str(out_path),
        ]
        if leaderboard is not None:
            cmd += ["--leaderboard", str(leaderboard)]
        if pending:
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False) as pf:
                json.dump([list(x) for x in pending], pf)
                pend_path = Path(pf.name)
            cmd += ["--pending-json", str(pend_path)]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s)
        if r.returncode != 0:
            raise RuntimeError(
                f"[botorch_ask] botorch_predict rc={r.returncode}: "
                f"stderr={r.stderr.strip()[:400]}")
        raw = json.loads(out_path.read_text())
    finally:
        for p in (out_path, pend_path):
            if p is not None:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
    return [list(p) for p in raw]


# --- Subcommands ------------------------------------------------------------

def cmd_propose(args):
    mode = MODES[args.mode]
    names = args.config_names
    lock_path = _lock_path(mode.leaderboard.with_name(f"propose_{mode.name}"))
    with lock_path.open("w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        return _cmd_propose_locked(args, mode, names)


def _cmd_propose_locked(args, mode, names):
    history = mode.load_history()
    pending = mode.load_pending()

    existing = {p.cfg for p in history} | {n for n, _ in pending}
    dupes = [n for n in names if n in existing]
    if dupes:
        print(f"ERROR: name(s) already used (in leaderboard or pending): {dupes}",
              file=sys.stderr)
        return 1

    q = len(names)
    space = mode.build_space()
    print(f"[{mode.name}] botorch ask: {len(history)} history rows, "
          f"{len(pending)} pending (in-flight, fantasized as X_pending)")

    xs = botorch_ask(mode.name, q=q, pending=[px for _, px in pending])
    print(f"\nProposed batch of {q}:")

    for name, x in zip(names, xs):
        print(f"\n  '{name}':")
        for dim, val in zip(space, x):
            print(f"    {dim.name:24s} = {val}")
        geom = mode.render_proposal(name, x)
        # Auto-stage geom into the per-config work tree
        # (wiki/incidents/template-fcl-staleness.md).
        work_geom_dir = GRID_DATA_ROOT / name / "geom"
        work_geom_dir.mkdir(parents=True, exist_ok=True)
        work_geom = work_geom_dir / f"autoresearch_{name}_geom.txt"
        shutil.copy(geom, work_geom)
        print(f"    geom: {geom}  →  {work_geom}")
        mode.append_pending(name, x, args.alpha)

    print(f"\nPending file: {mode.pending_path()}")
    print(f"\nNext per config (run in parallel):")
    for name in names:
        print(f"  pipeline.py --config {name} submit mubeam")
    print(f"\nThen as each finishes:")
    print(f"  ./core/bo_driver.py --mode {mode.name} --alpha {args.alpha} "
          f"evaluate <name> <summary.json>")
    return 0


# Where each leaderboard.context name gets its value at evaluate time. A
# study naming a context value with no entry here fails the row
# pre-validation in cmd_evaluate, before anything is written.
_CONTEXT_SOURCES = {"alpha": lambda args: args.alpha}


def cmd_evaluate(args):
    mode = MODES[args.mode]
    study = _modes.STUDIES[mode.name]
    context = {c: f(args) for c, f in _CONTEXT_SOURCES.items()
               if c in study.context}
    summary = json.loads(Path(args.summary).read_text())
    values = mode.extract_metrics(summary)
    # A missing value is NEVER coerced to a number: a fake zero row dominates
    # the whole Pareto front at the next GP refit
    # (wiki/incidents/no-run1b-substitution-poisons-flash-modes.md).
    missing = [n for n, v in values.items() if v is None]
    if missing:
        print(f"[{mode.name}] summary.json has no value for {missing} "
              f"({[i.metric for i in (*study.objectives, *study.extra_metrics) if i.name in missing]}) "
              f"— refusing to append a row; recover the failed stage first.")
        return 1
    for o in study.objectives:
        if o.transform == "log10" and values[o.name] <= 0:
            raise SystemExit(
                f"[{mode.name}] objective {o.name!r} resolved to "
                f"{values[o.name]!r} from summary.json key {o.key!r} -- "
                f"refusing to append a row; a zero/negative log10 objective "
                f"would dominate the Pareto front at the next GP refit")
    x = mode.x_for_evaluate(args.config_name)
    p = Point(cfg=args.config_name, x=x, y=values)
    # Format the row BEFORE clearing pending: the pending row is the ONLY
    # record of x, so anything the formatter can raise (a missing context
    # value, an extra-column expression failing on these values) must fire
    # while that record still exists.
    try:
        mode.leaderboard_io().format_line(p, context)
    except Exception as e:
        raise SystemExit(
            f"[{mode.name}] cannot format the leaderboard row for "
            f"{p.cfg!r}: {e!r}. The pending row (the only record of x) is "
            f"kept; fix the study's extra_columns/context ({study.path}) "
            f"and re-run evaluate.") from e
    # Clear pending BEFORE appending: a crash in between leaves "missing
    # leaderboard row" (loud, re-runnable) rather than a silent phantom
    # pending row that trips propose_one's collision guard.
    removed = mode.remove_pending(args.config_name)
    mode.append_history(p, context)
    primary = study.objectives[0].name
    if getattr(args, "emit_json", None):
        write_json_atomic(Path(args.emit_json), {
            "config": p.cfg,
            "primary": values[primary],
            "objectives": {o.name: values[o.name] for o in study.objectives},
            "row_appended": True,
        })
    pend_tag = "  (cleared from pending)" if removed else ""
    shown = ", ".join(f"{o.name}={values[o.name]:.4g}" for o in study.objectives)
    print(f"[{mode.name}] recorded {p.cfg}: {shown}  →  "
          f"{mode.leaderboard}{pend_tag}")
    return 0


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp+rename (atomic within one filesystem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


_VERDICT_LABELS = {"pass": "PASS", "fail_managed": "FAIL",
                   "ambiguous": "AMBIGUOUS"}
_RC_OF_VERDICT = {v: k for k, v in PREFLIGHT_VERDICTS.items()}


def _cmd_preflight_impl(args):
    mode = MODES[args.mode]
    spec = _modes.SPECS[mode.name]

    import harvest as _harvest
    import paths as _paths
    # Preflight runs first, so a missing backing surfaces here -- including
    # harvest's Run1BAna artifacts, which no earlier step touches.
    _paths.verify([spec], extra=_harvest.REQUIRED_ARTIFACTS, make_dirs=False)

    name = args.config_name
    geom = mode.proposal_dir / f"{name}_geom.txt"
    if not geom.exists():
        print(f"Proposal geom not found: {geom}", file=sys.stderr)
        return 2

    mode.preflight_dir.mkdir(parents=True, exist_ok=True)
    workdir = GRID_DATA_ROOT / name / "preflight"
    log = mode.preflight_dir / f"{name}.log"
    print(f"[preflight/{mode.name}] cfg={name}  workdir={workdir}  log={log}")
    print(f"[preflight/{mode.name}] geom: {geom}  fcl: {pc.FCL_NAME}")

    # The code the grid jobs run: the mode's code tarball, unpacked once per
    # content, so preflight and grid cannot diverge (the prodtarget
    # env-divergence and foilsg holeRadii incidents).
    verdict, out = pc.run_preflight(
        spec.grid_tarball, geom.read_text(), name, workdir,
        cache_root=GRID_DATA_ROOT / "_code",
        dumps_gdml=spec.dumps_gdml,
        verifies_foil_gdml=spec.verifies_foil_gdml,
        checks_managed_overlap=spec.checks_managed_overlap,
        require_zero_overlaps=spec.require_zero_overlaps,
        label=f"preflight/{mode.name}", timeout_s=PREFLIGHT_TIMEOUT_S,
        log=sys.stdout)
    log.write_text(out)

    for note in verdict.notes:
        print(f"[preflight/{mode.name}] {note}")
    if verdict.gdml_verified:
        # Kept where the pipeline has always kept it, only once the as-built
        # comparison passed.
        keep_dir = GRID_DATA_ROOT / name / "geom"
        keep_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(workdir / pc.PREFLIGHT_GDML_NAME,
                        keep_dir / f"asbuilt_{name}.gdml")
    print(f"[preflight/{mode.name}] {_VERDICT_LABELS[verdict.code]}  "
          f"{verdict.reason}")
    if verdict.code == "ambiguous":
        print(f"[preflight/{mode.name}] See {log}")
    return _RC_OF_VERDICT[verdict.code]


def cmd_preflight(args):
    rc = _cmd_preflight_impl(args)
    if getattr(args, "emit_json", None):
        mode = MODES[args.mode]
        verdict = PREFLIGHT_VERDICTS.get(rc, "ambiguous")
        write_json_atomic(Path(args.emit_json), {
            "verdict": verdict,
            "rc": rc,
            # Coarse cause class; the log carries the detailed FAIL lines.
            "reasons": [f"preflight classifier verdict: {verdict} (rc={rc})"],
            "log_path": str(mode.preflight_dir / f"{args.config_name}.log"),
            "config": args.config_name,
        })
    return rc


def cmd_pending_prune(args):
    mode = MODES[args.mode]
    removed = mode.leaderboard_io().pending_prune(
        older_than_h=args.older_than_hours)
    if removed:
        print(f"[{mode.name}] pruned {len(removed)} stale pending row(s): "
              + ", ".join(removed))
    else:
        print(f"[{mode.name}] nothing stale "
              f"(threshold {args.older_than_hours:.0f}h)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=list(MODES.keys()), required=True,
                    help="Search-space mode")
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                    help=f"Scalarization weight (default {DEFAULT_ALPHA})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prop = sub.add_parser("propose",
                            help="Propose q≥1 candidate(s) + render geom(s). "
                                 "Pass multiple names for batch BO (CL-mean by default).")
    p_prop.add_argument("config_names", nargs="+",
                        help="One or more proposal names, e.g. `helical003 helical004 helical005`")
    p_prop.set_defaults(func=cmd_propose)

    p_eval = sub.add_parser("evaluate", help="Record completed run in leaderboard")
    p_eval.add_argument("config_name")
    p_eval.add_argument("summary", help="path to harvest/summary.json")
    p_eval.add_argument("--emit-json", dest="emit_json", default=None,
                        help="Write the typed result JSON to this path "
                             "(graph seam; written only after the row lands)")
    p_eval.set_defaults(func=cmd_evaluate)

    p_pre = sub.add_parser("preflight", help="Run mu2e -n 1 locally to test G4 init feasibility")
    p_pre.add_argument("config_name", help="Proposal name (must exist in proposal dir)")
    p_pre.add_argument("--emit-json", dest="emit_json", default=None,
                       help="Write the typed verdict JSON to this path "
                            "(graph seam; tmp+rename atomic)")
    p_pre.set_defaults(func=cmd_preflight)

    p_prune = sub.add_parser(
        "pending-prune",
        help="Delete pending rows older than a threshold (never automatic; "
             "this is the command the stale-row warning points at)")
    p_prune.add_argument("--older-than-hours", type=float, default=48.0)
    p_prune.set_defaults(func=cmd_pending_prune)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
