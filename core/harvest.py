"""Eval-summary module: the schema and pure logic behind `pipeline.py harvest`.

This is the deep half of cmd_harvest (see wiki
concepts/architecture-friction-survey-2026-07, 2026-07-11 re-survey FP-1/FP-2):
everything that can be computed or decided WITHOUT touching the grid, a muse
env, or a subprocess lives here, behind small typed interfaces. pipeline.py
keeps the CLI verb, env sourcing, and the subprocess-invoking extractors, and
passes those extractors IN as callables — so every branch in this module is
unit-testable from tests/ (no grid, no ROOT).

Vocabulary (CONTEXT.md): an **Eval summary** is the explicit product of
harvest — the typed key set below, written to harvest/summary.json; the
leaderboard row is derived from it by the driver's extract_metrics.

Invariant ownership (FP-2): whether concat ran for THIS Eval is decided by
`resolve_muminus_inputs` from the Eval's state dir alone (stage-chain stamp
if present, else file presence) — never from the process env. The same stamp
is what submit-side template materialization must consult.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

# --- physics/parse constants (moved verbatim from pipeline.py) --------------

RUN1A_MUBEAM_INPUT_CORRECTION = 0.01278168
POT_PER_ELECTRON = 25_000_000 / 2_166_994  # EleBeamCat dh.gencount / event_count

# EdepAna prints the count via %g: >1M events arrive as "2.70937e+06"
# (incident: edepana-saw-events-scientific-notation-parse).
EDEP_SAW_RX = re.compile(r"EdepAna summary:\s*Saw\s+([\d.eE+-]+)\s+events")
S_OVER_SQRTB_RX = re.compile(
    r"^Signal box.*S/sqrt\(B\)\s*=\s*([\d.eE+-]+)\s*$", re.MULTILINE)

STAGE_CHAIN_STAMP = "stage_chain.txt"


# --- pure parsers ------------------------------------------------------------

def parse_edepana_saw(stdout: str) -> int:
    """Event count from EdepAna's 'Saw N events' line; raises on absence."""
    m = EDEP_SAW_RX.search(stdout)
    if not m:
        raise ValueError("EdepAna 'Saw N events' summary not found")
    return int(float(m.group(1)))


def parse_s_over_sqrt_b(stdout: str) -> float:
    """S/sqrt(B) from rough_run1a_sensitivity.C output; raises on absence."""
    m = S_OVER_SQRTB_RX.search(stdout)
    if not m:
        raise ValueError("S/sqrt(B) not found in macro output")
    return float(m.group(1))


# --- Steps 1 & 4: subprocess-shaped harvest work, behind injected runners ---
# (harvest.py stays stdlib-only; runner(cmd, cwd) is a proc-like the CALLER
# binds env for — see pipeline.py's _mu2e_runner / _root_runner.)

from paths import REPO_ROOT as AUTORESEARCH  # see core/paths.py
EDEP_FCL = AUTORESEARCH / "Run1BAna/workflows/fcl/edep.fcl"
SENSITIVITY_MACRO = AUTORESEARCH / "Run1BAna/workflows/scripts/rough_run1a_sensitivity.C"


def run_edepana(harvest_dir: Path, ce_files: Sequence[Path], *, runner):
    """Harvest Step 1: EdepAna over the CeEndpoint art files.

    Returns (ce_seen, nts_path). Writes ce_files.txt, edep_wrapper.fcl and
    edep.log into harvest_dir. runner(cmd, cwd) -> proc-like; the caller
    binds env/FHICL_FILE_PATH. HARD-fail (SystemExit) on rc != 0 or an
    unparseable 'Saw N events' line — this is the sob numerator, never
    fail-soft (unlike extract_secondary_edep).
    """
    ce_list = harvest_dir / "ce_files.txt"
    ce_list.write_text("\n".join(str(p) for p in ce_files) + "\n")
    nts_path = harvest_dir / "nts.ce.root"
    wrapper = harvest_dir / "edep_wrapper.fcl"
    wrapper.write_text(
        f'#include "{EDEP_FCL.relative_to(AUTORESEARCH).as_posix()}"\n'
        f'services.TFileService.fileName: "{nts_path.name}"\n'
    )
    edep_log = harvest_dir / "edep.log"
    proc = runner(["mu2e", "-c", str(wrapper), "-S", str(ce_list)],
                  harvest_dir)
    edep_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"EdepAna failed (rc={proc.returncode}); see {edep_log}")
    try:
        return parse_edepana_saw(proc.stdout), nts_path
    except ValueError as e:
        raise SystemExit(f"{e}; see {edep_log}")


