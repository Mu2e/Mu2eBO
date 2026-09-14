"""Eval-summary module: the schema and pure logic behind `pipeline.py harvest`.

Everything decidable without grid/muse/subprocess lives here; pipeline.py
passes its subprocess extractors IN as callables (every branch unit-testable).
An **Eval summary** (CONTEXT.md) = harvest/summary.json; the leaderboard row
derives from it. Invariant: every input set is resolved from the Eval's own
state dir (its <stage>_outputs.txt), NEVER the process env.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

# --- physics/parse constants -------------------------------------------------

RUN1A_MUBEAM_INPUT_CORRECTION = 0.01278168
POT_PER_ELECTRON = 25_000_000 / 2_166_994  # EleBeamCat dh.gencount / event_count

# EdepAna prints the count via %g: >1M events arrive as "2.70937e+06"
# (incident: edepana-saw-events-scientific-notation-parse).
EDEP_SAW_RX = re.compile(r"EdepAna summary:\s*Saw\s+([\d.eE+-]+)\s+events")
S_OVER_SQRTB_RX = re.compile(
    r"^Signal box.*S/sqrt\(B\)\s*=\s*([\d.eE+-]+)\s*$", re.MULTILINE)


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
# (runner(cmd, cwd) is a proc-like the CALLER binds env for.)

# Run1BAna (github.com/michaelmackenzie/Run1BAna) is an ARTIFACT (gitignored),
# resolved via artifact()/backing — REPO_ROOT resolution died on fresh clones.
# MUSE_WORKAREA anchoring keeps the #include honest (FHICL_FILE_PATH).
from paths import artifact  # see core/paths.py

MUSE_WORKAREA = artifact("autoresearch_muse")
EDEP_FCL = MUSE_WORKAREA / "Run1BAna/workflows/fcl/edep.fcl"
SENSITIVITY_MACRO = (MUSE_WORKAREA /
                     "Run1BAna/workflows/scripts/rough_run1a_sensitivity.C")

# Checked by paths.verify() at preflight — a missing backing fails in the
# first minute, not after the last stage. Every mode's harvest needs both.
REQUIRED_ARTIFACTS = (
    (EDEP_FCL, "EdepAna FCL (Run1BAna)"),
    (SENSITIVITY_MACRO, "sensitivity macro (Run1BAna)"),
)


def run_edepana(harvest_dir: Path, ce_files: Sequence[Path], *, runner):
    """Harvest Step 1: EdepAna over the CeEndpoint art files -> (ce_seen, nts_path).

    HARD-fail (SystemExit) on rc != 0 or an unparseable 'Saw N events' line
    — this is the sob numerator, never fail-soft.
    """
    ce_list = harvest_dir / "ce_files.txt"
    ce_list.write_text("\n".join(str(p) for p in ce_files) + "\n")
    nts_path = harvest_dir / "nts.ce.root"
    wrapper = harvest_dir / "edep_wrapper.fcl"
    wrapper.write_text(
        f'#include "{EDEP_FCL.relative_to(MUSE_WORKAREA).as_posix()}"\n'
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
    """Harvest Step 4: rough_run1a_sensitivity.C -> S/sqrt(B); HARD-fail on
    rc != 0 / unparseable output. cwd is the Run1BAna workflows dir (macro
    path is workflows-relative)."""
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


def read_outputs(state_dir: Path, stage: str) -> Optional[list[Path]]:
    """Non-blank lines of state/<stage>_outputs.txt, or None if absent.

    A present-but-blank file (stage-out-lag face) returns [] — callers must
    treat that as a hard error for primary inputs, not as 'stage absent'.
    """
    p = state_dir / f"{stage}_outputs.txt"
    if not p.exists():
        return None
    return [Path(ln) for ln in p.read_text().splitlines() if ln.strip()]


def resolve_muminus_inputs(state_dir: Path) -> list[Path]:
    """The mu⁻-stop count inputs for this Eval: mubeam's mu⁻-pure
    TargetStops (muminusSelector guarantees purity). SystemExit when inputs
    are missing."""
    mubeam_files = read_outputs(state_dir, "mubeam")
    if not mubeam_files:
        raise SystemExit("No mubeam outputs to count mu- stops from")
    files = [f for f in mubeam_files if "TargetStops" in f.name]
    if not files:
        raise SystemExit("No TargetStops in mubeam outputs")
    return files


def events_per_job(state_dir: Path, stage: str, fallback: int) -> int:
    """SUBMIT-stamped events/job (see
    wiki/incidents/events-per-job-mid-flight-edit.md); `fallback` is
    pipeline.stage_cfg(stage, MODE)['events'] for pre-stamp configs."""
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

    None = stage absent from this Eval's chain (no outputs.txt). Never
    raises: failures come back as SecondaryEdep.error, so harvest degrades
    to a metric-less summary.
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



def per_pot(total_MeV: Optional[float], n_files: int, epj: int) -> tuple[Optional[float], Optional[int]]:
    """(metric_per_pot, n_input) from a landed-file count — the shared
    per-POT denominator convention."""
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

    Clips the heavy per-job tail (sd/mean 25-35%, single-run swing ±5-11% —
    bo-noise-budget). Biased slightly low (the tail is real flash), so the
    leaderboard objective STAYS the plain mean.
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

    Optional fields are fail-soft secondary objectives — None means 'stage
    absent or extraction degraded'.
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
    # flash / bo-foilsflash (fail-soft)
    flash_edep_per_event: Optional[float] = None
    flash_edep_per_pot: Optional[float] = None
    flash_edep_per_pot_winsor: Optional[float] = None  # diagnostic, NOT objective
    flash_perfile_stats: Optional[dict] = None          # diagnostic
    flash_edep_total_MeV: Optional[float] = None
    flash_edep_events: Optional[int] = None
    flash_n_input: Optional[int] = None
    flash_edep_tag: Optional[str] = None
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
