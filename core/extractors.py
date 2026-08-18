"""Generic harvest extractors driven by mode_specs harvest config.

Each extractor type implements a standard interface: given stage output
files and a muse env, extract one or more metric fields. Results are
collected into a flat dict that the derived-field evaluator can reference.

Extractor types:
  - mu2e_module: run `mu2e -c <fcl> -S <files>`, parse stdout
  - root_macro:  run `root -q -b -l '<script>(<args>)'`, parse stdout
  - gallery:     run gallery StrawGasStep/collection extractor
  - event_count: count art events in stage output files
  - histogram:   read ROOT histogram bins
  - script:      run an arbitrary user script, parse JSON output

STDLIB ONLY for the module itself; subprocess calls use the caller's env.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

if __package__:
    from core.modes import HarvestConfig, HarvestExtractor
else:
    from modes import HarvestConfig, HarvestExtractor


# ---------------------------------------------------------------------------
# Safe expression evaluator (reuses geom_template.py's AST-whitelist approach)
# ---------------------------------------------------------------------------

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "int": int,
    "float": float,
}


def _safe_eval_expr(expr_str: str, ns: dict) -> Any:
    """Evaluate a simple arithmetic expression with named variables.

    Only allows: numbers, variable names from `ns`, basic arithmetic,
    and whitelisted functions. No attribute access, no subscripts beyond
    simple indexing, no imports.
    """
    tree = ast.parse(expr_str, mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"unsupported constant: {node.value!r}")
        if isinstance(node, ast.Name):
            if node.id in ns:
                return ns[node.id]
            if node.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.id]
            raise NameError(f"undefined variable: {node.id!r}")
        if isinstance(node, ast.BinOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported operator: {type(node.op).__name__}")
            return op_fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _SAFE_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"unsupported unary: {type(node.op).__name__}")
            return op_fn(_eval(node.operand))
        if isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(a) for a in node.args]
            if callable(func):
                return func(*args)
            raise ValueError(f"not callable: {func!r}")
        if isinstance(node, ast.IfExp):
            return _eval(node.body) if _eval(node.test) else _eval(node.orelse)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                if isinstance(op, ast.Gt):
                    result = left > right
                elif isinstance(op, ast.Lt):
                    result = left < right
                elif isinstance(op, ast.GtE):
                    result = left >= right
                elif isinstance(op, ast.LtE):
                    result = left <= right
                elif isinstance(op, ast.Eq):
                    result = left == right
                elif isinstance(op, ast.NotEq):
                    result = left != right
                else:
                    raise ValueError(f"unsupported comparison: {type(op).__name__}")
                if not result:
                    return False
                left = right
            return True
        raise ValueError(f"unsupported AST node: {type(node).__name__}")

    return _eval(tree)


# ---------------------------------------------------------------------------
# Extractor runners
# ---------------------------------------------------------------------------

def _read_stage_outputs(state_dir: Path, stage: str) -> Optional[List[Path]]:
    """Read state/<stage>_outputs.txt, return list of Paths or None."""
    p = state_dir / f"{stage}_outputs.txt"
    if not p.exists():
        return None
    return [Path(ln) for ln in p.read_text().splitlines() if ln.strip()]


def _events_per_job_stamped(state_dir: Path, stage: str, default: int) -> int:
    """Read the submit-stamped events_per_job for a stage."""
    stamp = state_dir / f"{stage}_events_per_job.txt"
    if stamp.exists():
        return int(stamp.read_text().strip())
    return default


def run_mu2e_module(ext: HarvestExtractor, files: List[Path],
                    harvest_dir: Path, env: dict,
                    fhicl_extra_path: str = "") -> dict:
    """Run a mu2e art module on stage output files.

    Returns dict of parsed fields from stdout.
    """
    if not files:
        raise RuntimeError(f"mu2e_module extractor {ext.name}: no input files")
    file_list = harvest_dir / f"{ext.name}_files.txt"
    file_list.write_text("\n".join(str(p) for p in files) + "\n")
    output_name = ext.output or f"nts.{ext.name}.root"
    nts_path = harvest_dir / output_name
    wrapper = harvest_dir / f"{ext.name}_wrapper.fcl"
    wrapper.write_text(
        f'#include "{ext.fcl}"\n'
        f'services.TFileService.fileName: "{nts_path.name}"\n'
    )
    log_path = harvest_dir / f"{ext.name}.log"
    fhicl_env = dict(env)
    if fhicl_extra_path:
        fhicl_env["FHICL_FILE_PATH"] = (
            f"{fhicl_extra_path}:{fhicl_env.get('FHICL_FILE_PATH', '')}")
    proc = subprocess.run(
        ["mu2e", "-c", str(wrapper), "-S", str(file_list)],
        cwd=str(harvest_dir), env=fhicl_env,
        capture_output=True, text=True, check=False)
    log_path.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"mu2e_module {ext.name} failed (rc={proc.returncode}); see {log_path}")
    result = {"_nts_path": str(nts_path), "_log": str(log_path)}
    if ext.parse_pattern and ext.parse_field:
        m = re.search(ext.parse_pattern, proc.stdout)
        if not m:
            raise RuntimeError(
                f"mu2e_module {ext.name}: pattern {ext.parse_pattern!r} not found; "
                f"see {log_path}")
        val = m.group(1)
        if ext.parse_type == "int":
            val = int(float(val))
        else:
            val = float(val)
        result[ext.parse_field] = val
    return result


def run_root_macro(ext: HarvestExtractor, harvest_dir: Path, env: dict,
                   ns: dict) -> dict:
    """Run a ROOT macro and parse output."""
    if not ext.script:
        raise RuntimeError(f"root_macro extractor {ext.name}: no script specified")
    log_path = harvest_dir / f"{ext.name}.log"
    # Substitute {field} references in args
    args_str = []
    for arg in (ext.args or ()):
        try:
            args_str.append(arg.format(**ns))
        except KeyError:
            args_str.append(arg)
    macro_call = f'{ext.script}({", ".join(args_str)})'
    cwd = Path(ext.script).parent.parent if "/" in (ext.script or "") else harvest_dir
    proc = subprocess.run(
        ["root", "-q", "-b", "-l", macro_call],
        cwd=str(cwd), env=env,
        capture_output=True, text=True, check=False)
    log_path.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"root_macro {ext.name} failed (rc={proc.returncode}); see {log_path}")
    result = {"_log": str(log_path)}
    if ext.parse_pattern and ext.parse_field:
        m = re.search(ext.parse_pattern, proc.stdout, re.MULTILINE)
        if not m:
            raise RuntimeError(
                f"root_macro {ext.name}: pattern {ext.parse_pattern!r} not found; "
                f"see {log_path}")
        val = m.group(1)
        result[ext.parse_field] = float(val) if ext.parse_type != "int" else int(float(val))
    return result


# Gallery StrawGasStep extractor script (generalized from pipeline.py)
_GALLERY_EXTRACT_SCRIPT = r"""
import json, sys
import ROOT
ROOT.gSystem.Load("libgallery")
data = json.loads(sys.stdin.read())
files, tags, collection, quantity = data["files"], data["tags"], data["collection"], data["quantity"]
total = 0.0; n_events = 0; used = ""; per_file = []
for path in files:
    fv = ROOT.vector("string")()
    fv.push_back(path)
    try:
        ev = ROOT.gallery.Event(fv)
        getH = ev.getValidHandle[ROOT.std.vector(collection)]
    except Exception as e:
        print("EXTRACT_RESULT " + json.dumps({"error": "gallery init (%s): %s" % (path, e)})); sys.exit(0)
    cand = list(zip(tags, [ROOT.art.InputTag(t) for t in tags]))
    ftot = 0.0; fn = 0
    while not ev.atEnd():
        prod = None
        trylist = [(used, ROOT.art.InputTag(used))] if used else cand
        for tname, it in trylist:
            try:
                prod = getH(it).product(); used = tname; break
            except Exception:
                continue
        if prod is not None:
            for s in prod:
                try:
                    ftot += getattr(s, quantity)()
                except Exception:
                    pass
        fn += 1
        ev.next()
    per_file.append(ftot)
    total += ftot; n_events += fn
