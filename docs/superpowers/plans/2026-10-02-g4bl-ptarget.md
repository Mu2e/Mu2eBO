# G4beamline Production-Target Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `ptg4bl` study, a tungsten rod with a length and a 3-point radius profile, runs on the contract engine through beamkit and lands rows of μ⁻+π⁻ per POT at `Coll_01_Det`.

**Architecture:**
- A deck branch makes the target a polycone whose dimensions come from the command line.
- A new adapter, `core/adapters/beamkit.py`, drives beamkit's MCP server: submit, status from the queue and the output count, and results counted from the ntuples with uproot.
- `mode_specs/ptg4bl.json` is a one-step study.

**Tech Stack:** Python 3.12 (ana 2.8.0: mcp 2.0, uproot 5.7.6, numpy), G4beamline deck syntax, unittest.

**Spec:** `docs/superpowers/specs/2026-10-02-g4bl-ptarget-design.md`

## Global Constraints

- **Worktree:** `/exp/mu2e/app/users/oksuzian/autoresearch-checkstudy`, branch `g4bl-ptarget` (spec d734f8c).
- **The deck clone** is `/exp/mu2e/app/users/oksuzian/G4BeamlineScripts`.
- **Suite:** `PY=/cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python`; `PYTHONPATH= $PY -m unittest discover -s tests -t .`. The baseline is 858 OK (skipped=3).
- **No test touches the grid, Kerberos or beamkit's real server.**
  - Tests drive `tests/fakebeamkit.py`.
  - A launch check that needs a ticket gets a fake `klist` on `PATH`, which prints a ticket expiring in 2099 (the format of `KLIST_OK` in `tests/test_contract.py`).
- **Imports:** bare `core/` modules, as the other adapters do (`if __package__ == "core.adapters"` pairs).
- **No submit with `run_as="mu2epro"`,** ever. `outloc="scratch"`. `make_recoveries` is never called.
- **Every existing `measure_basis_sha` is unchanged:**
  - ce_chain 79b9b3e2;
  - foilsflash_ax 405cc0e8;
  - foilspf2k_ax 2060c97e;
  - foilspf_ax e96f0491;
  - foilspfbp_ax 54467d3e;
  - foilspfbpx_ax d6ee2d28;
  - foilspfbpz_ax c4aafee1;
  - foilspfbw_ax 01bcbd62.
- **Nothing is pushed to GitHub by the executor:** tool shells have no ssh-agent, and pushes need the operator's word. The operator pushes the deck branch.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

**Ruling (plan against spec):** "the count" is unique tracks, not rows. Each `(file, EventID, TrackID)` with a listed PDG id counts once at the plane. A track looping in the solenoid field can cross a virtual detector more than once, and counting rows would count it twice. The cost if this is wrong is one line, and `FOM_VERSION` says which.

## Review Focus

1. **A deck param named like an adapter setting** (for example a knob called `njobs`).
   - **Expected:** refused when the study loads, never silently consumed as a setting.
   - **Test:** Task 2, `test_a_knob_named_like_a_setting_is_refused`.
2. **beamkit refuses the submit** (an unfetchable sha, no token).
   - **Expected:** `KitError` with beamkit's text, and the step record removed, so a fixed rerun submits.
   - **Test:** Task 3, `test_a_refused_submit_leaves_no_record`.
3. **The queue is unreadable for more than 6 h.**
   - **Expected:** failed, naming the reason.
   - **Test:** Task 3, `test_an_unreadable_queue_fails_after_the_limit`, with the clock injected.
4. **A file is missing the plane's tree, or two files hold the same EventIDs.**
   - **Expected:** a `KitError` naming the file; duplicates are counted per file.
   - **Test:** Task 3, `test_counts`.
5. **`results` before `status` says completed.**
   - **Expected:** `KitError` "not completed".
   - **Test:** Task 3, `test_results_before_completion`.

---

### Task 1: The deck branch (local; the operator pushes)

**Files:**
- Modify (deck clone): `Geometry/Proton_Target_W.txt`, on a new branch `ptarget-polycone` from `epsmax-0.01` (adba281).

