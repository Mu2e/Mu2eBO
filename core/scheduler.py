"""run_steps: the one per-point node that runs a study's steps
(generic-study design, "One point, end to end", step 4).

A step starts as soon as every step in its files_from has completed, and
ready steps run concurrently in threads, so a slow independent step never
holds back a dependent chain. One LangGraph node per step would: LangGraph
finishes a whole superstep before starting the next, which is the wait
today's presubmit_after works around.

Each step works from its state files, which is what makes a killed child
resumable with no second submit:
  state/<step>_results.json  done: adopt the record, skip the step
  state/<step>_cluster.txt   submitted: poll that handle
  neither                    submit, then write the handle
A failed or cancelled step, a kit error, or a reply outside the contract
stops new launches; running steps finish; broken.txt names the first step
that failed. A failed step is never retried.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

if __package__:
    from core.contract import ContractError
    from core.kits import KitError
else:
    from contract import ContractError
    from kits import KitError


@dataclass(frozen=True)
class StepOutcome:
    step: str
    ok: bool
    message: str
    record: Optional[Dict[str, Any]]    # the <step>_results.json content


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def map_params(mapping: Dict[str, str], env: Dict[str, Any],
               accepts_lists: bool) -> Dict[str, Any]:
    """Kit param name -> the value of the knob, const, expr or profile it
    names. A profile goes to a kit that takes no lists flattened as
    <param>_0 ... <param>_{N-1}."""
    out: Dict[str, Any] = {}
    for key, name in mapping.items():
        value = env[name]
        if isinstance(value, list) and not accepts_lists:
            out.update({f"{key}_{i}": v for i, v in enumerate(value)})
        else:
            out[key] = list(value) if isinstance(value, list) else value
    return out


def step_params(study, step, env, accepts_lists) -> Dict[str, Any]:
    """The mapped params, then the study's settings for the step's kit, then
    the step's fixed values, which win over the settings. A mapped param may
    not share a name with a setting or a fixed value."""
    mapped = map_params(step.params, env, accepts_lists)
    constant = {**study.kits.get(step.kit, {}), **step.fixed}
    clash = sorted(set(mapped) & set(constant))
    if clash:
        raise ValueError(f"step {step.step!r}: param(s) {clash} are both "
                         f"mapped from the point and set in kits/fixed")
    return {**mapped, **constant}


def run_steps(study, *, config: str, state_dir: Path, env, files, kits,
              workflow: Callable[[str], str], sleep=time.sleep,
              log=print) -> Dict[str, StepOutcome]:
    state_dir.mkdir(parents=True, exist_ok=True)
    outcomes: Dict[str, StepOutcome] = {}
    for s in study.steps:
        path = state_dir / f"{s.step}_results.json"
        if path.exists():
            outcomes[s.step] = StepOutcome(s.step, True, "adopted",
                                           json.loads(path.read_text()))
            log(f"[steps] {s.step}: adopted {path.name}")
    pending = [s for s in study.steps if s.step not in outcomes]
    failed: Optional[StepOutcome] = None
    with ThreadPoolExecutor(max_workers=max(1, len(pending))) as pool:
        running = {}
        while True:
            if failed is None:
                for s in list(pending):
                    if all(d in outcomes and outcomes[d].ok
                           for d in s.files_from):
                        pending.remove(s)
                        upstream = {d: outcomes[d].record for d in s.files_from}
                        fut = pool.submit(_run_one, study, s, config,
                                          state_dir, env, files, kits,
                                          upstream, workflow(s.step), sleep,
                                          log)
                        running[fut] = s.step
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                name = running.pop(fut)
                out = fut.result()      # _run_one reports errors as outcomes
                outcomes[name] = out
                log(f"[steps] {name}: "
                    f"{'completed' if out.ok else 'FAILED: ' + out.message}")
                if not out.ok and failed is None:
                    failed = out
    if failed is not None:
        write_atomic(state_dir / "broken.txt",
                     f"step {failed.step}: {failed.message}\n")
    return outcomes


def _run_one(study, step, config, state_dir, env, files, kits, upstream,
             workflow, sleep, log) -> StepOutcome:
    try:
        kit = kits.get(step.kit)
        params = step_params(study, step, env, kit.accepts_lists)
        step_files = [files[f] for f in step.files]
        inputs = [ref for up in step.files_from for ref in upstream[up]["files"]]
        handle_path = state_dir / f"{step.step}_cluster.txt"
        if handle_path.exists():
            handle = handle_path.read_text().strip()
            log(f"[steps] {step.step}: polling {handle} (submitted by an "
                f"earlier run)")
        else:
            handle = kit.submit(f"{config}.{step.step}", params, step_files,
                                inputs, workflow)
            write_atomic(handle_path, handle + "\n")
            log(f"[steps] {step.step}: submitted {handle}")
        lo, hi = kit.poll_s
        while True:
            status = kit.status(handle, workflow)
            if status.state == "completed":
                break
            if status.state in ("failed", "cancelled"):
                return StepOutcome(step.step, False,
                                   f"{status.state}: {status.message}", None)
            sleep(min(max(status.poll_ms / 1000.0, lo), hi))
        res = kit.results(handle, workflow)
        record = {"step": step.step, "kit": step.kit,
                  "kit_version": kit.version, "handle": handle,
                  "params": params, "inputs": inputs,
                  "metrics": res.metrics, "files": list(res.files),
                  "metadata": res.metadata}
        write_atomic(state_dir / f"{step.step}_results.json",
                     json.dumps(record, indent=1, sort_keys=True))
        return StepOutcome(step.step, True, "completed", record)
    except (KitError, ContractError, KeyError, ValueError) as exc:
        return StepOutcome(step.step, False, f"{type(exc).__name__}: {exc}",
                           None)
