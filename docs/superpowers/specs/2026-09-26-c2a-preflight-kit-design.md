# Phase C2a: the geometry pre-check kit, the run label, and C1's small fixes — design

Date: 2026-09-26. Status: draft for review.

Related:
- [`2026-09-23-generic-study-design.md`](2026-09-23-generic-study-design.md):
  the generic-study design. Its "Local plugins" table describes
  `offline_preflight`.
- [`2026-09-25-prodtools-kit-design.md`](2026-09-25-prodtools-kit-design.md):
  Phase C1, the prodtools kit this builds on (branch `generic-study-phase-c1`).
- `wiki/drivers/contract-engine.md`: the Phase C split, the C1 acceptance
  runs, and the minor findings deferred from C1's final review.
- `wiki/incidents/prodtools-tape-check-musing-python-mismatch.md`: why new
  engine studies use SimJob MDC2025ax.

## Goal

C2 moves the foilspf studies onto the contract engine. It is split in two,
each with its own spec, plan and build:

| # | Sub-project | Done when |
|---|---|---|
| **C2a** (this document) | the `offline_preflight` kit, the run label as a study setting, and C1's deferred small fixes. None of it depends on anakit. | `prodtools_smoke`, with a pre-check added, runs locally end to end on MDC2025ax; the pre-check verdicts match the old pipeline's for one passing and one failing geometry |
| C2b | the sob and flash analyses on our anakit fork, the anakit adapter, EdepAna for MDC2025ax, the foilspf engine studies, and the parity check against the pipeline's harvest | one foilspf point's numbers from the engine match the pipeline's harvest on the same files |

C3 then deletes the old pipeline.

## Decisions

All decided by the operator on 2026-09-26.

| Question | Decision |
|---|---|
| One C2 spec or two? | Two. C2a needs nothing from anakit; C2b waits on it. |
| Where do the sob and flash analyses go? | anakit, developed on our own fork for now. M. MacKenzie has been asked for a quick patch; nothing is posted to his repo without the operator's go-ahead. (C2b.) |
| How is the pre-check built? | An in-process adapter, `core/adapters/offline_preflight.py`, like the prodtools one. Not a standalone MCP server, and not a prodtools `run_local` job. |
| What code does the pre-check run? | The same code tarball as the grid jobs, the study's `kits.prodtools.code_tarball`. The separate `musing` setting goes away. |
| The `holeRadii vector active` printout check | Dropped. Upstream Offline (v13_38_00, in MDC2025ax) has per-foil hole radii but prints no such line, and the as-built GDML comparison already checks every foil's hole radius. |
| Is "ambiguous" a pass? | No. `check` fails on it, with the log's last lines in the message. |
| Where does the run label (`dsconf`) come from? | A required study setting, `kits.prodtools.dsconf`, with `{cfg}`. It leaves the stage templates. |
| Release for engine studies | SimJob MDC2025ax (`Code_mdc2025ax.tar.bz2`). The foilspf study files move in C2b, when their numbers are re-checked. |
| The old pipeline | Reference-only: no campaigns before C2b's parity check. Its pre-check switches to the shared code in this phase. |

## 1. The `offline_preflight` kit

### Files
- **New:** `core/adapters/preflight_checks.py`. Plain functions, moved out of
  `core/bo_driver.py`, that the adapter and (until C3) `bo_driver` both call:
  - `check_files(geom_basename, *, dumps_gdml) -> {filename: text}`: the
    surface-check geometry overlay and `surfacecheck.fcl`
    (`SURFACE_CHECK_GEOM_OVERLAY`, `SURFACE_CHECK_FCL`,
    `PREFLIGHT_GDML_FCL_LINES`, moved verbatim);
  - `run_check(code_dir, workdir, fcl, *, timeout_s) -> (out, rc, timed_out)`:
    sources `setupmu2e-art.sh` and `<code_dir>/Code/setup.sh`, puts `workdir`
    first on `MU2E_SEARCH_PATH` and `FHICL_FILE_PATH`, runs `mu2e -c <fcl>
    -n 1`, with `SPACK_USER_CACHE_PATH` off NFS and today's
    retry-only-if-mu2e-never-started rule;
  - `classify(out, rc, timed_out, *, geom_text, gdml_path, verifies_foil_gdml,
    checks_managed_overlap, require_zero_overlaps) -> Verdict`, where
    `Verdict(ok: bool, code: str, reason: str)` and `code` is one of today's
    `PREFLIGHT_VERDICTS` values (`pass`, `fail_managed`, `fail_init`,
    `ambiguous`, ...). Same rules and order as `_cmd_preflight_impl` today,
    minus the `holeRadii vector active` check;
  - `verify_stopping_target_gdml` and the regexes it and `classify` use,
    moved verbatim.