- [ ] **Step 1: Edit `Geometry/Proton_Target_W.txt`:**
  - **The size params:** replace `param Tlength=160.0 Tradius=6.299*.5` with:
    - `param -unset Tlength=160.0`;
    - `param Tradius=6.299*.5`;
    - `param -unset R_up=3.1495 R_mid=3.1495 R_dn=3.1495`.
  - **The solid:** replace the `tubs pTarget ...` command with `polycone pTarget z=-$Tlength/2,0,$Tlength/2 innerRadius=0,0,0 outerRadius=$R_up,$R_mid,$R_dn material=$Tmaterial color=$Tungsten`. The `place pTarget` stays as it is.
- [ ] **Step 2: Check the deck parses without a grid job, if possible.** If `g4bl` is available through `source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh; setup G4beamline` (look at `$G4BEAMLINE_DIR`, never search /cvmfs), run `g4bl Mu2E.in viewer=none Num_Events=0 epsMax=0.01 Use_Proton_Target=4 R_mid=2.0` and grep the output for `ptarget: Tlength=160 R_up=3.1495 R_mid=2 R_dn=3.1495`. If it is not available, record that in the ledger; acceptance step 2 then proves it on the grid.
- [ ] **Step 3: Commit on the deck branch** (`git -C <deck clone> commit -am "ptarget: polycone target; Tlength and three radii from the command line"`), and record the sha in the ledger.
- [ ] **Step 4: Ask the operator to push.** Tell them: fork `Mu2e/G4BeamlineScripts` on GitHub, then push from the deck clone with `git remote add fork git@github.com:<user>/G4BeamlineScripts.git && git push fork ptarget-polycone`. Record the fork URL they confirm. Tasks 2-5 do not wait for this; Task 6 does.

### Task 2: beamkit as a kit — registry, `kits.toml`, `activate.sh`

**Files:**
- Modify: `core/kit_registry.py` (validators and `KitDecl("beamkit")`), `kits.toml`, `activate.sh`.
- Test: `tests/test_beamkit_kit.py` (new), `tests/test_activate.py`.

**Produces:**
- **Validators in `kit_registry`:**
  - `_sha40(v)`: 40 lowercase hex;
  - `_int_list(v)`: a non-empty list of ints, no bools;
  - `_deck_params(v)`: a dict whose keys match `[A-Za-z_]\w*`, are not in `BEAMKIT_RESERVED = ("First_Event", "Num_Events", "histoFile", "viewer")`, and whose values are int, float or str (no bool).
- **`KitDecl("beamkit", ...)`:**
  - `study_keys = {deck_url: _string, deck_ref: _sha40, main_input: _string, deck_params: _deck_params}`;
  - `fixed_keys = {njobs: _job_count, events_per_job: _positive_int, quorum: _fraction, plane: _string, pdg: _int_list}`, with `required_fixed = {"quorum", "plane", "pdg"}`;
  - `uses_entries=False`, `step_kit=True`, `check_kit=False`, `executors=("grid",)`, `launch_stagger_s=0.0`, `requires_kerberos=True`, `names_runs_after_config=True`, `factory="adapters.beamkit:BeamkitKit"`.
- **`BEAMKIT_OWN = ("deck_url", "deck_ref", "main_input", "deck_params", "njobs", "events_per_job", "quorum", "plane", "pdg")`:** the names the adapter reads itself.
  - The study loader refuses a beamkit step whose `params` maps a name in `BEAMKIT_OWN` or `BEAMKIT_RESERVED`, with `"<step>.params.<name>: a beamkit setting, not a deck param"`.
  - It is wired where `core/study.py` checks a step's params against its kit (`_steps`), through a new `KitDecl` field `reserved_params: FrozenSet[str]`. Every existing `KitDecl(...)` gets `reserved_params=frozenset()` explicitly (ADR-0002: no field defaults), including the native-kit declarations built from `kits.toml`.
