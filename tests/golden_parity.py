#!/usr/bin/env python3
"""Golden parity harness (manually run; NOT part of unittest discover).

Usage:
    PYTHONPATH= .venv/bin/python tests/golden_parity.py capture [a b c]
    PYTHONPATH= .venv/bin/python tests/golden_parity.py check   [a b c]

(a) per-mode leaderboard round-trip: parse -> core/leaderboard.py's
    Leaderboard formatter over BOTH boards the archive/live split created
    (committed in-repo archive, and this operator's live board on
    $DATA_ROOT), reported under separate "archive"/"live" keys. Baseline =
    per-board row counts, skip counts, mismatch-index set, sha256 of
    regenerated lines. Pins reader+writer.
    Note: `mismatch_idx` is expected to be non-empty in places. `obj` is a
    DERIVED column, so re-deriving it from the disk-rounded sob/calo/alpha
    can differ from the full-precision original in the last decimal
    (3.10825 vs 3.10826). Those entries pin that rounding, they do not
    report corruption.
(b) loader fingerprint: `botorch_predict._load_history_tensor("foilsflash")`
    on the frozen leaderboard copy, hashed (sha256 of X/Y tensor bytes +
    shapes + bounds + int_dims). Exact-compare only.
    Was: fixed-seed hybrid q=2 picks — abandoned 2026-07-19, proved
    non-reproducible at production scale (scipy L-BFGS-B ABNORMAL-retry
    draws vary with BLAS noise; see
    wiki/incidents/hybrid-picker-scipy-abnormal-retry-nondeterminism.md).
    The tensor level has no optimizer in the loop and pins exactly what
    the Phase 1 schema refactor could break: leaderboard row ->
    (X, Y, bounds, int_dims) assembly.
(c) seam replay: evaluate (in-process, tmp leaderboard copy) + preflight
    (real G4, ~2 min) for a completed foilsflash config. Baseline = rc,
    obj, appended line, verdict line — and, once Phase 2 lands, the
    emitted JSON payloads (re-capture then).
Never writes to leaderboards/ — evaluate replays into a tmp copy.
"""
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
from csv import DictReader
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
import bo_driver as bo  # noqa: E402
import paths  # noqa: E402

GOLDENS = ROOT / "tests" / "goldens"
FROZEN_LB = GOLDENS / "leaderboard_bo_foilsflash.frozen.tsv"
B_BASE = GOLDENS / "history_tensor_fingerprint.json"
A_BASE = GOLDENS / "parity_a_baseline.json"
C_BASE = GOLDENS / "seam_replay_baseline.json"


def _roundtrip_file(path, lb):
    """Reader+writer parity pin over ONE board file."""
    raw_lines = path.read_text().splitlines(keepends=True)
    regen, mismatches, skipped = [], [], 0
    with path.open() as f:
        rows = list(DictReader(f, delimiter="\t"))
    for i, (row, raw) in enumerate(zip(rows, raw_lines[1:])):
        try:
            p = bo.Point(cfg=row["config"],
                        x=[float(row[c]) for c in lb.knob_names],
                        sob=float(row[lb.metric_cols[0]]),
                        calo=float(row[lb.metric_cols[1]]))
            alpha = float(row.get("alpha", bo.DEFAULT_ALPHA))
            line = lb._format_line(p, alpha)
        except (KeyError, ValueError):
            skipped += 1
            continue
        regen.append(line)
        if line != raw:
            mismatches.append(i)
    return {
        "rows": len(rows), "skipped": skipped, "mismatch_idx": mismatches,
        "header_matches_disk": lb.header() == raw_lines[0],
        "sha256": hashlib.sha256("".join(regen).encode()).hexdigest(),
    }


def _roundtrip_mode(name):
    """Both boards the archive/live split created, pinned separately.

    `mode.leaderboard` means the operator's LIVE board on $DATA_ROOT;
    `mode.leaderboard_archive` is the committed in-repo priors. Reporting
    them under separate keys is load-bearing: this function used to read
    only `mode.leaderboard` and return a bare None when it was absent, so
    after the split it returned None for EVERY mode and section (a) read as
    an 11-mode data regression rather than a harness that had stopped
    seeing its input. An absent board must be legible as absent.
    """
    mode = bo.MODES[name]
    lb = mode.leaderboard_io()
    return {
        slot: (_roundtrip_file(path, lb) if path and path.exists() else None)
        for slot, path in (("archive", mode.leaderboard_archive),
                           ("live", mode.leaderboard))
    }


def section_a():
    result = {name: _roundtrip_mode(name) for name in sorted(bo.MODES)}
    if not any(per_mode[slot]
               for per_mode in result.values() for slot in ("archive", "live")):
        raise SystemExit(
            "[a] pinned ZERO board files across all modes — the harness is "
            "reporting on boards it cannot see, which compares unequal and "
            "looks exactly like a data regression. Check that "
            "$AUTORESEARCH_DATA_ROOT is not redirecting the live tree and "
            "that the committed archives under leaderboards/ are present.")
    return result