- **New:** `core/adapters/offline_preflight.py`, class
  `OfflinePreflightKit(campaign, *, executor, parallel)`.
- **Changed:** `core/bo_driver.py:_cmd_preflight_impl` calls the three
  functions, and gets its code from the spec's `code_tarball` instead of
  `musing`. It keeps its printing, its return codes and the
  `paths.verify(... REQUIRED_ARTIFACTS)` gate, which is pipeline-only.
- **Changed:** `core/adapters/prodtools_entry.py` gains
  `unpacked(tarball, cache_root) -> Path`: the tarball unpacked once into
  `<cache_root>/<sha256 of its bytes>/`, built in a private directory and
  renamed into place, so concurrent children unpacking the same tarball
  are safe (the same pattern as `build_code_tarball`).

### The kit
- `EXECUTORS = ("grid", "local")`: the check always runs on this node,
  whatever `--executor` says. `REQUIRES_KERBEROS = False` (no inputs, one
  event). `LAUNCH_STAGGER_S = 0`.
- `tools = {"check", "describe"}`. `describe` lists its params.
- `check(name, params, files, inputs, workflow) -> (ok, message)`:
  1. `name` is `<config>.preflight`; the config name must match the
     prodtools rule (letters, digits, `_`), checked the same way.
  2. The `geom` file ref must be a `file://` URI.
  3. Unpack `params["code_tarball"]` via `unpacked(...)` into
     `<GRID_DATA_ROOT>/_code/`.
  4. Workdir `<GRID_DATA_ROOT>/<config>/preflight/`, emptied first: the geometry
     as `autoresearch_<config>_geom.txt` (the name the grid jobs use), the
     overlay and the FCL.
  5. `run_check`, then `classify`. Keep `preflight.log` and, when dumped,
     `asbuilt.gdml` in the workdir.
  6. Return `(verdict.ok, "<code>: <reason>")`. For `ambiguous`, the reason
     carries the log's last 40 lines.
- The engine's existing `node_preflight` already calls `check` and turns a
  failure into `broken.txt`; no engine change is needed.

### Settings and registry
- `offline_preflight`'s `study_keys` become `code_tarball`, `dumps_gdml`,
  `verifies_foil_gdml`, `checks_managed_overlap`, `require_zero_overlaps`
  (all required). `musing` is removed.
- The study loader refuses a study with both kits whose
  `kits.offline_preflight.code_tarball` differs from
  `kits.prodtools.code_tarball`, naming both values.
- `KitDecl("offline_preflight", ...)` gets `engine=True` (keeps
  `pipeline=True`). The foilspf studies still run on the pipeline: their
  `ce_sensitivity` and `flash_edep_per_pot` kits are pipeline-only until
  C2b.
- The seven `mode_specs` and the `demo.json` / `template.json` fixtures swap
  `musing` for `code_tarball`, set to their own `kits.prodtools.code_tarball`.
  `prodtools_smoke.json` gains a `preflight` block and an
  `offline_preflight` kit entry with `Code_mdc2025ax.tar.bz2`.

## 2. The run label as a study setting
- Remove `dsconf_fmt` from `stage_entries/{mubeam,mustops_ce,elebeam_flash}.json`
  and from `prodtools_entry._TEMPLATE_KEYS`.
- Add `dsconf` to `prodtools`' `study_keys`, required. Validator: a string
  containing `{cfg}`; with `{cfg}` filled by a valid config name, only letters,
  digits and `_`.
