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
    the launch check, with a late import of score that no longer guards
    any cycle (score imports only leaderboard and point_dir since
    d42679e);
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
- **Live data (read-only check, 2026-10-05):**
  - **foilspfbpz_ax:** all 41 rows have every step's results record. They
    were recorded at `{anakit: anakit-adapter/1+anakit-60cb434419a2,
    prodtools: prodtools-adapter/1}`, and `study.measure_sha(recorded)`
    reproduces 1a91751589c1 with today's study file.
  - **ptg4bl_5k:** all 29 rows reproduce 8dfb8e3a7fae from
    `beamkit-adapter/1+beamkit-0.5.1+fom1`.
  - **Other boards:** no other `_ax` board has rows, and there is no `_ax`
    archive and no quarantine file.
  - **Fork history:** the fork moved 60cb434 → 1f831a1 in three commits.
    Two refactors of `ce_sensitivity.py` and `flash_edep_per_pot.py`
    change no numbers; the third adds `nts_momentum`.

## Design

### Versions are hand-bumped constants

- **anakit:** `version` is `VERSION` (`anakit-adapter/1`).
  - **The build is recorded at submit.** The fork commit read at submit is
    written into the step's `anakit_result.json` as `build`. `results`
    reports that recorded `build` in the metadata, not the commit the kit
    reads now.
  - **The moved-commit refusal (anakit.py:223-234) is dropped.** Every
    submit starts its own analysis server from the checkout, so that
    check only kept the version label right. Kept, it would let an
    unrelated fork commit break every later anakit step of a campaign:
    the failure this design ends.
  - **Two refusals stay:** a dirty checkout (`fork_commit`), and a step
    whose recorded `version` differs at `results` (a hand bump between
    submit and results).
- **beamkit:** `version` is `f"{VERSION}+fom{FOM_VERSION}"`
  (`beamkit-adapter/1+fom1`).
  - The server version is stored in the step record
    (`state/<step>_beamkit.json`) at submit and reported as `server` in the
    results metadata.
  - `start()` still asks the server for its version and refuses one that
    reports none.
- **Unchanged:** prodtools, offline_preflight, and MCP-native kits (the
  server's reported version is that server's own hand-set number).
- **The bump rule is written down:**
  - in each adapter's `VERSION` comment;
  - in `wiki/external/anakit.md` and the contract-engine wiki page, as
    "bump when a step would measure anew; for anakit, whenever a fork
    change alters what an analysis computes";
  - in `mode_specs/README.md` next to the board rule;
  - and the index line "any fork commit changes every _ax measure_sha" is
    corrected.

### `core/measure.py`: one place decides

Stdlib only, no `modes`. It holds:

- **`class MixedVersions(ValueError)`.**
- **`recorded_versions(records) -> {kit: version}`:** today's
  `score.kit_versions`. Steps of one kit recorded at two versions raise
  `MixedVersions`.
- **`point_versions(study, current, adopted=None) -> (versions,
  problems)`:** today's `contract.board_versions`.
- **`board_problems(study, board, versions) -> problems`:** today's
  `contract.board_problems`.
- **`hand_version(kit, version) -> str`:**
  - for `anakit` and `beamkit` only, it removes the old-scheme build
    segment (`+anakit-<build>`, `+beamkit-<build>`), so
    `anakit-adapter/1+anakit-60cb434419a2` reads as `anakit-adapter/1` and
    `beamkit-adapter/1+beamkit-0.5.1+fom1` as `beamkit-adapter/1+fom1`;
  - it refuses (ValueError) a build segment that would leave an unexpected
    `+`;
  - every other kit's version is returned unchanged;
  - it is used only by re-stamping.

`score` calls `recorded_versions` and turns `MixedVersions` into its
`ScoreError`. `contract.launch_problems` calls `point_versions` and
`board_problems`, and the leftover late import goes.
`contract.board_problems`, `contract.board_versions` and
`score.kit_versions` are deleted, and their tests move to `core/measure.py`.

### Re-stamping an old board

`python -m graph.restamp_board --study <name> --why "<text>" [--confirm]`
moves a board's rows to the new fingerprint once, by hand. It edits the
board's `measure_sha` column, under the board's exclusive lock and after a
backup copy. Only two boards (70 rows) need it, so a one-time rewrite is
simpler than an alias that every launch and append would have to read
from then on. The board's other columns, and every row's numbers, are
untouched.

- **Current versions:** it opens the study's step kits through `KitSet`
  and reads `kit.version`. A kit that does not start is a refusal
  (exit 2).
- **What to re-stamp:** every live-board row whose `measure_sha` is not
  `study.measure_sha(current)`, grouped by sha.
- **The proof, for each old sha, using every row of that sha:**
  - the row's point folder (`PointDir.of(GRID_DATA_ROOT, row.config)`) has
    every step's results record;
  - the records' handles equal the row's `handles` column;
  - `study.measure_sha(recorded_versions(records)) == old_sha`: the study's
    measure basis is the one the row was measured under;
  - `hand_version(kit, recorded[kit]) == current[kit]` for every kit: no
    hand bump lies between them.
