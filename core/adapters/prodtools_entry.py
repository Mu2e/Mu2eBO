"""prodtools entries, code tarballs and input staging, as plain functions
(Phase C1 spec, "The adapter"): the prodtools adapter
(core/adapters/prodtools.py) and, until Phase C3 deletes it, the old
pipeline (core/prodtools_exec.py, core/pipeline.py) both call these, so
the two runners render and stage the same way.
"""
from __future__ import annotations

import errno
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

USER = os.environ.get("USER") or getpass.getuser()
TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "pipeline_templates"
# Prepends the unpacked tarball to both search paths, so the geometry file
# and the bare-name #include files it ships are found before the release's.
SETUP_POST = ('export MU2E_SEARCH_PATH="$CODE_DIR:$MU2E_SEARCH_PATH"\n'
              'export FHICL_FILE_PATH="$CODE_DIR:$FHICL_FILE_PATH"\n')
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_DEFAULT_OUTLOC = {"*.art": "outstage", "*.root": "outstage"}
_TEMPLATE_KEYS = ("desc_fmt", "dsconf_fmt", "fcl", "output_glob")


def substitute_placeholders(value, mapping: dict, where: str):
    """Recursively substitute {name} tokens in string values (nested dicts
    and lists). Any token not in `mapping` is a loud ValueError naming the
    key path: a typo must fail here, not render literally into a submitted
    FHiCL override. Always builds NEW containers, so repeated calls over one
    cached template never alias."""
    if isinstance(value, str):
        def repl(m):
            token = m.group(1)
            if token not in mapping:
                raise ValueError(
                    f"stage template: unknown placeholder {{{token}}} at "
                    f"{where!r} -- only {sorted(mapping)} are substituted "
                    f"here")
            return str(mapping[token])
        return _PLACEHOLDER_RE.sub(repl, value)
    if isinstance(value, list):
        return [substitute_placeholders(v, mapping, f"{where}[{i}]")
                for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: substitute_placeholders(v, mapping, f"{where}.{k}")
                for k, v in value.items()}
    return value


def render_entry(*, dsconf, desc, njobs,
                 code_tarball, fcl_name, events=None, run=None,
                 memory_mb=None, input_data=None, inloc=None,
                 resampler_name=None, fcl_overrides=None,
                 outloc=None, sequential_aux=None) -> dict:
    """One json2jobdef entry dict for a (config, stage).

    `fcl_name` is the PUBLISHED Production FCL path from
    stage_entries/<stage>.json; `fcl_overrides` is copied verbatim (prodtools
    renders it on top of that base FCL). Code-mode for every stage: the
    per-config tarball ships the geom, so grid and local read identical FCL
    (the env-divergence incident class is closed by construction).
    Caller-supplied `outloc` wins; _DEFAULT_OUTLOC covers only a caller that
    passes none, so editing a stage's JSON outloc actually takes effect
    instead of being silently shadowed here.
    Only the keys named here reach json2jobdef; `sequential_aux` is copied
    when given.
    """
    entry = {
        "desc": desc,
        "dsconf": dsconf,
        "owner": USER,
        "fcl": fcl_name,
        "code": str(code_tarball),
        "njobs": njobs,
        "outloc": dict(outloc) if outloc is not None else dict(_DEFAULT_OUTLOC),
    }
    if events is not None:
        entry["events"] = events
        entry["run"] = run
    if memory_mb is not None:
        entry["memory"] = f"{memory_mb}MB"
    if input_data is not None:
        entry["input_data"] = input_data
        entry["inloc"] = inloc
    if resampler_name is not None:
        entry["resampler_name"] = resampler_name
    if fcl_overrides is not None:
        entry["fcl_overrides"] = dict(fcl_overrides)
    if sequential_aux is not None:
        entry["sequential_aux"] = sequential_aux
    return entry