print("EXTRACT_RESULT " + json.dumps({"total": total, "n_events": n_events, "tag": used, "per_file": per_file}))
"""


def run_gallery(ext: HarvestExtractor, files: List[Path], env: dict) -> dict:
    """Run gallery collection extractor on stage output files."""
    if not files:
        return {"_error": f"gallery {ext.name}: no input files"}
    collection = ext.collection or "mu2e::StrawGasStep"
    quantity = ext.quantity or "ionizingEdep"
    tags = list(ext.tags or ("compressDetStepMCs",))
    proc = subprocess.run(
        ["python3", "-c", _GALLERY_EXTRACT_SCRIPT],
        input=json.dumps({
            "files": [str(p) for p in files],
            "tags": tags,
            "collection": collection,
            "quantity": quantity,
        }),
        env=env, capture_output=True, text=True, check=True)
    marker = [ln for ln in proc.stdout.splitlines() if ln.startswith("EXTRACT_RESULT ")]
    if not marker:
        raise RuntimeError(f"gallery {ext.name}: no EXTRACT_RESULT line in output")
    result_data = json.loads(marker[-1][len("EXTRACT_RESULT "):])
    if "error" in result_data:
        raise RuntimeError(result_data["error"])
    return {
        f"{ext.name}_total": result_data["total"],
        f"{ext.name}_n_events": result_data["n_events"],
        f"{ext.name}_tag": result_data.get("tag"),
        f"{ext.name}_per_file": result_data.get("per_file"),
        f"{ext.name}_n_files": len(files),
        f"{ext.name}_per_event": (result_data["total"] / result_data["n_events"]
                                  if result_data["n_events"] else None),
    }


def run_event_count(ext: HarvestExtractor, files: List[Path],
                    harvest_dir: Path, env: dict) -> dict:
    """Count events in art files, optionally filtering by name substring."""
    if not files:
        return {ext.parse_field or f"{ext.name}_count": 0}
    filtered = files
    if ext.count_filter:
        filtered = [f for f in files if ext.count_filter in f.name]
    total = 0
    fcl = harvest_dir / f"count_{ext.name}.fcl"
    fcl.write_text(
        '#include "Offline/fcl/minimalMessageService.fcl"\n'
        "process_name: count\n"
        "source: { module_type: RootInput }\n"
        "services: { message: @local::default_message }\n"
        "physics: {}\n"
    )
    for f in filtered:
        log = harvest_dir / f"count_{ext.name}_{f.stem}.log"
        proc = subprocess.run(
            ["mu2e", "-c", str(fcl), "-s", str(f), "-n", "-1"],
            cwd=str(harvest_dir), env=env,
            capture_output=True, text=True, check=True)
        log.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
        m = re.search(r"TrigReport Events total =\s*(\d+)", proc.stdout)
        if m:
            total += int(m.group(1))
    field_name = ext.parse_field or f"{ext.name}_count"
    return {field_name: total}


_HISTOGRAM_SCRIPT = r"""
import json, sys
data = json.loads(sys.stdin.read())
import ROOT
files, hist_path, bin_labels = data["files"], data["hist_path"], data["bin_labels"]
labels_set = set(bin_labels) if bin_labels else None
total = 0.0; files_seen = 0
for path in files:
    tfile = ROOT.TFile.Open(path, "READ")
    if not tfile or tfile.IsZombie():
        continue
    hist = tfile.Get(hist_path)
    if not hist:
        tfile.Close()
        continue
    files_seen += 1
    if labels_set:
        xaxis = hist.GetXaxis()
        for b in range(1, xaxis.GetNbins() + 1):
            if xaxis.GetBinLabel(b) in labels_set:
                total += float(hist.GetBinContent(b))
    else:
        total += hist.Integral()
    tfile.Close()