def section_b():
    """Deterministic loader fingerprint on the frozen leaderboard copy.

    Was: fixed-seed hybrid q=2 picks — abandoned 2026-07-19, non-reproducible
    at production scale (scipy L-BFGS ABNORMAL-retry draws vary with BLAS
    noise; see wiki/incidents/hybrid-picker-scipy-abnormal-retry-
    nondeterminism.md). The tensor level has no optimizer in the loop and
    pins exactly what the Phase 1 schema refactor could break: leaderboard
    row -> (X, Y, bounds, int_dims) assembly.
    """
    import botorch_predict as bp
    mode = bo.MODES["foilsflash"]
    orig, orig_arch = mode.leaderboard, mode.leaderboard_archive
    mode.leaderboard = FROZEN_LB
    mode.leaderboard_archive = None
    try:
        X, Y, bounds, int_dims = bp._load_history_tensor("foilsflash")
    finally:
        mode.leaderboard = orig
        mode.leaderboard_archive = orig_arch
    return {
        "X_shape": list(X.shape), "Y_shape": list(Y.shape),
        "sha_X": hashlib.sha256(X.numpy().tobytes()).hexdigest(),
        "sha_Y": hashlib.sha256(Y.numpy().tobytes()).hexdigest(),
        "bounds": bounds.tolist(), "int_dims": list(int_dims),
    }


def _pick_replay_config():
    mode = bo.MODES["foilsflash"]
    grid = paths.GRID_DATA_ROOT
    for p in reversed(mode.load_history()):
        geom = mode.proposal_dir / f"{p.cfg}_geom.txt"
        summary = grid / p.cfg / "harvest" / "summary.json"
        if geom.exists() and summary.exists():
            return p.cfg, summary
    raise SystemExit("no completed foilsflash config with geom+summary found")


def section_c():
    cfg, summary = _pick_replay_config()
    result = {"config": cfg}
    # -- evaluate replay against a TMP leaderboard copy --
    mode = bo.MODES["foilsflash"]
    tmp = Path(tempfile.mkdtemp())
    lb_copy = tmp / mode.leaderboard.name
    shutil.copyfile(mode.leaderboard, lb_copy)
    orig, orig_arch = mode.leaderboard, mode.leaderboard_archive
    mode.leaderboard = lb_copy
    mode.leaderboard_archive = None
    try:
        buf = io.StringIO()
        args = SimpleNamespace(mode="foilsflash", config_name=cfg,
                               summary=str(summary), alpha=bo.DEFAULT_ALPHA,
                               emit_json=str(tmp / "evaluate_result.json"))
        with contextlib.redirect_stdout(buf):
            rc = bo.cmd_evaluate(args)
        m = re.search(r"obj=([+-]?\d+\.\d+)", buf.getvalue())
        result["evaluate"] = {
            "rc": rc, "obj": m.group(1) if m else None,
            "appended_line": lb_copy.read_text().splitlines()[-1],
        }
        ej = getattr(args, "emit_json", None)
        if ej and Path(ej).exists():
            result["evaluate"]["json"] = json.loads(Path(ej).read_text())
    finally:
        mode.leaderboard = orig
        mode.leaderboard_archive = orig_arch
    # -- preflight replay (real G4 init, ~2 min) --
    buf = io.StringIO()
    args = SimpleNamespace(mode="foilsflash", config_name=cfg)
    with contextlib.redirect_stdout(buf):
        rc = bo.cmd_preflight(args)
    verdict_lines = [ln for ln in buf.getvalue().splitlines()
                     if any(k in ln for k in ("PASS", "FAIL", "AMBIGUOUS"))]
    result["preflight"] = {"rc": rc,
                           "verdict_line": verdict_lines[-1] if verdict_lines else None}
    return result


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    sections = sys.argv[2:] or ["a", "b", "c"]
    GOLDENS.mkdir(exist_ok=True)
    fails = 0
    if "a" in sections:
        cur = section_a()
        if action == "capture":
            A_BASE.write_text(json.dumps(cur, indent=2))
            print(f"[a] captured -> {A_BASE}")
        else:
            base = json.loads(A_BASE.read_text())
            ok = cur == base
            print(f"[a] round-trip parity: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                for k in base:
                    if base[k] != cur.get(k):
                        print(f"    mode {k}: baseline={base[k]}\n"
                              f"             current ={cur.get(k)}")
                fails += 1
    if "b" in sections:
        if action == "capture":
            if not FROZEN_LB.exists():
                shutil.copyfile(
                    ROOT / "leaderboards" / "leaderboard_bo_foilsflash.tsv",
                    FROZEN_LB)
            B_BASE.write_text(json.dumps(section_b(), indent=2))
            print(f"[b] captured -> {B_BASE}")
        else:
            base, cur = json.loads(B_BASE.read_text()), section_b()
            ok = cur == base
            print(f"[b] history tensor fingerprint: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                for k in base:
                    if base[k] != cur.get(k):
                        print(f"    {k}: baseline={base[k]}\n"
                              f"          current ={cur.get(k)}")
                fails += 1
    if "c" in sections:
        cur = section_c()
        if action == "capture":
            C_BASE.write_text(json.dumps(cur, indent=2))
            print(f"[c] captured -> {C_BASE}")
        else:
            base = json.loads(C_BASE.read_text())
            ok = cur == base
            print(f"[c] seam replay parity: {'OK' if ok else 'MISMATCH'}")
            if not ok:
                print(f"    baseline={json.dumps(base, indent=2)}\n"
                      f"    current ={json.dumps(cur, indent=2)}")
                fails += 1
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
