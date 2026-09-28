#!/usr/bin/env python3
"""C2b parity: the anakit analyses against the old pipeline's harvest, on
the same archived files (Phase C2b spec,
docs/superpowers/specs/2026-09-27-c2b-anakit-analyses-design.md, "6. The
parity check"). Manual, outside the unit-test run; deleted with the
pipeline in C3.

  level1 [--limit N] [--workers W]
      the sensitivity scan alone on every archived foilspf* harvest
  level2 --config C --root R
      the full chain (sob and flash) on one archived point
  level3-setup --config C --root R --sandbox S
      hand-written prodtools records for the engine to adopt; prints the
      graph.study_run command to run next
  level3-check --config C --root R
      the engine's sob/flash results and board row against the archived
      summary.json (run with AUTORESEARCH_DATA_ROOT=S)

R is the grid root holding <config>/state and <config>/harvest (e.g.
$DATA_ROOT/autoresearch_grid). Every analysis runs through the anakit
adapter with foilspfbpz_ax's own settings, so the parity covers the adapter
and the study file as well as the analyses. Reports go under
<DATA_ROOT>/c2b_parity/. Exit 1 on any mismatch or failed analysis.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import paths  # noqa: E402

STUDY = "foilspfbpz_ax"
EXACT = ("muminus_stops", "mubeam_sim_total", "ce_seen", "ce_simulated_events")
REL_TOL = 1e-6
OUT = paths.DATA_ROOT / "c2b_parity"
WORKFLOW = "c2bparity"


# --- the comparison rules ----------------------------------------------------

def sob_matches(old: float, new: float) -> bool:
    """The macro printed S/sqrt(B) at 3 significant figures: `new` matches
    `old` when it is within half a unit of that last digit, plus 1e-4
    relative for anakit's convolution change (its README: 0.01%)."""
    if not old > 0 or not math.isfinite(new):
        return False
    unit = 10.0 ** (math.floor(math.log10(abs(old))) - 2)
    return abs(new - old) <= 0.5 * unit + 1e-4 * abs(old)


def rel_close(old: float, new: float, tol: float = REL_TOL) -> bool:
    return old != 0 and abs(new - old) <= tol * abs(old)


def compare_level2(summary: dict, sob: dict, flash: dict) -> list:
    """Each check as (quantity, old, new, ok), in the spec's order."""
    rows = [(k, summary[k], sob[k], float(summary[k]) == float(sob[k]))
            for k in EXACT]
    rows.append(("ce_abs_eff", summary["ce_abs_eff"], sob["ce_abs_eff"],
                 rel_close(summary["ce_abs_eff"], sob["ce_abs_eff"])))
    rows.append(("flash_edep_per_pot", summary["flash_edep_per_pot"],
                 flash["flash_edep_per_pot"],
                 rel_close(summary["flash_edep_per_pot"],
                           flash["flash_edep_per_pot"])))
    rows.append(("s_over_sqrt_b", summary["s_over_sqrt_b"],
                 sob["s_over_sqrt_b"],
                 sob_matches(summary["s_over_sqrt_b"], sob["s_over_sqrt_b"])))
    return rows


def level1_inputs(summary_paths) -> tuple:
    """(config, nts, ce_abs_eff, old sob) for each harvest that has all
    three; every other one as (path, reason) -- counted, never dropped."""
    rows, skipped = [], []
    for path in sorted(Path(p) for p in summary_paths):
        try:
            s = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            skipped.append((str(path), f"unreadable: {exc}"))
            continue
        missing = [k for k in ("ce_abs_eff", "s_over_sqrt_b")
                   if not isinstance(s.get(k), (int, float))]
        if missing:
            skipped.append((str(path), f"no {missing}"))
            continue
        nts = path.parent / "nts.ce.root"
        if not nts.is_file():
            skipped.append((str(path), "no nts.ce.root"))
            continue
        rows.append((path.parent.parent.name, nts, float(s["ce_abs_eff"]),
                     float(s["s_over_sqrt_b"])))
    return rows, skipped


# --- file refs and the adopted records ---------------------------------------

