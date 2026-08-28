"""Eval-summary module: the schema behind `pipeline.py harvest`.

An **Eval summary** (CONTEXT.md) = harvest/summary.json; the leaderboard row
derives from it. The generic harvest orchestrator (core/extractors.py) populates
the `fields` dict from mode_spec-declared extractors and derived expressions.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


def read_outputs(state_dir: Path, stage: str) -> Optional[list[Path]]:
    """Non-blank lines of state/<stage>_outputs.txt, or None if absent.

    A present-but-blank file (stage-out-lag face) returns [] — callers must
    treat that as a hard error for primary inputs, not as 'stage absent'.
    """
    p = state_dir / f"{stage}_outputs.txt"
    if not p.exists():
        return None
    return [Path(ln) for ln in p.read_text().splitlines() if ln.strip()]


def events_per_job(state_dir: Path, stage: str, fallback: int) -> int:
    """SUBMIT-stamped events/job (see
    wiki/incidents/events-per-job-mid-flight-edit.md); `fallback` is
    pipeline.stage_cfg(stage, MODE)['events'] for pre-stamp configs."""
    stamp = state_dir / f"{stage}_events_per_job.txt"
    if stamp.exists():
        return int(stamp.read_text().strip())
    return fallback


# --- the Eval summary schema -------------------------------------------------

@dataclass
class EvalSummary:
    """The contract behind harvest/summary.json.

    The `fields` dict holds all metric values produced by the generic harvest
    extractors and derived-field expressions. `to_json()` flattens `fields`
    into the top-level dict so that downstream consumers (extract_metrics,
    evaluate node, leaderboard) can read summary.json by key name.
    """
    config: str
    fields: dict = field(default_factory=dict)
    degraded: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        # Flatten: fields values available at top level for extract_metrics
        for k, v in d.get("fields", {}).items():
            if k not in d:
                d[k] = v
        return json.dumps(d, indent=2)

    def write(self, harvest_dir: Path) -> Path:
        out = harvest_dir / "summary.json"
        out.write_text(self.to_json())
        return out

    @classmethod
    def from_fields(cls, config: str, fields: dict) -> "EvalSummary":
        """Build an EvalSummary from a generic fields dict."""
        degraded = fields.pop("degraded", {})
        return cls(config=config, fields=dict(fields), degraded=degraded)
