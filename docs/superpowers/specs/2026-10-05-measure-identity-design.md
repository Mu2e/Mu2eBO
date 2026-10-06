# Measure identity — design

2026-10-05. Candidate C of the architecture survey of 2026-10-05. The
operator chose: a board splits only when someone bumps a version by hand;
existing boards are re-stamped once, by hand; design "OK".

## Goal

A leaderboard holds one measurement. Whether a launch or a row matches the
board is decided in one place, by a rule an operator controls: a kit's
version changes only when its author bumps it. An unrelated commit to a kit
no longer forces a new board, as the `nts_momentum` commit for `ce_chain`
did for every `_ax` board.

Unchanged:
- the per-row `measure_sha` and how it is computed from the study's
  measure basis plus each step kit's version;
- `measure_basis_sha` in point.json;
- the quarantine of a row that does not match;
- the refusal to finish a point across a version change.

## Today

- **The rule is enforced in four places:**
  - `core/scheduler.py` records each step's `kit_version`;
  - `core/score.py:kit_versions` and `row_meta` turn them into the row's
    `measure_sha`;
  - `core/contract.py:board_versions` and `board_problems` repeat that for
    the launch check. They import score late, because score → scheduler →
    contract → score is a cycle;
  - `core/leaderboard.py:_is_new_row` refuses a row with another sha.
- **Each kit means something different by "version":**
  - **prodtools:** `prodtools-adapter/1`, bumped by hand;
  - **anakit:** `anakit-adapter/1+anakit-<fork commit>`, so any fork
    commit changes it;
  - **beamkit:** `beamkit-adapter/1+beamkit-<server version>+fom1`, so any
    beamkit release changes it;
  - **MCP-native kits:** whatever the server reports;
  - **offline_preflight:** excluded from `measure_sha`.
- **Consequence:** `foilspfbpz_ax`'s board (41 rows, measured at
  1a91751589c1) refuses every launch, which now measures at 28a09663f81f.
  The only difference is the anakit fork commit.

## Design

### Versions are hand-bumped constants

- **anakit:** `version` is `VERSION` (`anakit-adapter/1`).
  - The fork commit leaves the version and goes into each step's record
    and the results metadata as `build`.
  - A step submitted under one version is refused at `results` by another,
    as today (`rec["version"]`).
  - The adapter still refuses when the fork checkout moved under a running
    server (its existing open-commit check). That check is about which
    code the server runs, not about the measurement.
- **beamkit:** `version` is `f"{VERSION}+fom{FOM_VERSION}"`
  (`beamkit-adapter/1+fom1`). The server version goes into the results
  metadata as `server`. `start()` still asks the server for its version
  and refuses one that reports none.
- **Unchanged:** prodtools, offline_preflight, and MCP-native kits (the
  server's reported version is that server's own hand-set number).
- **The bump rule is written down:**
  - in each adapter's `VERSION` comment;
  - in the wiki, as "bump when a step would measure anew; for anakit,
    whenever a fork change alters what an analysis computes";
  - in `mode_specs/README.md` next to the board rule.

### `core/measure.py`: one place decides

Stdlib only, no `modes`. It holds:

- **`class MixedBuilds(ValueError)`.**
- **`recorded_versions(records) -> {kit: version}`:** today's
  `score.kit_versions`. Steps of one kit recorded at two versions raise
  `MixedBuilds`.
- **`point_versions(study, current, adopted=None) -> (versions,
  problems)`:** today's `contract.board_versions`. `current` is
  `{kit: running version}` and `adopted` is `{step: record}` for a resumed
  point.
- **`board_problems(study, board, versions) -> problems`:** today's
  `contract.board_problems`. It compares the board's effective shas (see
  "Aliases") with `study.measure_sha(versions)`.
- **`hand_version(kit, version) -> str`:** the version with any
  `+<kit>-<build>` segment removed, so an old-scheme string reads as its
  hand part:
  - `anakit-adapter/1+anakit-1f831a1` becomes `anakit-adapter/1`;
  - `beamkit-adapter/1+beamkit-0.5.1+fom1` becomes
    `beamkit-adapter/1+fom1`.
  - It is used only by re-stamping.

`score` calls `recorded_versions`, and turns `MixedBuilds` into its
`ScoreError`. `contract.launch_problems` calls `point_versions` and
`board_problems`. The late import and the cycle go.

`contract.board_problems`, `contract.board_versions` and
`score.kit_versions` are deleted. Tests that called them call
`core/measure.py`.

### Aliases: re-stamping an old board

- **The alias file.** A board has an optional
  `<board file>.measure_alias.jsonl`, appended to and never rewritten.
  - Each line reads `{"from": old_sha, "to": new_sha, "study", "by",
    "time", "why", "from_versions", "to_versions"}`.
  - `Leaderboard.measure_aliases() -> {old: new}`.
  - `measure_shas()` returns the effective shas (aliases applied), and
    `_is_new_row` compares effective shas.
  - The rows themselves are never edited: the board stays append-only.