def file_ref(path) -> dict:
    p = Path(path)
    return {"name": p.name, "uri": p.resolve().as_uri(),
            "kind": p.suffix.lstrip(".") or "file"}


def adopted_record(config, step, files, events_per_job) -> dict:
    """A prodtools step's <step>_results.json as run_steps adopts it."""
    from adapters.prodtools import VERSION as PRODTOOLS_VERSION
    return {"step": step, "kit": "prodtools",
            "kit_version": PRODTOOLS_VERSION, "handle": f"{config}.{step}",
            "params": {}, "inputs": [],
            "metrics": {"njobs": len(files), "njobs_ok": len(files)},
            "files": [file_ref(f) for f in files],
            "metadata": {"events_per_job": events_per_job,
                         "source": "hand-written by tools/c2b_parity.py "
                                   "level3-setup from the archived pipeline "
                                   "outputs"}}


def outputs(state_dir: Path, stage: str) -> list:
    path = state_dir / f"{stage}_outputs.txt"
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"{path} lists no files")
    return lines


# --- running the analyses ----------------------------------------------------

def study_params(step_name: str) -> dict:
    import modes
    import scheduler
    study = modes.STUDIES[STUDY]
    step = next(s for s in study.steps if s.step == step_name)
    return scheduler.step_params(study, step, {}, False)


def analyze(kit, handle, params, refs):
    """(metrics, None) or (None, why). Every call into the kit -- submit,
    status, results -- is guarded: a bad point must become a per-point
    error in the report, never an exception out of pool.map that kills
    the whole run."""
    try:
        kit.submit(handle, params, [], refs, f"{WORKFLOW}/{handle}")
        status = kit.status(handle, WORKFLOW)
        if status.state != "completed":
            return None, status.message
        return kit.results(handle, WORKFLOW).metrics, None
    except Exception as exc:      # noqa: BLE001 - reported per point
        return None, f"{type(exc).__name__}: {exc}"


def _kit(sub):
    from adapters.anakit import AnakitKit
    return AnakitKit(WORKFLOW, grid_root=OUT / sub)


def _write_report(name, report) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(report, indent=1, default=str))
    return path


def level1(args) -> int:
    root = paths.GRID_DATA_ROOT
    summaries = sorted(root.glob("foilspf*/harvest/summary.json"))
    rows, skipped = level1_inputs(summaries)
    if not rows:
        print(f"level1: no foilspf*/harvest/summary.json under {root} has "
              f"both 'ce_abs_eff' and 's_over_sqrt_b' plus a sibling "
              f"nts.ce.root ({len(summaries)} summary.json found, "
              f"{len(skipped)} skipped); nothing to compare")
        return 2
    if args.limit:
        rows = rows[:args.limit]
    sob = study_params("sob")
    base = {k: sob[k] for k in ("work_area", "cosmic_rate_per_s_per_mev",
                                "dio_fraction", "dio_table")}
    kit = _kit("level1")

    def one(row):
        config, nts, eff, old = row
        params = {**base, "analysis": "approx_ce_sensitivity", "sig_eff": eff}
        metrics, why = analyze(kit, f"{config}.l1", params, [file_ref(nts)])
        new = metrics["sensitivity"] if metrics else None
        return {"config": config, "old": old, "new": new, "error": why,
                "ok": why is None and sob_matches(old, new)}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, rows))
    bad = [r for r in results if not r["ok"]]
    path = _write_report("level1", {"summary_files": len(summaries),
                                    "compared": len(results),
                                    "mismatched": len(bad), "results": results,
                                    "skipped": skipped})
    print(f"level1: {len(summaries)} summary file(s) found, {len(results)} "
          f"compared, {len(bad)} mismatched or failed, {len(skipped)} "
          f"skipped; report {path}")
    for r in bad:
        print(f"  {r['config']}: old {r['old']} new {r['new']} {r['error'] or ''}")
    return 1 if bad else 0