- `entry_for_step(..., dsconf=...)` takes it; the adapter adds `dsconf` to
  its `PARAMS` and passes `params["dsconf"]` (study settings already reach
  the adapter's params through `step_params`).
- Values: `prodtools_smoke` `MDC2025ax_{cfg}`; the mode specs and fixtures
  `Run1Bak_{cfg}`, which is what the old pipeline's own `DSCONF` constant
  already uses (it never read the template value). The gridphaseA01 parity
  fixtures are unchanged, since that run used `Run1Bak_gridphaseA01`.

## 3. Small fixes carried over from C1

| # | Fix | Where |
|---|---|---|
| 1 | A receipt stuck in `submitting`/`building` raises with prodtools' original error text (when there was one) and advice that fits the executor: `jobsub_q` for grid, the receipt's host and pid for local. | `core/adapters/prodtools.py:_adopt`, `submit` |
| 2 | A local receipt in `starting` is refused by `_adopt` like `building`, and `status` fails a run still `starting` after `STARTING_LIMIT_S = 10 * 60`. | `core/adapters/prodtools.py` |
| 3 | `KitClient.start` writes a trace row (`tool: "start"`, its duration, errors) to `kit_trace.jsonl`. | `core/kits.py` |
| 4 | `graph.study_loop` refuses a `--name-prefix` whose child config names would break a kit's naming rule, before launching anything. The check runs on the first child name `next_free_name` would give (`graph/pool.py`), so the prefix and the suffix it adds are both covered. | `graph/study_loop.py`; the rule exported by `core/adapters/prodtools.py` |
| 5 | `status`, `results` and `cancel` retry for about 4.5 min: 5 attempts with pauses of 5, 20, 60 and 180 s. `submit` keeps 3 attempts and the (5, 20) s pauses. | `core/contract.py` (`RETRY_PAUSES_S` per call kind), `core/adapters/prodtools.py:_run_status` |
| 6 | A `uses_entries` kit's step with a param, fixed value or study setting named `entry` is refused at load time. The run-time check stays as a guard. | `core/study.py` |
| 7 | A `done`/`short` reply with no `jobs` block raises a `KitError` naming the run, instead of reporting "0/N jobs ok". | `core/adapters/prodtools.py:_complete` |

## Failures

| Failure | Result |
|---|---|
| `code_tarball` missing or not a tarball with `Code/` | the pre-check fails, naming the path; no job is submitted |
| the tarball's `Code/setup.sh` fails to set up | retried only if `mu2e` never started; then `ambiguous`, so the pre-check fails with the log tail |
| fatal G4/art abort, GDML mismatch, overlap under the study's policy, geometry error before init | the pre-check fails with today's reason text; the point is `broken` |
| the pre-check and prodtools name different `code_tarball`s | the study is refused at load |
| a bad `dsconf` (no `{cfg}`, other characters) | the study is refused at load |
| two children unpack the same tarball at once | one unpacking wins the rename; both use it |

## Testing
- `tests/test_preflight_checks.py`: `classify` on recorded logs, one per verdict
  (pass; fatal abort; GDML mismatch; zero-overlap failure; managed overlap;
  geometry error before init; ambiguous), with the log text copied from
  today's tests or from archived pipeline logs with no personal paths;
  `check_files` output; `verify_stopping_target_gdml` (tests moved with it).
- `tests/test_offline_preflight_kit.py`: `check` with `run_check` replaced by
  a fake returning recorded output; the workdir contents; the unpack cache
  (two threads at once); a bad config name; a non-`file://` geometry.
- `tests/test_bo_driver*` (existing): the pipeline's pre-check through the
  shared functions, unchanged verdicts.
- Registry and loader: the equal-`code_tarball` rule; `dsconf` validation; the
  load-time `entry` refusal.
- Each fix in section 3 gets a unit test in its module's test file.

## Acceptance (the controller, after the final review)
1. `prodtools_smoke` with its new pre-check runs locally on MDC2025ax (a new
   config name): the pre-check passes, both steps complete, a row lands.
2. Verdict parity with the old pipeline's pre-check, for two geometries:
   gridphaseA01's point (expected pass) and a deliberately broken variant of
   it that the old pre-check fails (the plan picks one, e.g. a foil radius
   beyond the target's mother volume). The old verdicts come from
   `bo_driver preflight` at the C1 branch tip (`generic-study-phase-c1`,
   Run1Bap `musing`), the new ones from the kit on MDC2025ax. Verdict codes
   must match; overlap counts may differ between releases and are recorded.

## Out of scope
- Everything in C2b: the analyses, the anakit adapter and fork, EdepAna for
  MDC2025ax, the foilspf engine study files, and the parity of sob and
  flash.
- Testing `cancel_run` (P3) against real servers.
- The prodtools tape-check bug (the operator chose not to fix it).
- Renaming `desc_fmt` to `desc` in the templates (C3, with the pipeline gone).

## Open questions
- None.