def run_sensitivity_macro(harvest_dir: Path, nts_path: Path,
                          ce_abs_eff: float, *, runner) -> float:
    """Harvest Step 4: rough_run1a_sensitivity.C -> S/sqrt(B).

    cwd is the Run1BAna workflows dir (macro path in cmd is
    workflows-relative). Writes rough_run1a_sensitivity.log. HARD-fail on
    rc != 0 / unparseable output.
    """
    macro_log = harvest_dir / "rough_run1a_sensitivity.log"
    cwd = SENSITIVITY_MACRO.parent.parent
    cmd = ["root", "-q", "-b", "-l",
           f'scripts/rough_run1a_sensitivity.C("{nts_path}", '
           f'{ce_abs_eff:.16g}, "{harvest_dir}")']
    proc = runner(cmd, cwd)
    macro_log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(
            f"rough_run1a_sensitivity.C failed (rc={proc.returncode}); "
            f"see {macro_log}")
    try:
        return parse_s_over_sqrt_b(proc.stdout)
    except ValueError as e:
        raise SystemExit(f"{e}; see {macro_log}")


# --- stage-chain stamp (the one owner of "did concat run for this Eval") ----

def stamp_stage_chain(state_dir: Path, stages: Sequence[str]) -> None:
    """Record the mode's stage chain at submit time (events_per_job pattern).

    Written once per Eval alongside the first submit; harvest and template
    materialization read it back so a config evaluated under an older chain
    is never re-interpreted under the current env's chain.
    """
    (state_dir / STAGE_CHAIN_STAMP).write_text("\n".join(stages) + "\n")


def stamped_stage_chain(state_dir: Path) -> Optional[list[str]]:
    """The submit-time stage chain, or None for pre-stamp legacy configs."""
    p = state_dir / STAGE_CHAIN_STAMP
    if not p.exists():
        return None
    return [ln.strip() for ln in p.read_text().splitlines() if ln.strip()]


def read_outputs(state_dir: Path, stage: str) -> Optional[list[Path]]:
    """Non-blank lines of state/<stage>_outputs.txt, or None if absent.

    A present-but-blank file (stage-out-lag face) returns [] — callers must
    treat that as a hard error for primary inputs, not as 'stage absent'.
    """
    p = state_dir / f"{stage}_outputs.txt"
    if not p.exists():
        return None
    return [Path(ln) for ln in p.read_text().splitlines() if ln.strip()]


def concatless(state_dir: Path, fallback: bool) -> bool:
    """Did THIS Eval's chain skip concat? Stamp-first; `fallback` (the
    env-derived mode default) only applies to pre-stamp legacy configs.
    The one accessor for every submit-side consumer — never key this off
    the env directly (ff11R00_07 +1.5% sob bias class)."""
    chain = stamped_stage_chain(state_dir)
    if chain is not None:
        return "concat" not in chain
    return fallback