- **`kits.toml` `[servers.beamkit]`:**
  - `command = ["${AUTORESEARCH_BEAMKIT}/.venv/bin/beamkit-mcp"]`;
  - `env_passthrough`: the same list as `prodtools_write`;
  - `set = { BEAMKIT_PRODTOOLS_ROOT = "${AUTORESEARCH_PRODTOOLS}" }`;
  - `timeouts = { start = 120, run_beamline = 900, beamline_status = 120, beamline_outputs = 120 }`.
- **`activate.sh`:** export `AUTORESEARCH_BEAMKIT` from the sibling `$_parent/beamkit` when it is unset and that directory exists, exactly as `AUTORESEARCH_ANAKIT`; add one line to the header comment.

- [ ] **Step 1: Failing tests** (`tests/test_beamkit_kit.py`, class `TestRegistry`, using `tests.engine_fixtures.write_study` and `st.load_study_file`). The helper `ptg_doc()` returns the Task 4 study document, in memory.
  - `test_a_good_beamkit_study_loads`: the doc loads; `study.steps[0].kit == "beamkit"`.
  - `test_settings_are_checked`, each a `ValueError` naming the key:
    - `deck_ref="abc"`;
    - `pdg=[]`;
    - `pdg=[13, True]`;
    - `deck_params={"Num_Events": 5}`;
    - `deck_params={"1x": 5}`;
    - a missing `quorum`.
  - `test_a_knob_named_like_a_setting_is_refused`: step `params {"njobs": "Tlength"}` gives a `ValueError` containing `"a beamkit setting, not a deck param"`.
  - `test_grid_only`: `KITS["beamkit"].executors == ("grid",)` and `requires_kerberos` is true.
  - `tests/test_activate.py`: add `AUTORESEARCH_BEAMKIT` to the sibling-default test the same way the anakit one is written.
- [ ] **Step 2: Run them.** Expected: `KeyError: 'beamkit'` (not registered) and the activate test failing.
- [ ] **Step 3: Implement** as in Produces.
- [ ] **Step 4: Run** `tests.test_beamkit_kit`, `tests.test_activate`, `tests.test_kit_config`, `tests.test_study`, `tests.test_no_hardcoded_paths`. Expected: all OK.
- [ ] **Step 5: Commit:** `beamkit: a registered kit -- settings, kits.toml server, AUTORESEARCH_BEAMKIT`.

### Task 3: `core/adapters/beamkit.py` and its fake server

**Files:**
- Create: `core/adapters/beamkit.py`, `tests/fakebeamkit.py`.
- Test: `tests/test_beamkit_kit.py`.

**Consumes:** `KITS["beamkit"]` and `BEAMKIT_OWN` (Task 2); `kit_config.load_server_configs()`; `KitClient(cfg, campaign=, trace_dir=)`; `client.call(tool, args, timeout_s=, workflow=)`; `scheduler.write_atomic`.

**Produces:**
- **Constants:** `VERSION = "beamkit-adapter/1"`, `FOM_VERSION = 1`, `SERVER = "beamkit"`, `UNKNOWN_LIMIT_S = 6 * 3600`.
- **`tag_for(name: str) -> str`:** `re.sub(r"[^A-Za-z0-9]", "", name) + hashlib.sha256(name.encode()).hexdigest()[:6]`.
- **`count_tracks(paths: Sequence[str], plane: str, pdg: Sequence[int]) -> int`:** unique `(file index, int(EventID), int(TrackID))` over the rows of `NTuple/<plane>` whose `int(PDGid)` is in `pdg`. A missing tree or an unreadable file raises `KitError(SERVER, "results", "<path>: <why>")`.
- **`BeamkitKit(campaign, *, executor="grid", parallel=None, server=None, client_factory=None, grid_root=None, clock=time.time)`:**
  - `name = "beamkit"`, `accepts_lists = False`, `poll_s = (30.0, 300.0)`;
  - `tools = frozenset({"submit", "status", "results", "cancel"})`;
  - `describe()` returns None;
  - `start()` opens one `KitClient` and reads beamkit's version from `get_server_info`;
  - `version` is `f"{VERSION}+beamkit-{server_version}+fom{FOM_VERSION}"`;
  - `close()` closes the client.
