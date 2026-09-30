# The kit seam: one declaration, one error contract, one launch check

Date: 2026-09-29. Branch: `kit-seam`, from `generic-study-phase-c1` at
`c19d8ca`, in the worktree `../autoresearch-kitseam` (the main checkout
runs the live `bpzax01` campaign, whose next children start `graph.run`
from it).

Source: the `/improve-codebase-architecture` pass of 2026-09-29
(three explorers over study/measurement, the contract and kits, the
adapters and runners). The operator picked candidates 1–3 plus the
board-column bug (fixed first, on this branch, as its own commit).

## Goal

A kit is declared in one place, fails in one way, and is checked at
launch by one function that both runners call.

## Why

- **Facts about one kit live in four places.** Native kits declare
  executors, stagger and `check` in `kits.toml`. Adapter kits declare
  settings in a `KitDecl` (`core/kit_registry.py`), and executors,
  stagger, Kerberos and the config-name rule as class attributes
  (`core/adapters/*.py`), registered through `contract.ADAPTERS` with a
  lazy `_load_adapters` (called at 5 sites) to break an import cycle.
  Four functions in `core/contract.py` branch on "adapter or native";
  a test exists only to catch the two registries drifting apart.
- **"Who decides a step failed" is unwritten.** Six call sites catch six
  different exception lists. Adapters rewrap `OSError` by convention,
  two with stale comments. Two bugs follow:
  - a prodtools config missing a server timeout raises `ValueError` when
    the kit is built; `graph/run.py:157` and `contract.py:524` catch only
    `KeyError`/`KitError`, so both runners crash with a traceback instead
    of refusing;
  - an unwrapped adapter `OSError` inside a step writes `broken.txt` and
    then re-raises, so the child exits with a traceback.
- **The launch check exists twice, partially.** `graph.closed_loop` runs
  the executor/Kerberos rules, the config-name rule and `check_kits`
  (tools, version, describe, step hooks). `graph.run` runs the
  executor/Kerberos rules, starts each kit by reading `.tools`, and runs
  only the step hooks. So:
  - a bad `--config` given to `graph.run` is not refused: it writes
    `point.json` and ends as `broken.txt`, against `graph/run.py`'s own
    "exit 2: refused before anything ran";
  - "start" is not part of the Kit interface; reading `.tools` starts
    prodtools and does nothing for anakit, which starts in its
    constructor.

## Decisions

| Question | Answer |
|---|---|
| Where does a kit's static declaration live? | **`KitDecl` in `core/kit_registry.py`**, for every kit. It already exists for all of them (adapters hand-written, native ones built from `kits.toml`). It gains the facts that now sit on adapter classes. |
| How does the engine find an adapter's class? | **By a `"module:Class"` string on its `KitDecl`**, imported when the kit is opened. `contract.ADAPTERS`, `register_adapter`, `core/adapters/__init__.py:register_all` and `_load_adapters` are deleted. kit_registry stays stdlib-only: the string is data. |
| What may a Kit raise? | **`KitError` or `ContractError`** for every expected failure (environment, transport, a kit-side refusal, bad inputs). Anything else is a bug and crashes loudly, as now. |
| Where is that enforced? | **At `KitSet.get`**: it wraps each opened kit so that `OSError`, `ValueError`, `KeyError` and `subprocess.SubprocessError` raised by construction or by any Kit method become `KitError(kit, call, "<Type>: <message>")`. Programming errors (`TypeError`, `AttributeError`, …) pass through. |
| One launch check? | **`contract.launch_problems(study, kits, *, executor, parallel, config_names, kerberos=None)`**, used by both runners. |
| Explicit start? | **Yes: `start()` joins the Kit interface.** NativeKit and prodtools start their clients; anakit and offline_preflight have nothing to start. |

## Rulings (controller, while designing)

- **No `measure_sha` change.** Nothing here touches `study_keys`,
  `fixed_keys`, kit versions or stage entries. The seven `_ax` studies'
  `measure_basis_sha` must be unchanged, and the local
  `foilspfbpz_local` point must land with `measure_sha` `8c8157af…`.
- **anakit's analysis parameters stay in its `KitDecl`.** They give a
  load-time type check; `step_problems` checks their names against
  anakit's catalogue at launch. Two checks, two jobs.
- **Timeouts and poll clamps stay where they are.** Native kits' per-call
  timeouts and the adapters' per-tool server timeouts are both already in
  `kits.toml`; poll clamps depend on the executor and belong to the kit
  instance. The two `_check_timeouts` functions stay (they check
  different tables), but raise through the new error contract.
- **Adapter rewraps:** one that exists only to dodge the crash is
  deleted; one that adds context the bare exception lacks (which command,
  which directory) stays, with its comment corrected.
- **`accepts_lists` and `poll_s` stay on the Kit instance.** They are part
  of the Kit interface the scheduler reads per call, and prodtools'
  `poll_s` depends on the executor.