def resolve_muminus_inputs(state_dir: Path) -> tuple[list[Path], str]:
    """The mu⁻-stop count inputs for this Eval: (files, source).

    source is "concat" (MuminusStopsCat from the concat stage) or "mubeam"
    (mu⁻-pure TargetStops — concat-less chain, muminusSelector in the mubeam
    template guarantees purity). Decision order:
      1. stage-chain stamp, when present (the authoritative record);
      2. else file presence: existing concat outputs are the truth for this
         config regardless of the current env (ff11R00_07 +1.5% sob bias
         taught us never to key this off the env).
    Raises SystemExit with a diagnosable message when inputs are missing.
    """
    chain = stamped_stage_chain(state_dir)
    if chain is not None:
        use_concat = "concat" in chain
    else:
        use_concat = (state_dir / "concat_outputs.txt").exists()

    if use_concat:
        concat_files = read_outputs(state_dir, "concat")
        if not concat_files:
            raise SystemExit("No concat outputs to count mu- stops from "
                             "(blank or missing concat_outputs.txt)")
        files = [f for f in concat_files if "MuminusStopsCat" in f.name]
        if not files:
            raise SystemExit("No MuminusStopsCat in concat outputs")
        return files, "concat"

    mubeam_files = read_outputs(state_dir, "mubeam")
    if not mubeam_files:
        raise SystemExit("No mubeam outputs to count mu- stops from")
    files = [f for f in mubeam_files if "TargetStops" in f.name]
    if not files:
        raise SystemExit("No TargetStops in mubeam outputs")
    return files, "mubeam"


def events_per_job(state_dir: Path, stage: str, fallback: int) -> int:
    """SUBMIT-stamped events/job (events-per-job-mid-flight-edit incident);
    `fallback` is STAGES[stage]['events_per_job'] for pre-stamp configs."""
    stamp = state_dir / f"{stage}_events_per_job.txt"
    if stamp.exists():
        return int(stamp.read_text().strip())
    return fallback


# --- secondary (fail-soft) objectives ---------------------------------------

@dataclass
class SecondaryEdep:
    """One StrawGasStep-Edep secondary objective (trk_edep or flash)."""
    per_event: Optional[float] = None
    total_MeV: Optional[float] = None
    n_events: Optional[int] = None
    tag: Optional[str] = None
    per_file: Optional[list] = None
    n_files: int = 0
    error: Optional[str] = None  # why extraction fail-softed, for the log


def extract_secondary_edep(state_dir: Path, stage: str,
                           runner: Callable[[list[Path]], tuple],
                           ) -> Optional[SecondaryEdep]:
    """THE fail-soft wrapper for secondary objectives (one copy, not three).

    Returns None when the stage didn't run in this Eval's chain (no
    outputs.txt). Never raises: extraction failures come back as a
    SecondaryEdep carrying `error`, so harvest degrades to a metric-less
    summary exactly as before — but the policy lives in one testable place.
    `runner(files)` is pipeline.py's gallery extractor (subprocess); tests
    inject a fake.
    """
    files = read_outputs(state_dir, stage)
    if files is None:
        return None
    if not files:
        return SecondaryEdep(error=f"{stage}_outputs.txt is blank "
                                   "(stage-out-lag face?)")
    try:
        per_event, total, n_events, tag, per_file = runner(files)
    except Exception as e:  # noqa: BLE001 — fail-soft by contract
        return SecondaryEdep(n_files=len(files), error=f"{stage} edep extraction failed: {e}")
    return SecondaryEdep(per_event=per_event, total_MeV=total,
                         n_events=n_events, tag=tag,
                         per_file=list(per_file) if per_file else None,
                         n_files=len(files))


@dataclass
class SecondaryCalo:
    """The calo secondary objective (run1b_mubeam stopmat histogram sum)."""
    per_pot: Optional[float] = None
    total: Optional[float] = None
    files_seen: Optional[int] = None
    error: Optional[str] = None


def extract_secondary_calo(state_dir: Path,
                           runner: Callable[[list[Path]], tuple],
                           ) -> Optional[SecondaryCalo]:
    """Calo twin of extract_secondary_edep — same fail-soft policy, 3-tuple
    runner shape. None = stage absent from this Eval's chain."""
    files = read_outputs(state_dir, "run1b_mubeam")
    if files is None:
        return None
    if not files:
        return SecondaryCalo(error="run1b_mubeam_outputs.txt is blank "
                                   "(stage-out-lag face?)")
    try:
        per_pot_v, total, files_seen = runner(files)
    except Exception as e:  # noqa: BLE001 — fail-soft by contract
        return SecondaryCalo(error=f"calo extraction failed: {e}")
    return SecondaryCalo(per_pot=per_pot_v, total=total, files_seen=files_seen)