- **`Leaderboard.add_alias(line: dict)`** appends one line under the
  board's exclusive lock. It refuses a `from` that is already aliased, and
  a chain (a `to` that is itself a `from`).
- **`python -m graph.restamp_board --study <name> --why "<text>"
  [--confirm]`:**
  - **Current versions:** it opens the study's step kits through `KitSet`
    and reads `kit.version`. A kit that does not start is a refusal
    (exit 2).
  - **What to re-stamp:** each effective board sha other than
    `study.measure_sha(current)`. For each one it must prove that only the
    kits' build parts differ:
    - find a board row with that sha whose point folder
      (`PointDir.of(GRID_DATA_ROOT, row.config)`) has every step's results
      record;
    - take the recorded versions (`recorded_versions`) and require
      `study.measure_sha(recorded) == old_sha`. That shows the study's
      measure basis is the one the row was measured under;
    - require `hand_version(kit, recorded[kit]) == current[kit]` for every
      kit, so no hand bump lies between them.
  - **Refusals, naming why:**
    - no row of that sha has its records on disk;
    - the basis changed (start a new board);
    - a kit's hand version changed (a deliberate bump; start a new board).
  - **Without `--confirm`** it prints the plan: each old sha, its proof
    row, the old and new versions, and the alias it would write. Exit 0
    when every sha is provable, 2 otherwise. Nothing is written.
  - **With `--confirm`** it writes one alias line per old sha, with `by`
    set to `$USER` and `why` from `--why`.
  - **Nothing to do** (the board is empty or already current) prints so
    and exits 0.

### Records keep the build

- **Step records:** each step's `metadata` carries the build (anakit
  `build`, beamkit `server`), so a row can still be traced to the exact
  fork commit or server.
- **The scheduler's step record is unchanged:** `kit_version` is still
  `kit.version`.

## Errors

- **A malformed alias file** raises `LeaderboardError`, naming the file
  and line, in every reader: launch check, append, re-stamp. An alias
  never fails silently.
- **`restamp_board`:** every refusal names the sha, the proof row (or its
  absence) and the reason. A write failure raises.
- **`MixedBuilds`** at score is a `ScoreError` (`broken.txt: score: ...`),
  as today.

## Testing

- **`tests/test_measure.py`:**
  - `recorded_versions`, and `MixedBuilds` on two versions of one kit;
  - `point_versions`:
    - fresh: the current versions;
    - all of a kit's steps adopted: the recorded version is kept;
    - a kit adopted in part at another version: a problem;
  - `board_problems`:
    - an empty board;
    - a matching board;
    - another sha;
    - another sha with an alias to this one, which matches;
  - `hand_version` on the old anakit and beamkit strings and on a new
    one, which is unchanged.
- **`tests/test_leaderboard.py`:**
  - `add_alias` then `measure_shas()` maps;
  - an append at the new sha onto a board of old-sha rows plus their
    alias succeeds, and without the alias it raises `MeasureMismatch`;
  - a second alias from the same sha is refused, and so is a chain;
  - a malformed alias line raises, naming the file.
- **`tests/test_restamp_board.py`** (toy study, sandbox data root):
  - a board of rows measured with old-scheme versions (records on disk
    under `GRID_DATA_ROOT`) gives a dry run that plans one alias and
    writes nothing;
  - `--confirm` writes it, and a `graph.run` launch on that board then
    passes the launch check;
  - refused: the basis changed, a hand bump, no records on disk;
  - an already-current board is "nothing to do".
- **Kit tests:**
  - the anakit version no longer contains the commit, and `build` is in
    the results metadata;
  - the beamkit version is `beamkit-adapter/1+fom1`, and `server` is in
    the metadata.
- **Contract and score tests** move from the deleted functions to
  `core/measure.py` and keep their assertions.
- **Measurement fingerprints:**
  - every study's `measure_basis_sha` is unchanged;
  - `measure_sha` changes exactly for the `_ax` studies (anakit) and
    `ptg4bl` (beamkit).
- **Acceptance:**
  - `restamp_board --study foilspfbpz_ax` (dry run) on the live board
    proves its 41 rows and plans one alias. `--confirm` only with the
    operator's OK;
  - after that, a `graph.closed_loop --check-only` on `foilspfbpz_ax`
    passes the board check;
  - the same dry run for `ptg4bl` (board `leaderboard_bo_ptg4bl_5k.tsv`)
    and for any other `_ax` board with rows.

## Out of scope

- per-analysis versions inside the anakit fork;
- versions for MCP-native kits beyond what their server reports;
- the kit interface work (survey items 4 to 6).