- **No kit-level launch hook is added.** The ported launch checks (data
  quota, stale clusters) are still follow-ups; `launch_problems` is where
  they will go. One adapter would be a hypothetical seam.
- **Engine-side code keeps its own `ValueError`/`KeyError` handling**
  (e.g. `step_params`, `files[f]` in `core/scheduler.py`). The rule is
  about what a *kit* raises, not the engine.
- **Merge after `bpzax01` finishes**, or on the operator's word: children
  launched after a merge would run this code.

## What changes

### 1. One declaration per kit

- `KitDecl` gains:
  - `executors: tuple`;
  - `launch_stagger_s: float`;
  - `requires_kerberos: bool`;
  - `names_runs_after_config: bool` (apply
    `kit_registry.config_name_problem` at launch);
  - `factory: str | None` (`"core.adapters.prodtools:ProdtoolsKit"`; None
    for a native kit, which opens as `NativeKit`).
- The three adapter `KitDecl`s carry today's class-attribute values:
  - prodtools: `("grid","local")`, 90 s, Kerberos, config rule;
  - offline_preflight: `("grid","local")`, 0, no Kerberos, config rule;
  - anakit: `("grid","local")`, 0, no Kerberos, no config rule.
- `_native_decl` fills them from `kits.toml` (`executors`,
  `launch_stagger_s`; Kerberos false, no config rule).
- `contract.launch_stagger`, `_executors_of`, `requires_kerberos` and
  `config_name_problems` read `kit_registry.KITS[name]` with no branch.
- `contract.open_kit` imports `decl.factory` on demand, or builds a
  `NativeKit`.
- The adapter classes drop `EXECUTORS`, `LAUNCH_STAGGER_S`,
  `REQUIRES_KERBEROS` and `config_problem`; their constructors' executor
  checks read the declaration.
- Tests: the registry-drift test becomes "every declared factory
  imports and names a class"; tests that injected fake adapters through
  `ADAPTERS` inject through `KitSet`'s opener or a patched `KITS` entry.

### 2. The kit error contract

- The contract docstring (`core/contract.py`) states the rule.
- `KitSet.get` returns kits wrapped in a guard that maps
  `OSError`/`ValueError`/`KeyError`/`SubprocessError` from the factory
  call and from every Kit method to `KitError`, naming the kit and the
  call.
- Callers narrow to `(KitError, ContractError)` for kit calls:
  `scheduler._run_one` (kit calls only), `_cancel_running`,
  `study_graph.node_preflight`, `graph/run.py`, `contract.check_kits`
  (which becomes `launch_problems`).
- Bugs fixed: a missing prodtools timeout refuses cleanly (exit 2); an
  adapter `OSError` mid-step breaks the point without a traceback.

### 3. One launch check

- `contract.launch_problems(study, kits, *, executor, parallel,
  config_names, kerberos=None) -> list[str]` runs, in order:
  - `executor_problems`;
  - the Kerberos rule (grid, when a kit requires it);
  - the config-name rule for each of `config_names`;
  - per kit: `start()`, the contract tools it needs, a version, the
    `describe` cross-check and its `step_problems`.
- `graph.closed_loop` calls it with a KitSet opened for the check and
  closed after, and `config_names=[child_name(prefix, 0)]`.
- `graph.run` calls it with the KitSet the steps then reuse, and
  `config_names=[args.config]`: a bad `--config` is refused, exit 2.
- `launch_refusals` in `graph/run.py`, `check_kits` and
  `config_name_problems` in `core/contract.py` are removed; tests move to
  `launch_problems`.

## Acceptance

1. The full suite is green:
   `PYTHONPATH= "$AUTORESEARCH_PYTHON" -m unittest discover -s tests -t .`.
2. New tests:
   - a prodtools kit missing a server timeout refuses `graph.run` with
     exit 2 and names the timeout;
   - `graph.run --config bad.name` refuses with exit 2 and writes nothing;
   - an adapter `OSError` inside a step ends in `broken.txt` and exit 0;
   - `launch_problems` covers each check in order.
3. `grep` finds no `ADAPTERS`, `register_adapter`, `_load_adapters`,
   `LAUNCH_STAGGER_S`, `REQUIRES_KERBEROS`, `config_problem`,
   `launch_refusals` or `check_kits` in `core/`, `graph/` or `tests/`.
4. The seven `_ax` studies' `measure_basis_sha` are unchanged.
5. A local `foilspfbpz_local` point in the `c3_sandbox/local` sandbox
   lands a row with `measure_sha` `8c8157af…`, and a Branin
   `graph.closed_loop` runs end to end.

## Out of scope

- Candidates 4–8 of the architecture pass (point directory, board column
  schema, History object, Objective axis rule, inputs digest).
- Retry policy differences between adapters (each is documented).
- Porting the pipeline's launch checks (quota, stale clusters).
- Replacing LangGraph in `graph/study_graph.py`.
- Pushing, or merging while `bpzax01` runs.