- **Step record** `grid_root/<config>/state/<step>_beamkit.json` (config and step split at the last `.`), holding `{name, tag, run_id, njobs, events_per_job, quorum, plane, pdg, submitted}`.
- **`submit(name, params, files, inputs, workflow)`:**
  - **Adopt** an existing record and return `name`.
  - **Otherwise, split the params:**
    - `deck = {k: repr(float(v)) for knobs}` (every param not in `BEAMKIT_OWN`);
    - then `deck.update(params["deck_params"])`, with values made `str`.
  - **Write the record,** then call `run_beamline(tag=tag_for(name), run_as="self", deck_url=, deck_ref=, main_input=, params=deck, njobs=, events_per_job=, outloc="scratch", submit=True)`.
  - **Store** the reply's `run_id` in the record.
  - **On any error,** remove the record and raise `KitError` with beamkit's text.
- **`status(handle, workflow) -> Status`:**
  - `q = reply["status"]["campaigns"][0]["queue"]`. A reply without it is unknown.
  - **Queue unknown:**
    - `working` with `q["reason"]`, until `clock() - submitted > UNKNOWN_LIMIT_S`;
    - then `failed`, with `"queue unreadable for 6 h: <reason>"`.
  - **Queue known, `idle + running > 0`:** `working`, with `progress = {done: n_files, total: njobs, ok: n_files}`.
  - **Otherwise,** `n = beamline_outputs(run_id)["n_files"]`:
    - `completed` if `n >= ceil(quorum * njobs)`;
    - else `failed`, with `f"{n} of {njobs} files (quorum {need}), {held} held"`.
- **`results(handle, workflow) -> Results`:**
  - `KitError("not completed")` unless the status is completed;
  - the paths are `[f["path"] for f in outputs["files"]]`;
  - `pot = len(paths) * events_per_job`; zero gives `KitError`;
  - **Metrics:** `yield_per_pot = n / pot`, `n_selected = n`, `pot`, `n_files`;
  - **Files:** `[{name: basename, uri: "file://" + path, kind: "nts"}]`.
- **`cancel(handle, workflow)`** returns the current state with no beamkit call; the message is "beamkit has no cancel: remove the jobs with jobsub_rm".

**`tests/fakebeamkit.py`:** an `MCPServer("beamkit")` over stdio. Its state is in `$FAKEBEAMKIT_STATE/<run_id>.json`, which tests edit.
- `run_beamline(**kw)`:
  - refuses `deck_ref == "f"*40` with "deck sha not found";
  - otherwise records the call and returns `{run_id: f"{tag}.{deck_ref[:7]}", ...}`.
- `beamline_status(run_id)` returns `{record, site: "fermilab", status: {campaigns: [{queue: <state.queue>}]}}`.
- `beamline_outputs(run_id)` returns `{n_files, files: [{path, size}]}`.
- `get_server_info()` returns `{version: "0.5.1-fake"}`.

