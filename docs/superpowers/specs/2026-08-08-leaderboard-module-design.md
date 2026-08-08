# Leaderboard module — design spec (2026-08-08)

Candidate #1 of `docs/architecture-review-2026-08-08.md`: make the Leaderboard
a deep module that owns the row schema as an invariant, instead of a pair of
format/parse functions plus silent `except: continue` guards. Approved
decisions (brainstorm 2026-08-08):

1. **Archive the Python-mode adapters first** (review candidate #7, Phase 0
   below). The module supports exactly one row shape.
2. **Header mismatch = fail loud + quarantine.** Reads hard-error; appends
   save the row to a quarantine file, then raise. Never a silent 0-row
   history, never a lost eval.
3. **The module owns the pending TSV too.** Same invariants; rows older than
   48 h trigger a loud warning at load; deletion only via an explicit prune
   command.

Motivating incidents: `touched-leaderboard-headerless-history-loss`
(foilspfbw01, 2026-08-07 — headerless file → silent GP cold-start),
the `remove_pending` header-fusion bug (tombstone comment at
`bo_driver.py:328-342`; lost a finished 3.5 h eval, foilsflash24R00_00,
2026-07-26), and the never-GC'd stale pending rows found in the review.

## Scope

- **In:** `core/leaderboard.py` (new), Phase-0 archive cut, `BOMode`
  delegation, `pending-prune` CLI verb, `tests/test_leaderboard.py`,
  a permanent header-validation test over the tracked live files.
- **Out (explicitly):** migrating `graph/closed_loop.py`'s
  `_leaderboard_names`/`_leaderboard_len` helpers (review #2c — five-line
  follow-up once this lands); auto-expiry of pending rows; schema
  migration tooling (mismatch = refuse, not migrate); any change to the
  on-disk formats.

## Phase 0 — archive the Python-mode adapters