def entry_for_step(template, *, config, fixed, code_tarball, geom_name=None,
                   staged=None):
    """(entry, facts) for one prodtools step.

    `template` is the step's stage template as the study resolved it;
    {cfg} becomes `config`, and {geom} `geom_name` (a template that names
    {geom} for a step with no geometry file is refused). `fixed` holds the
    study's njobs / events_per_job / memory_mb when it sets them; the
    template's njobs / events / memory are the defaults. `staged` is
    (directory, {basename: 1}) when the step reads upstream outputs.
    `facts` are what the adapter records: desc, dsconf, njobs,
    events_per_job and output_glob.
    """
    mapping = {"cfg": config}
    if geom_name is not None:
        mapping["geom"] = geom_name
    t = substitute_placeholders(template, mapping, "entry")
    missing = [k for k in _TEMPLATE_KEYS if k not in t]
    if missing:
        raise ValueError(f"stage template: missing key(s) {missing}")
    njobs = fixed.get("njobs", t.get("njobs"))
    if njobs is None:
        raise ValueError("stage template: no njobs in the step's fixed or "
                         "the template")
    events = fixed.get("events_per_job", t.get("events"))
    entry = render_entry(
        dsconf=t["dsconf_fmt"], desc=t["desc_fmt"], njobs=njobs,
        code_tarball=code_tarball, fcl_name=t["fcl"], events=events,
        run=t.get("run"), memory_mb=fixed.get("memory_mb", t.get("memory")),
        input_data=staged[1] if staged else t.get("input_data"),
        inloc=f"dir:{staged[0]}" if staged else t.get("inloc"),
        resampler_name=t.get("resampler_name"),
        fcl_overrides=t.get("fcl_overrides"), outloc=t.get("outloc"),
        sequential_aux=t.get("sequential_aux"))
    facts = {"desc": t["desc_fmt"], "dsconf": t["dsconf_fmt"],
             "njobs": njobs, "events_per_job": events,
             "output_glob": t["output_glob"]}
    return entry, facts


def include_files(template, templates_root) -> list:
    """The FHiCL files a code tarball must ship: every bare-name (no '/')
    '#include' of the template's fcl_overrides, from `templates_root`. A
    published Production/... path resolves from the release and ships
    nothing."""
    inc = template.get("fcl_overrides", {}).get("#include", [])
    if isinstance(inc, str):
        inc = [inc]
    out = []
    for name in inc:
        if "/" in name:
            continue
        path = Path(templates_root) / name
        if not path.is_file():
            raise ValueError(f"stage template: #include {name!r} is not in "
                             f"{templates_root}")
        out.append(path)
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tar(args, what):
    r = subprocess.run(["tar", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"{what} failed (rc={r.returncode}): "
                         f"{r.stderr.strip()}")


def build_code_tarball(base, *, geom_path, geom_name, extra_files,
                       out_dir) -> Path:
    """Code.<digest>.tar.bz2 in `out_dir`: the base tarball's Code/, plus the
    geometry file (as `geom_name`), the extra files and setup_post.sh. The
    digest covers every input's bytes, so identical inputs reuse one file
    and a changed geometry never does. Built in a private directory and
    moved into place atomically: concurrent builders are safe."""
    base = Path(base)
    if not base.is_file():
        raise ValueError(f"code_tarball {base} does not exist")
    parts = sorted([(Path(p).name, Path(p)) for p in extra_files]
                   + ([(geom_name, Path(geom_path))] if geom_path else []))
    h = hashlib.sha256(_sha256_file(base).encode())
    for name, path in parts:
        h.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    h.update(SETUP_POST.encode())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"Code.{h.hexdigest()[:16]}.tar.bz2"
    if final.exists():
        return final
    work = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=out_dir))
    try:
        _tar(["xjf", str(base), "-C", str(work)], f"unpacking {base}")
        code = work / "Code"
        if not code.is_dir():
            raise ValueError(f"code_tarball {base} has no top-level Code/ "
                             f"directory")
        for name, path in parts:
            shutil.copy(path, code / name)
        (code / "setup_post.sh").write_text(SETUP_POST)
        packed = work / "packed.tar.bz2"
        _tar(["cjf", str(packed), "-C", str(work), "Code"],
             f"packing {final.name}")
        os.replace(packed, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return final


def link_inputs(sources, dest, *, allow_copy) -> dict:
    """Hard-link every source into `dest` (emptied first); return
    {basename: 1}, json2jobdef's input_data. Hard, not symbolic, links:
    xrootd will not follow /pnfs symlinks. allow_copy: a cross-device link
    falls back to a copy (a local run only; on /pnfs a copy would eat the
    quota, wiki/incidents/data-quota-exhausted-grid-accumulation.md)."""
    dest = Path(dest)
    if dest.exists():
        for p in dest.iterdir():
            p.unlink()
    else:
        dest.mkdir(parents=True)
    names = {}
    for src in map(Path, sources):
        if src.name in names:
            raise ValueError(f"two inputs share the basename {src.name!r}; "
                             f"input_data is keyed by basename")
        try:
            os.link(src, dest / src.name)
        except OSError as exc:
            if exc.errno != errno.EXDEV or not allow_copy:
                raise
            shutil.copy2(src, dest / src.name)
        names[src.name] = 1
    return names


def write_entry_file(path, entry) -> Path:
    """The one-element list json2jobdef reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([entry], indent=1) + "\n")
    return path