- [ ] **Step 1: Failing tests** (`tests/test_beamkit_kit.py`, class `TestAdapter`). It uses a `ServerConfig` running `sys.executable tests/fakebeamkit.py` with `FAKEBEAMKIT_STATE` in `set`, and a helper `nts(path, rows)` writing `NTuple/Coll_01_Det` with uproot (`PDGid`, `EventID`, `TrackID` as float32).
  - `test_tags_are_unique`: `tag_for("a_bR00_00.g4bl") != tag_for("abR00_00.g4bl")`, and both match `[A-Za-z0-9]+`.
  - `test_submit_is_idempotent_and_splits_params`:
    - two submits of `"cfgR00_00.g4bl"` give one `run_beamline` call;
    - its params are `{"Tlength": "160.0", "R_up": "3.1495", ..., "Use_Proton_Target": "4", "epsMax": "0.01"}`, with no `njobs`/`plane` among them;
    - `njobs == 20`, `run_as == "self"`, `outloc == "scratch"`.
  - `test_a_refused_submit_leaves_no_record`: `deck_ref "f"*40` gives a `KitError` containing `"deck sha not found"`; no record file; a later good submit calls `run_beamline`.
  - `test_status_rule`:
    - queue `{state: known, idle: 3, running: 2, held: 0}` gives `working`;
    - idle 0, running 0, 18 files of 20 with quorum 0.9 gives `completed`;
    - 17 files with held 3 gives `failed`, with `"17 of 20 files"` and `"3 held"` in the message.
  - `test_an_unreadable_queue_fails_after_the_limit`: queue `{state: unknown, reason: "schedd"}` gives `working` at clock 0 and `failed`, with `"queue unreadable"`, at `UNKNOWN_LIMIT_S + 1`.
  - `test_counts`:
    - file A has rows (13,1,5), (13,1,5), (−211,1,6), (211,1,7), (11,2,8);
    - file B has (13,1,5);
    - `count_tracks([A, B], "Coll_01_Det", [13, -211]) == 3`, since the duplicate row counts once and file B's identical ids count separately;
    - a file with only `NTuple/Other` gives a `KitError` naming that file.
  - `test_results`: the fake has 2 files of the rows above with `events_per_job=1000`. Metrics are `{yield_per_pot: 3/2000, n_selected: 3, pot: 2000, n_files: 2}`, and there are 2 FileRefs.
  - `test_results_before_completion`: a working run gives `KitError` with `"not completed"`.
  - `test_version_names_beamkit_and_fom`: `"beamkit-0.5.1-fake"` and `"fom1"` are both in `kit.version`.
- [ ] **Step 2: Run them.** Expected: `ModuleNotFoundError: adapters.beamkit` / `tests.fakebeamkit` missing.
- [ ] **Step 3: Implement** the adapter and the fake as in Produces.
- [ ] **Step 4: Run `tests.test_beamkit_kit`.** Expected: all OK.
- [ ] **Step 5: Commit:** `beamkit: the adapter -- submit, status by queue and quorum, results counted from the ntuples`.

### Task 4: The study `ptg4bl`, checked end to end against the fake

**Files:**
- Create: `mode_specs/ptg4bl.json`.
- Modify: `tests/test_modes.py` (`SHIPPED_SPECS` gains `"ptg4bl.json"`), `mode_specs/README.md`.
- Test: `tests/test_beamkit_kit.py` (class `TestEndToEnd`).

**Produces:** `ptg4bl.json` exactly as the spec's "mode_specs/ptg4bl.json", with:
- `deck_url = "https://github.com/<operator user>/G4BeamlineScripts"`, the URL recorded in Task 1 Step 4. Until it is recorded, `https://github.com/oksuzian/G4BeamlineScripts`, the operator's GitHub user per the repo's issue tracker.
- `deck_ref` = Task 1's sha;
- objective `noise: 0.002`;
- `extra_metrics` `n_selected` (`g4bl.n_selected`, `"{:.0f}"`) and `pot` (`g4bl.pot`, `"{:.0f}"`).

**README, "From draft to launch":** one paragraph, "A knob a deck reads": a G4beamline study's knobs are deck params, which need `param -unset` in a pinned deck branch, because a plain `param` line overrides the command line.