print(json.dumps({"total": total, "files_seen": files_seen}))
"""


def run_histogram(ext: HarvestExtractor, files: List[Path], env: dict) -> dict:
    """Read ROOT histogram bins from stage output files."""
    if not files:
        return {f"{ext.name}_total": 0.0, f"{ext.name}_files_seen": 0}
    proc = subprocess.run(
        ["python3", "-c", _HISTOGRAM_SCRIPT],
        input=json.dumps({
            "files": [str(p) for p in files],
            "hist_path": ext.histogram_path or "",
            "bin_labels": list(ext.bin_labels) if ext.bin_labels else None,
        }),
        env=env, capture_output=True, text=True, check=True)
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    return {
        f"{ext.name}_total": result["total"],
        f"{ext.name}_files_seen": result["files_seen"],
    }


def run_script(ext: HarvestExtractor, files: List[Path],
               harvest_dir: Path, env: dict, ns: dict) -> dict:
    """Run an arbitrary user script and parse JSON output."""
    if not ext.command:
        raise RuntimeError(f"script extractor {ext.name}: no command specified")
    cmd = list(ext.command)
    log_path = harvest_dir / f"{ext.name}.log"
    input_data = json.dumps({
        "files": [str(p) for p in (files or [])],
        "fields": dict(ns),
    })
    proc = subprocess.run(
        cmd, input=input_data, cwd=str(harvest_dir), env=env,
        capture_output=True, text=True, check=False)
    log_path.write_text(proc.stdout + "\n=== STDERR ===\n" + proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(
            f"script {ext.name} failed (rc={proc.returncode}); see {log_path}")
    result = {}
    if ext.parse_json:
        try:
            parsed = json.loads(proc.stdout.strip().splitlines()[-1])
            if ext.fields:
                for field in ext.fields:
                    if field in parsed:
                        result[field] = parsed[field]
            else:
                result.update(parsed)
        except (json.JSONDecodeError, IndexError) as e:
            raise RuntimeError(
                f"script {ext.name}: could not parse JSON output: {e}; "
                f"see {log_path}")
    elif ext.parse_pattern and ext.parse_field:
        m = re.search(ext.parse_pattern, proc.stdout, re.MULTILINE)
        if m:
            val = m.group(1)
            result[ext.parse_field] = float(val) if ext.parse_type != "int" else int(float(val))
    return result


# ---------------------------------------------------------------------------
# Orchestrator: run all extractors + evaluate derived fields
# ---------------------------------------------------------------------------

_EXTRACTOR_RUNNERS = {
    "mu2e_module": "mu2e_module",
    "root_macro": "root_macro",
    "gallery": "gallery",
    "event_count": "event_count",
    "histogram": "histogram",
    "script": "script",
}


def run_harvest_config(config: HarvestConfig, state_dir: Path,
                       harvest_dir: Path, env: dict,
                       stage_defs: dict,
                       fhicl_extra_path: str = "") -> dict:
    """Run all extractors in a HarvestConfig, evaluate derived fields,
    and return the full summary dict.

    `stage_defs` is {name: StageDef} for events_per_job resolution.
    """
    harvest_dir.mkdir(parents=True, exist_ok=True)
    fields: Dict[str, Any] = {}
    degraded: Dict[str, str] = {}

    # Built-in helper functions available in derived expressions
    def count_files(stage: str) -> int:
        outputs = _read_stage_outputs(state_dir, stage)
        return len(outputs) if outputs else 0

    def events_per_job(stage: str) -> int:
        sdef = stage_defs.get(stage)
        default_epj = sdef.events_per_job if sdef else 5000
        return _events_per_job_stamped(state_dir, stage, default_epj)

    # Run each extractor
    for ext in config.extractors:
        try:
            # Get stage outputs if needed
            files = None
            if ext.stage:
                files = _read_stage_outputs(state_dir, ext.stage)
                if files is None:
                    if ext.fail_soft:
                        degraded[ext.name] = f"stage {ext.stage} has no outputs"
                        continue
                    raise RuntimeError(
                        f"extractor {ext.name}: stage {ext.stage} has no outputs")
                if not files:
                    if ext.fail_soft:
                        degraded[ext.name] = f"stage {ext.stage} outputs empty"
                        continue
                    raise RuntimeError(
                        f"extractor {ext.name}: stage {ext.stage} outputs empty")

            if ext.type == "mu2e_module":
                result = run_mu2e_module(ext, files or [], harvest_dir, env,
                                         fhicl_extra_path)
            elif ext.type == "root_macro":
                result = run_root_macro(ext, harvest_dir, env, fields)
            elif ext.type == "gallery":
                result = run_gallery(ext, files or [], env)
            elif ext.type == "event_count":
                result = run_event_count(ext, files or [], harvest_dir, env)
            elif ext.type == "histogram":
                result = run_histogram(ext, files or [], env)
            elif ext.type == "script":
                result = run_script(ext, files or [], harvest_dir, env, fields)
            else:
                raise RuntimeError(f"unknown extractor type: {ext.type!r}")

            fields.update(result)

        except Exception as exc:
            if ext.fail_soft:
                degraded[ext.name] = str(exc)
                print(f"    [{ext.name}] WARN (fail-soft): {exc}")
            else:
                raise

    # Evaluate derived fields
    # Build namespace with fields + helper functions
    eval_ns = dict(fields)
    eval_ns["count_files"] = count_files
    eval_ns["events_per_job"] = events_per_job
    eval_ns["sqrt"] = math.sqrt
    eval_ns["log"] = math.log
    eval_ns["abs"] = abs
    eval_ns["min"] = min
    eval_ns["max"] = max

    for field_name, expr in config.derived.items():
        try:
            fields[field_name] = _safe_eval_expr(expr, eval_ns)
            eval_ns[field_name] = fields[field_name]
        except Exception as exc:
            print(f"    [{field_name}] WARN: derived field failed: {exc}")
            fields[field_name] = None

    fields["degraded"] = degraded
    return fields