def level2(args) -> int:
    point = Path(args.root) / args.config
    state = point / "state"
    summary = json.loads((point / "harvest" / "summary.json").read_text())
    kit = _kit("level2")
    sob_refs = [file_ref(f) for f in outputs(state, "mubeam")
                + outputs(state, "mustops_ce")]
    flash_refs = [file_ref(f) for f in outputs(state, "elebeam_flash")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        sob_f = pool.submit(analyze, kit, f"{args.config}.sob",
                            study_params("sob"), sob_refs)
        flash_f = pool.submit(analyze, kit, f"{args.config}.flash",
                              study_params("flash"), flash_refs)
        (sob, sob_why), (flash, flash_why) = sob_f.result(), flash_f.result()
    if sob_why or flash_why:
        print(f"level2 {args.config}: sob: {sob_why or 'ok'}; "
              f"flash: {flash_why or 'ok'}")
        return 1
    rows = compare_level2(summary, sob, flash)
    path = _write_report(f"level2_{args.config}", {"rows": rows, "sob": sob,
                                                   "flash": flash})
    for q, old, new, ok in rows:
        print(f"  {'ok ' if ok else 'BAD'} {q}: old {old} new {new}")
    print(f"level2 {args.config}: report {path}")
    return 0 if all(r[3] for r in rows) else 1


def level3_setup(args) -> int:
    src = Path(args.root) / args.config / "state"
    dest = Path(args.sandbox) / "autoresearch_grid" / args.config / "state"
    if dest.exists():
        raise SystemExit(f"{dest} exists; use a fresh sandbox")
    dest.mkdir(parents=True)
    for step in ("mubeam", "mustops_ce", "elebeam_flash"):
        files = outputs(src, step)
        epj = int((src / f"{step}_events_per_job.txt").read_text().split()[0])
        (dest / f"{step}_results.json").write_text(json.dumps(
            adopted_record(args.config, step, files, epj), indent=1,
            sort_keys=True))
    print(f"wrote the three prodtools records under {dest}. Next:\n"
          f"  AUTORESEARCH_DATA_ROOT={args.sandbox} PYTHONPATH= "
          f"\"$AUTORESEARCH_PYTHON\" -m graph.study_run --study {STUDY} "
          f"--config {args.config} --campaign {WORKFLOW} --x=<the point's x> "
          f"--context alpha=100000.0 --executor local\n"
          f"then: AUTORESEARCH_DATA_ROOT={args.sandbox} PYTHONPATH= "
          f"\"$AUTORESEARCH_PYTHON\" tools/c2b_parity.py level3-check "
          f"--config {args.config} --root {args.root}")
    return 0


def level3_check(args) -> int:
    import modes
    summary = json.loads((Path(args.root) / args.config / "harvest"
                          / "summary.json").read_text())
    state = paths.GRID_DATA_ROOT / args.config / "state"
    sob = json.loads((state / "sob_results.json").read_text())["metrics"]
    flash = json.loads((state / "flash_results.json").read_text())["metrics"]
    rows = compare_level2(summary, sob, flash)
    study = modes.STUDIES[STUDY]
    board = paths.leaderboard_live(study.leaderboard_rel)
    with board.open() as f:
        found = [r for r in csv.DictReader(f, delimiter="\t")
                 if r["config"] == args.config]
    fmt = {o.name: o.fmt for o in study.objectives}
    want = {"sob": fmt["sob"].format(sob["s_over_sqrt_b"]),
            "flash_edep": fmt["flash_edep"].format(flash["flash_edep_per_pot"])}
    row_ok = (len(found) == 1
              and all(found[0][k] == v for k, v in want.items()))
    for q, old, new, ok in rows:
        print(f"  {'ok ' if ok else 'BAD'} {q}: old {old} new {new}")
    print(f"  {'ok ' if row_ok else 'BAD'} board row {board}: "
          f"{found[0] if found else 'missing'} (want {want})")
    return 0 if row_ok and all(r[3] for r in rows) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("level1")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    for name in ("level2", "level3-setup", "level3-check"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)
        p.add_argument("--root", required=True)
        if name == "level3-setup":
            p.add_argument("--sandbox", required=True)
    args = ap.parse_args(argv)
    return {"level1": level1, "level2": level2, "level3-setup": level3_setup,
            "level3-check": level3_check}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