Delete, following the michael/helical/ipa retirement precedent ("code
retired, leaderboard frozen"):

- `core/bo_driver.py`: `FoilsMode`, `FoilsFracMode`, `FoilsGroupMode`,
  `ProdTargetMode`, `ProdTarget6DMode` (region :351-1142) and their `MODES`
  registry entries. Interface shrink: `parse_geom` abstract slot deleted;
  `load_priors` becomes a concrete default returning `[]`; `JsonMode`'s
  pending-based `x_for_evaluate` becomes the base implementation (the
  geometry-round-trip fallback dies with `parse_geom`); the
  `format_row`/`load_history_row` override hooks go (uniform 4-column
  metric tail, enforced by the new module).
- `core/modes.py`: `SPECS` entries `foils`, `foilsf`, `foilsg`,
  `prodtarget`, `prodtarget6d`, plus constants only they referenced.
- `core/pipeline.py`: `cmd_harvest_pot_only` and the `harvest-pot-only`
  verb dispatch (verified: only prodtarget/prodtarget6d declared it; all 11
  JSON specs use `"harvest"`), plus `pot_only`-stage plumbing reachable only
  from it.
- `core/mode_json.py`: the `PYTHON_MODE_LEADERBOARDS` block (:65-76) and its
  consumer (:503).
- `graph/state.py`: deleted modes leave the mode Literal.
- Preflight/`bo_driver` mode tuples and any `*_BY_MODE` remnants naming the
  deleted modes (grep sweep — cf. the `preflight-mode-tuple` incident class).
- `tests/`: cases exercising the deleted modes; the ModeSpec-completeness
  test shrinks automatically.
- **File deletions (explicit step, operator-visible in the plan):** the
  fossil pending files `pending_bo_{foils,foilsf,foilsg,prodtarget,prodtarget6d,helical,ipa}.tsv`.
  All frozen `leaderboard_*.tsv` files are KEPT as the historical record.
- Wiki: project pages for the archived modes get a status note; log bullet.
  (Wiki edits stay uncommitted per project convention.)

## The module — `core/leaderboard.py`

Stdlib-only (`csv`, `json`, `fcntl`, `time`, `os`, `dataclasses`,
`pathlib`), no imports from other project modules — everything it needs
arrives via the constructor, so the botorch venv and tests import it with no
path games.

### Construction

```python
@dataclass(frozen=True)
class Leaderboard:
    path: Path            # the leaderboard TSV
    name: str             # mode name (derives pending path)
    knob_names: tuple[str, ...]
    knob_fmts: tuple[str, ...]
    metric_cols: tuple[str, str, str, str]   # (sob-like, calo-like, "alpha", "obj")

    @classmethod
    def from_spec(cls, spec) -> "Leaderboard": ...
```

`from_spec` reads `spec.leaderboard`, `spec.name`, `spec.knob_names`,
`spec.knob_fmts`, `spec.metric_cols`. The constructor validates
`len(metric_cols) == 4` (the guard currently inline in `format_row`) and
knob names/fmts lockstep — a bad spec fails at construction, not at append.

`Point` (cfg, x, sob, calo, extras, `obj(alpha)`) moves here **verbatim**;
`bo_driver` re-imports it under the old name (`from leaderboard import
Point`) so `botorch_predict` and tests are untouched.

### History API

- `header() -> str` — the one canonical line:
  `"config\t" + knobs + "\t" + metric_cols + "\n"`.
- `load() -> list[Point]` — missing file → `[]`. Otherwise, under the shared
  lock: line 1 must equal `header()` (modulo trailing newline) or
  **`SchemaMismatch(path, expected, found)`** is raised; each data row
  parses via `metric_cols[0]`/`[1]` (no hardcoded `"sob"` — mode_json's
  `columns[0] == "sob"` rule becomes belt-and-braces, not load-bearing) or
  **`RowParseError(path, line_no, cause)`** is raised. The
  `except (KeyError, ValueError): continue` guards are deleted.
- `append(point: Point, alpha: float) -> None` — under the exclusive lock:
  file absent → write header + row; present → verify line 1; on mismatch,
  append the row to the quarantine file **first**, then raise
  `SchemaMismatch`. Row format unchanged
  (`{sob:.5f}\t{calo:.5e}\t{alpha:.3f}\t{obj:.5f}`).

Quarantine file: `<path>.quarantine.tsv` (e.g.
`leaderboard_bo_foilspfbpz.tsv.quarantine.tsv`), created with the canonical
header on first use, append-only, never read by the system — operator
recovery material.

### Pending API

Pending path rule unchanged: `path.parent / f"pending_bo_{name}.tsv"`;
header `config\tx\talpha\tsubmitted_at`.

- `pending_add(name, x, alpha)` — unchanged behavior (JSON-encoded x via
  the existing scalar coercion, epoch timestamp), plus the header check on
  existing files (mismatch → quarantine + raise, same as history).
- `pending_load() -> list[tuple[str, list]]` — strict parse (same error
  types). After parsing, any row with `now - submitted_at > 48 h` produces
  one loud stderr block listing `name, age_h` per stale row and the prune
  command to run. Warning only — the rows are still returned.
- `pending_remove(name) -> bool` — moved verbatim, including the
  trailing-newline invariant and its incident tombstone comment.
- `pending_prune(older_than_h: float = 48.0) -> list[str]` — under the
  exclusive lock, rewrite the file without rows older than the threshold
  (preserving the newline invariant); returns removed names. Never called
  automatically.

### Errors

`LeaderboardError(RuntimeError)` base; `SchemaMismatch` carries
`path/expected/found`; `RowParseError` carries `path/line_no`. Messages name
the file, both header lines, and — for appends — the quarantine path where
the row was saved.

### Locking

`_flock_sh`/`_flock_ex` move into the module unchanged (shared-read /
exclusive-write on the target file; same semantics `bo_driver` has today).

## BOMode delegation

`BOMode` gains a cached `self._lb = Leaderboard.from_spec(self.spec)`;
`load_history`, `append_history`, `load_pending`, `append_pending`,
`remove_pending`, `pending_path` become one-line delegations with unchanged
signatures. `format_row` and `load_history_row` are **deleted from `BOMode`
entirely** — row rendering/parsing lives only inside the module, and tests
that used them (e.g. the `test_modes.py` round-trip) move to the module's
`append`/`load` API. **Zero changes in `graph/` or `core/botorch_predict.py`**
— they already call through `bo.MODES[mode]`.

## CLI

New `bo_driver.py` verb: `--mode <m> pending-prune [--older-than-hours 48]`.
Prints the removed names (or "nothing stale"). This is the explicit operator
command the stale-row warning points at.

## Testing

New `tests/test_leaderboard.py`, real temp files, no mocks:

1. Round-trip: `append` → `load` returns the Point; file's line 1 equals
   `header()`.
2. **Touch-incident regression:** empty existing file → `append` treats it
   as headerless (mismatch path), `load` raises `SchemaMismatch` — never a
   silent `[]` with rows present. (An empty 0-byte file: `load` raises,
   `append` refuses + quarantines — a `touch`-ed file is corrupt, full stop.)
3. **Fusion regression:** a file whose line 1 is header+row fused (real
   bytes from the incident) → `SchemaMismatch`, not 0 rows.
4. Malformed data row → `RowParseError` with the right line number.
5. Mismatch on append → row present in quarantine file, exception raised,
   main file unmodified.
6. Pending: add/load/remove round-trip; stale row (backdated timestamp)
   warns on load and is removed by `pending_prune`; fresh rows survive
   prune; newline invariant after removing the last row (regression for the
   fusion bug's cause).
7. Two-process flock smoke (writer blocks reader), mirroring the existing
   WAL-stress pattern.

Permanent invariant test (new): for every mode in `SPECS`, if its tracked
leaderboard/pending file exists in `leaderboards/`, its line 1 passes the
module's header check — the pre-landing safety check, kept forever so a
future schema drift is caught in the suite, not mid-campaign.

Existing suite: tests for deleted modes removed; everything else must pass
unmodified (`PYTHONPATH= .venv/bin/python -m unittest discover -s tests`).

## Rollout

- **Nothing lands while foilspfbpz01 is in flight** — children re-import
  `core/` fresh each wave. Land at drain.
- Two commits on a branch: Phase 0 (archive cut), then the module + tests +
  delegation + CLI.
- Before merging: run the live-file header check and the full suite; verify
  `graph/` diff is empty.

## Success criteria

- A header that disagrees with the ModeSpec is a loud, named error at the
  first read or write — demonstrated by the touch- and fusion-regression
  tests.
- An eval's row cannot be lost to a schema error (quarantine test).
- Stale pending rows are visible (warning) and removable (prune), never
  silently influential.
- Test suite green; `graph/` untouched; on-disk formats byte-identical for
  healthy files.