- **Refusals,** naming the sha, the row and the reason:
  - a row without its records on disk;
  - handles that do not match;
  - the basis changed (start a new board);
  - a hand bump between them (start a new board);
  - rows of that sha in the committed archive board (`leaderboards/`),
    which is never rewritten.
  - All or nothing: one refusal and nothing is written.
- **The dry run (without `--confirm`)** prints, for each old sha:
  - its row count;
  - the old and new versions of each kit, and its old and new build
    (anakit: the fork commit recorded in the rows and the current one;
    beamkit: the recorded and current server version);
  - for anakit, `git -C $AUTORESEARCH_ANAKIT log --oneline <old>..<new> --
    tools/analyses/`, the analysis commits in between, so the operator
    sees what changed before confirming;
  - a warning, not a refusal, when one kit's steps within a point ran on
    different builds.
  - Exit 0 when every sha is proven, 2 otherwise. Nothing is written.
- **`--confirm`,** after the same proof and under the board's exclusive
  lock:
  - copies the board to `<board>.pre-restamp-<UTC time>.tsv`;
  - rewrites the `measure_sha` cell of every proven row;
  - appends one line per old sha to `<board>.restamp.jsonl`: `{study,
    from, to, rows, from_versions, to_versions, from_builds, to_builds,
    by: $USER, time, why, backup}`.
- **Nothing to do** (an empty board, or one already current) prints so and
  exits 0.

### Records keep the build

Each step's results metadata carries the build that computed it: anakit
`build`, recorded at submit; beamkit `server`, recorded at submit. A row
can still be traced to the exact fork commit or server through its
handles. The scheduler's step record is unchanged: `kit_version` is still
`kit.version`.

## Rollout

The deploy itself changes the anakit and beamkit version strings:
- a point already in flight would refuse its adopted steps, or its anakit
  `results`, under the new string;
- closed_loop starts each `graph.run` child from the code on disk.

So:
1. stop any `_ax` or ptg4bl campaign (none runs on 2026-10-05);
2. merge;
3. dry run `restamp_board`, then `--confirm` it with the operator's OK, for
   foilspfbpz_ax and ptg4bl;
4. relaunch.

## Errors

- **`restamp_board`:** every refusal names the sha, the row and the
  reason. A write failure raises, and the backup copy stays; the board is
  replaced atomically (temp file plus rename), so a crash leaves either
  the old board or the new one.
- **`MixedVersions`** at score is a `ScoreError` (`broken.txt: score:
  ...`), as today.

## Testing

- **`tests/test_measure.py`:**
  - `recorded_versions`, and `MixedVersions`;
  - `point_versions`:
    - fresh;
    - all of a kit's steps adopted;
    - a kit adopted in part at another version;
    - a resumed point whose adopted steps carry the old version format,
      refused with a message naming the version change;
  - `board_problems`: empty, matching, other sha;
  - `hand_version`:
    - the old anakit and beamkit strings;
    - a new string, unchanged;
    - another kit, unchanged;
    - a malformed build, refused.
- **`tests/test_restamp_board.py`** (toy-kit study plus a fake anakit
  version, sandbox data root):
  - a board of old-scheme rows with records on disk gives a dry run that
    plans the rewrite, prints the versions and builds, and writes nothing;
  - `--confirm` rewrites the column, writes the backup and the log line,
    leaves every other cell identical, and a launch check on the board
    then passes;
  - refused, writing nothing:
    - the basis changed;
    - a hand bump;
    - a row without records;
    - mismatched handles;
    - archive rows;
    - one bad sha among two (all or nothing);
  - mixed builds within a point warn without refusing;
  - an already-current board is "nothing to do".
- **anakit kit tests:**
  - the version has no commit;
  - `results` with the same hand version but a newer fork commit is
    accepted, with `build` taken from the record;
  - a record of the old version format is refused at `results`;
  - these replace test_anakit_kit.py:125-129 and :402-415.
- **beamkit kit test:** the version is `beamkit-adapter/1+fom1`, and
  `server` comes from the record (replaces test_beamkit_kit.py:432-434).
- **Contract and score tests** move to `core/measure.py` and keep their
  assertions.
- **Fingerprints:**
  - a test pins every loaded study's `measure_basis_sha`;
  - `measure_sha` changes exactly for the `_ax` studies, `ce_chain` (its
    anakit `plot` step) and `ptg4bl`.
- **Acceptance:**
  - `restamp_board --study foilspfbpz_ax` and `--study ptg4bl` dry runs on
    the live boards prove 41 and 29 rows and show the anakit commits in
    between;
  - `--confirm` only with the operator's OK;
  - then `graph.closed_loop --check-only` on foilspfbpz_ax passes the
    board check.

## Out of scope

- per-analysis versions inside the anakit fork;
- versions for MCP-native kits beyond what their server reports;
- the kit interface work (survey items 4 to 6).
