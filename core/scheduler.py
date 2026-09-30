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
stops new launches and cancels the running steps whose kit offers `cancel`
(the others finish); broken.txt names the first step that failed, written
the moment that failure is known (not after the other steps drain). A
failed step is never retried. An exception outside those (a bug -- e.g. an
OSError from write_atomic) is logged and recorded the same way, then
re-raised once every already-running step has finished, so a programming
error still crashes loudly instead of hanging silently.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

if __package__:
    from core import kit_registry
    from core.contract import ContractError
    from core.kits import KitError
    from core.study import expand_artifact
else:
    import kit_registry
    from contract import ContractError
    from kits import KitError
    from study import expand_artifact


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


def merge_params(owner: str, mapped: Dict[str, Any],
                 constant: Dict[str, Any]) -> Dict[str, Any]:
    """The mapped params plus the constant ones (kit settings, a step's
    fixed values). The one clash rule for a step and the preflight: a mapped
    param may not share a name with a constant one, which would silently
    replace the point's value."""
    clash = sorted(set(mapped) & set(constant))
    if clash:
        raise ValueError(f"{owner}: param(s) {clash} are both mapped from the "
                         f"point and set in kits/fixed; a mapped param may "
                         f"not share a name with a kit setting or a fixed "
                         f"value")
    return {**mapped, **constant}


def step_params(study, step, env, accepts_lists) -> Dict[str, Any]:
    """The mapped params, then the study's settings for the step's kit, then
    the step's fixed values, which win over the settings. A mapped param may
    not share a name with a setting or a fixed value. A kit that takes stage
    templates also gets the step's resolved template as `entry`. A fixed
    '${ARTIFACT}/' value is expanded here (the study keeps it raw)."""
    fixed = {k: expand_artifact(v, f"step {step.step!r} fixed[{k}]")
             for k, v in step.fixed.items()}
    params = merge_params(f"step {step.step!r}",
                          map_params(step.params, env, accepts_lists),
                          {**study.kits.get(step.kit, {}), **fixed})
    decl = kit_registry.KITS.get(step.kit)
    if decl is not None and decl.uses_entries:
        if "entry" in params:
            raise ValueError(f"step {step.step!r}: 'entry' is reserved for "
                             f"kit {step.kit!r}, which receives the step's "
                             f"stage template under that name")
        params["entry"] = study.entry_template(step.step)
    return params


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
    crash: Optional[Exception] = None
    stop = threading.Event()
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
                                          log, stop)
                        running[fut] = s.step
            if not running:
                break
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in done:
                name = running.pop(fut)
                try:
                    # _run_one reports every contract/kit failure as a
                    # StepOutcome; anything else raised here is a bug in the
                    # step itself (e.g. an OSError from write_atomic), not a
                    # reported evaluation failure.
                    out = fut.result()
                except Exception as exc:
                    out = StepOutcome(name, False,
                                      f"{type(exc).__name__}: {exc}", None)
                    if crash is None:
                        crash = exc
                outcomes[name] = out
                log(f"[steps] {name}: "
                    f"{'completed' if out.ok else 'FAILED: ' + out.message}")
                if not out.ok and failed is None:
                    failed = out
                    write_atomic(state_dir / "broken.txt",
                                 f"step {failed.step}: {failed.message}\n")
                    stop.set()
                    _cancel_running(study, set(running.values()), state_dir,
                                    kits, workflow, log)
    if crash is not None:
        raise crash
    return outcomes


def _cancel_one(kit, step, handle, workflow, log) -> None:
    """A KitError/ContractError from the tools check or the cancel call
    itself (e.g. a NativeKit whose MCP server died and cannot respawn) is
    logged the same way as a refused cancel: the step runs to completion.
    Anything else (a kit missing `tools` entirely) is a bug and is not
    caught here."""
    try:
        if "cancel" not in kit.tools:
            log(f"[steps] {step.step}: kit {step.kit} cannot cancel; it "
                f"runs to completion")
            return
        state = kit.cancel(handle, workflow)
        log(f"[steps] {step.step}: cancel requested ({state})")
    except (KitError, ContractError) as exc:
        log(f"[steps] {step.step}: cancel failed ({exc}); it runs to "
            f"completion")


def _cancel_running(study, names, state_dir, kits, workflow, log) -> None:
    """Cancel each running step that has submitted. One that has not yet
    will see the stop event and never submit. A kit that cannot even be
    opened/fetched (KitError/ContractError, e.g. a lost server) is logged
    the same way; it does not stop the other names in `names` from being
    cancelled."""
    by_name = {s.step: s for s in study.steps}
    for name in sorted(names):
        handle_path = state_dir / f"{name}_cluster.txt"
        if not handle_path.exists():
            continue
        s = by_name[name]
        try:
            kit = kits.get(s.kit)
        except (KitError, ContractError) as exc:
            log(f"[steps] {name}: cancel failed ({exc}); it runs to "
                f"completion")
            continue
        _cancel_one(kit, s, handle_path.read_text().strip(),
                    workflow(name), log)


def _run_one(study, step, config, state_dir, env, files, kits, upstream,
             workflow, sleep, log, stop) -> StepOutcome:
    """Run one step: submit (or resume the handle an earlier run wrote), poll
    to a terminal state, read the results. Two kinds of failure become a
    failed StepOutcome: a kit failure (KitError or ContractError, which
    KitSet.get guarantees is all a kit raises) and an engine-side lookup or
    parameter error (KeyError, ValueError) while preparing the step. The
    handle-file read and write are not caught: an OSError there is a bug."""
    def failed(exc):
        return StepOutcome(step.step, False, f"{type(exc).__name__}: {exc}",
                           None)

    try:
        kit = kits.get(step.kit)
        accepts_lists = kit.accepts_lists
    except (KitError, ContractError) as exc:
        return failed(exc)
    try:
        params = step_params(study, step, env, accepts_lists)
        step_files = [files[f] for f in step.files]
        inputs = [ref for up in step.files_from for ref in upstream[up]["files"]]
    except (KeyError, ValueError) as exc:
        return failed(exc)
    handle_path = state_dir / f"{step.step}_cluster.txt"
    if handle_path.exists():
        handle = handle_path.read_text().strip()
        log(f"[steps] {step.step}: polling {handle} (submitted by an "
            f"earlier run)")
    else:
        if stop.is_set():
            return StepOutcome(step.step, False, "cancelled: not "
                               "submitted, another step failed first", None)
        try:
            handle = kit.submit(f"{config}.{step.step}", params, step_files,
                                inputs, workflow)
        except (KitError, ContractError) as exc:
            return failed(exc)
        write_atomic(handle_path, handle + "\n")
        log(f"[steps] {step.step}: submitted {handle}")
        if stop.is_set():   # a step failed while this one submitted
            _cancel_one(kit, step, handle, workflow, log)
    try:
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
        kit_version = kit.version
    except (KitError, ContractError) as exc:
        return failed(exc)
    record = {"step": step.step, "kit": step.kit,
              "kit_version": kit_version, "handle": handle,
              "params": params, "inputs": inputs,
              "metrics": res.metrics, "files": list(res.files),
              "metadata": res.metadata}
    write_atomic(state_dir / f"{step.step}_results.json",
                 json.dumps(record, indent=1, sort_keys=True))
    return StepOutcome(step.step, True, "completed", record)