- [ ] **Step 1: Failing tests,** `TestEndToEnd`:
  - **The environment:**
    - `AUTORESEARCH_BEAMKIT` is a temp dir whose `.venv/bin/beamkit-mcp` is a two-line shell script: `export FAKEBEAMKIT_STATE=<tmp>/state` then `exec <python> <repo>/tests/fakebeamkit.py`;
    - `PATH` is prefixed with a temp dir holding the fake `klist`;
    - `AUTORESEARCH_PRODTOOLS` is set to any existing dir, since `kits.toml` requires it for `BEAMKIT_PRODTOOLS_ROOT`;
    - the study path holds a copy of `ptg4bl.json` (renamed `ptg4blfake`, with its own board) whose `deck_ref` is a fake sha the fake accepts;
    - `engine_env(data, studies)`.
  - `test_check_study_passes_against_the_fake`: `python -m graph.check_study ptg4blfake --json` exits 0. `load`, `artifacts` and `launch` passed; `geometry` passed with its "no geometry" note (whatever note `check_study` gives a `geom: null` study; assert the status only).
  - `test_graph_run_lands_a_row`:
    - **The run:** `python -m graph.run --study ptg4blfake --config e2eR00_00 --campaign e2e --x=160,3.1495,3.1495,3.1495` is started.
    - **Feeding the fake:** the test waits for the state file, then sets the queue to idle/running 0 and writes 20 nts files of known rows.
    - **Expected:** the run exits 0; the board `leaderboard_bo_ptg4blfake.tsv` has one row whose `mu_pi_per_pot` equals the expected count / 20000, with `n_selected` and `pot` columns.
- [ ] **Step 2: Run them.** Expected: `check_study` exit 2 (no study `ptg4blfake`) until the study file and fixtures exist.
- [ ] **Step 3: Implement:** the study file, the fixtures, the `SHIPPED_SPECS` line and the README paragraph.
- [ ] **Step 4: Run** `tests.test_beamkit_kit`, `tests.test_modes`. Then the full suite: 858 plus the new tests, all OK (skipped=3). Then the eight `measure_basis_sha` values, unchanged; also print `ptg4bl`'s for the record.
- [ ] **Step 5: Commit:** `study: ptg4bl, the G4beamline production target, through beamkit`.

### Task 5: Records

- [ ] **Step 1: Wiki:**
  - **New `projects/bo-ptg4bl.md`** (`type: project`, `status: active`):
    - the study;
    - the deck branch and its sha;
    - the FoM and the unique-track ruling;
    - the knobs and their nominal values;
    - the acceptance protocol.
  - **A "beamkit adapter (2026-10-02)" section in `drivers/contract-engine.md`:**
    - the status rule;
    - no recoveries;
    - the tag scheme;
    - `BEAMKIT_PRODTOOLS_ROOT` = the dev checkout;
    - Claude Code's own beamkit config points at the cvmfs prodtools, which is why `beamline_status` errors there.
  - **`log.md` and `index.md` lines.**
- [ ] **Step 2: Memory:** `project_phase_c1_branches.md` and its MEMORY.md line.
- [ ] **Step 3:** The suite is green. Commit: `wiki: the ptg4bl line and the beamkit adapter`.

### Task 6: Grid acceptance (after the operator's push; Kerberos at least 4 h)

- [ ] **Step 1:** `git ls-remote <fork URL> ptarget-polycone` shows Task 1's sha. If not, stop and ask the operator.
- [ ] **Step 2: The nominal point.** `graph.run --study ptg4bl --config ptgnom01 --campaign ptgacc --x=160,3.1495,3.1495,3.1495`, in the background, with its log under `autoresearch_graph_data`.
  - **Expected:** exit 0 and one row.
  - **Record:**
    - `yield_per_pot`, `n_selected`;
    - the wall time per job, from one job's `log.*`;
    - the Poisson σ, `sqrt(n)/pot`.
- [ ] **Step 3: The override check.** `--config ptgrmid01 --x=160,3.1495,2.0,3.1495`. Its job logs echo `polycone pTarget … outerRadius=3.1495,2.0,3.1495`, and the nominal point's echo `3.1495,3.1495,3.1495`. Record both yields.
- [ ] **Step 4: Set the noise.** Set `ptg4bl.json`'s objective `noise` to the measured σ, rounded up to 2 significant figures. Check that the board's rows still pass the launch check: a noise change does not enter `measure_sha`, which the spec's study design says. Then commit `ptg4bl: noise from the nominal point`.
- [ ] **Step 5: Wiki and ledger.** Add the results to `projects/bo-ptg4bl.md` and the ledger. A campaign starts only on the operator's word (`start_campaign`: a dry run, then confirm, q=5, max_evals=20, `--picker qlnei`).