def per_pot(total_MeV: Optional[float], n_files: int, epj: int) -> tuple[Optional[float], Optional[int]]:
    """(metric_per_pot, n_input) from a landed-file count — the POT
    denominator convention shared by flash (and any future per-POT edep)."""
    if total_MeV is None or not n_files:
        return None, None
    n_input = n_files * epj
    if not n_input:
        return None, None
    return total_MeV / (n_input * POT_PER_ELECTRON), n_input


def winsorized_diagnostics(per_file: Optional[Sequence[float]], epj: int,
                           min_files: int = 10, trim: float = 0.05,
                           ) -> tuple[Optional[float], Optional[dict]]:
    """Per-run flash DIAGNOSTICS (not the objective): 5/95-Winsorized
    per-POT mean + per-file spread stats.

    Clips the heavy per-job tail (sd/mean 25-35%) that makes single runs
    swing ±5-11% (bo-noise-budget). Slightly biased low vs the physical mean
    (the tail is real flash), so the leaderboard objective STAYS the plain
    mean; these fields exist for run-level QA (they are exactly what the
    2026-07-09 sigma_flash split-half measurement needed).
    """
    if not per_file or len(per_file) < min_files:
        return None, None
    v = sorted(per_file)
    k = max(1, int(trim * len(v)))
    lo, hi = v[k], v[-k - 1]
    w = [min(max(x, lo), hi) for x in per_file]
    wmean = sum(w) / len(w)
    winsor_per_pot = wmean / (epj * POT_PER_ELECTRON)
    m = sum(per_file) / len(per_file)
    sd = (sum((x - m) ** 2 for x in per_file) / (len(per_file) - 1)) ** 0.5
    stats = {
        "n_files": len(per_file),
        "sd_over_mean": round(sd / m, 4) if m else None,
        "min": round(min(per_file), 6),
        "max": round(max(per_file), 6),
    }
    return winsor_per_pot, stats


# --- the Eval summary schema -------------------------------------------------

@dataclass
class EvalSummary:
    """The explicit contract behind harvest/summary.json.

    Every key the driver's extract_metrics, the graph's evaluate node, or a
    human reader may consume. Optional fields are the fail-soft secondary
    objectives — None means 'stage absent or extraction degraded', and the
    leaderboard row derived from this summary reflects that honestly.
    """
    config: str
    # primary (hard-fail) chain
    ce_seen: int
    muminus_stops: int
    mubeam_sim_total: int
    ce_simulated_events: int
    stopping_factor: float
    ce_abs_eff: float
    s_over_sqrt_b: float
    muminus_source: str  # "concat" | "mubeam" — provenance of the stop count
    # calo (fail-soft)
    calo_per_pot: Optional[float] = None
    calo_total: Optional[float] = None
    calo_files_seen: Optional[int] = None
    # flash / bo-foilsflash (fail-soft)
    flash_edep_per_event: Optional[float] = None
    flash_edep_per_pot: Optional[float] = None
    flash_edep_per_pot_winsor: Optional[float] = None  # diagnostic, NOT objective
    flash_perfile_stats: Optional[dict] = None          # diagnostic
    flash_edep_total_MeV: Optional[float] = None
    flash_edep_events: Optional[int] = None
    flash_n_input: Optional[int] = None
    flash_edep_tag: Optional[str] = None
    # local-executor provenance: basenames of FCLs hand-edited before the run.
    # None on every grid row; a list (possibly empty) on a local one.
    fcl_edited: Optional[list] = None
    # artifact pointers
    nts_path: str = ""
    edep_log: str = ""
    macro_log: str = ""
    # degradation record: stage -> reason, for every fail-softed extraction
    degraded: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def write(self, harvest_dir: Path) -> Path:
        out = harvest_dir / "summary.json"
        out.write_text(self.to_json())
        return out
