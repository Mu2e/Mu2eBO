# Portable paths — design spec (2026-08-11)

Make the tree stop naming a person. Today ~20 literal
`/exp/mu2e/{app,data}/users/oksuzian/...` paths are spread across 9 modules,
so a second Mu2e operator cannot clone this repo and run their own campaigns:
their code would execute against *these* leaderboards, *these* grid volumes,
and *these* build artifacts.

The hardcoding is historical, not necessary. `git log -S` traces the repo-root
constant to the initial commit `ed93a1c` (2026-05-21), carried unchanged
through the 2026-07-17 `core/` reorg. `core/bo_driver.py` already uses
`Path(__file__).resolve().parent` elsewhere (commit `11293a6`) to locate
`botorch_predict.py`, and `Path(__file__).resolve().parents[1]` from that file
evaluates to exactly the hardcoded root — verified. Our Python never runs on a
grid worker (the shipped artifact is a muse-built `Code.tar.bz2`; workers run
`mu2e`/art), so there is no remote-execution reason to prefer an absolute path.

Approved decisions (brainstorm 2026-08-11):

1. **Target is a second operator running their own campaigns**, possibly
   concurrently with the first — not merely a relocatable tree.
2. **Leaderboards: repo is a read-only archive.** Live rows append to the
   operator's own `/data` area; the committed `leaderboards/` stay in git as
   frozen priors. The loader reads archive + live and concatenates, so a new
   operator starts warm without ever contending for a file.
3. **Artifacts: each operator builds their own**, with a muse-style `backing`
   link so they only build what they need to differ on.
4. **No default backing.** A fresh clone has none and fails loudly, exactly as
   `muse setup` errors when a backing cannot supply the required build.

## Why it looks like Muse

Mu2e's own build system solved this problem, and the mechanics were read from
the implementation (`muse` v4_13_00 on cvmfs) rather than from the wiki prose:

- **Location is identity.** `muse setup` sets
  `MUSE_WORK_DIR=$(readlink -f $PWD)` (`museSetup.sh:169`); every other path is
  derived from it and exported. No user name appears anywhere.
- **`backing` is a symlink, and it chains.** `muse backing <target>` drops a
  symlink named `backing` in the work dir (`museBacking.sh`). At setup, muse
  walks the chain (`museSetup.sh:320-333`) and builds the include/link/fcl/data
  paths from the furthest backing forward, so anything built locally wins by
  link order and everything else falls through to the backing.
- **Setup verifies the backing.** `museSetup.sh:502` hard-errors with
  `backing build area missing required build ($MUSE_STUB)` — at setup time, not
  hours into a job.

We adopt all three ideas. We deliberately do **not** adopt two things:

- **cwd-as-identity.** Muse can use `$PWD` because a work dir is something you
  `cd` into. Our modules are imported by closed-loop children launched under
  `setsid` from arbitrary cwds, by the botorch subprocess, and by the test
  suite. We take the same idea against the *code's* location:
  `Path(__file__).resolve().parents[1]`.
- **A mandatory sourced setup.** Muse can say "muse setup must be run first"
  because everything runs under a shell. Our Python layer must keep working
  when imported with a bare environment, so it derives working defaults on its
  own; the shell layer only overrides and verifies.

## Scope

**In:**

- `core/paths.py` (new) — the single resolver.
- Rewiring the 9 modules that carry literals.
- `${ARTIFACT}` token in `mode_specs/*.json` + loader expansion and validation.
- `core/leaderboard.py` grows a read-only archive source alongside the live file.
- `setup.sh` (new, repo root) — `--status`, `--backing`, sourced export.
- `paths.verify()` wired into `graph/closed_loop.py` startup and
  `bo_driver.py preflight`.
- Tests, including a permanent anti-regression grep.
- README rewrite: the "Portability caveat" section is deleted, not re-worded.

**Out (explicitly):**

- **Artifact reproducibility** — bringing `rebuild.sh`, `stoppingtarget-holeradii.patch`,
  `ipa-zstart.patch`, and the `Code_*.tar.bz2` production recipe into the repo.
  Today those live inside the artifact directory itself and in a comment at
  `core/pipeline.py:395-400`. This is a separate spec (referred to below as
  "spec B"); it is what finally removes the need for a backing at all. This
  spec does not depend on it: with a backing link, a second operator runs today
  with no build.
- **Verifying artifact *contents*.** `verify()` checks that the `musing` and
  `grid_tarball` files exist. It does not check that the tarball actually
  carries the patch — `rebuild.sh` already does that with
  `strings | grep -q "holeRadii vector active"`, and wiring a per-artifact
  expected-marker table belongs with spec B.
- **Moving anything on disk.** The committed `leaderboards/` stay where they
  are; live files start empty on `/data`.
- `wiki/` and `docs/` mentions of `oksuzian` — they are a historical record of
  what actually happened and are left alone.
- The off-repo `mmackenz_table_plots/` generators on `/data` (unversioned,
  outside this repo).
- `graph/closed_loop.py`'s `_leaderboard_names` / `_leaderboard_len` helpers,
  already listed as out-of-scope by the Leaderboard module spec.

## Global constraints

- **Must not land while children are in flight.** Closed-loop children
  re-execute the working tree; `foilspfbpz07` is running as of 2026-08-11.
  Merge at drain.
- The full suite (422 tests) must pass with **no** `AUTORESEARCH_*` variable set
  **and** on a machine where `/exp/mu2e` does not exist.
- Golden geometry parity (`tests/golden_parity.py check`) must still pass.
- Stdlib only in `core/paths.py` — no imports from other project modules, the
  same rule `core/leaderboard.py` already follows, so the botorch venv
  subprocess and the tests import it with no path games.

## The module — `core/paths.py`

### Resolved names

```python
REPO_ROOT      = Path(__file__).resolve().parents[1]      # not configurable
DATA_ROOT      = $AUTORESEARCH_DATA_ROOT      or /exp/mu2e/data/users/$USER
ARTIFACT_ROOT  = $AUTORESEARCH_ARTIFACT_ROOT  or /exp/mu2e/app/users/$USER
BACKING        = readlink(REPO_ROOT/"backing") or $AUTORESEARCH_BACKING or None

GRID_DATA_ROOT      = DATA_ROOT / "autoresearch_grid"
GRAPH_DATA          = DATA_ROOT / "autoresearch_graph_data"
LEADERBOARD_LIVE    = DATA_ROOT / "autoresearch_leaderboards"
```

Leaderboards are reached through two functions rather than a second constant,
because `spec.leaderboard_rel` already carries a directory component
(`"leaderboards/leaderboard_bo_foilspf.tsv"`) and joining it to a
`LEADERBOARD_*` directory would double that component:

```python
def leaderboard_archive(rel: str) -> Path:   # REPO_ROOT / rel  (read-only priors)
def leaderboard_live(rel: str) -> Path:      # LEADERBOARD_LIVE / basename(rel)
```

The live tree is flat, so **`core/mode_json.py`'s leaderboard-uniqueness check
must be tightened from the whole relative path to the basename**: today
`a/x.tsv` and `b/x.tsv` are two distinct declarations that would collide into
one live file. All 11 current specs already use `leaderboards/<name>.tsv`, so
this rejects nothing that exists — it closes a hole the flattening opens.


`REPO_ROOT` is deliberately not configurable: it is not a preference, it is
where the code is. An env override would only ever let the two disagree.

`backing` is already in `.gitignore:70`, so the name is free.

### `artifact(rel) -> Path`

The muse link-order rule in one function:

```python
def artifact(rel: str) -> Path:
    """First of ARTIFACT_ROOT/rel, BACKING/rel that exists; else the
    intended ARTIFACT_ROOT/rel. Never raises."""
```

Local wins, backing fills in, and a miss returns the *intended* path so the
caller's error message names where the operator meant to put it. This is the
only place in the codebase that knows a backing exists.

### `verify(modes) -> None`

The gate. Raises `PathsError` with a remediation command on the first failure:

1. For every registered mode: `artifact(spec.musing)` and
   `artifact(spec.grid_tarball)` exist. Failure names
   `./setup.sh --backing <path>`.
2. `DATA_ROOT` exists and is writable; `GRID_DATA_ROOT`, `GRAPH_DATA`,
   `LEADERBOARD_LIVE` exist or are creatable.
3. Every archive leaderboard that exists has a valid header — delegated to
   `core/leaderboard.py`, which already owns that invariant.

### Resolution never touches the operator's volumes

**Constants are string math over the environment; only `verify()` and
`artifact()` stat DATA_ROOT / ARTIFACT_ROOT.** Import itself does touch the
filesystem twice, and the earlier wording claiming otherwise was wrong (caught
by strace in the Task 1 review): `Path(__file__).resolve()` canonicalises this
file's own location, ~8 lstats, and the `backing` probe is one more. Neither
goes near the operator's volumes, which is the property that actually matters.

This is what keeps the suite green on a machine with no `/exp/mu2e`, and it is
why `artifact()` is total rather than raising: `core/mode_json.py` expands
specs at import, so a raising resolver would explode the moment a spec is
loaded in a bare environment. Loud failure has exactly one home, `verify()`.

One deliberate non-fallback: if `$USER` is unset (cron, service account) and no
override is given, resolution **raises**. `graph/config.py:26` currently does
`os.environ.get('USER', 'autoresearch')` for the checkpoint dir; that fallback
is **not** copied to the data roots, where inventing a path would silently
create a fresh empty tree — the same failure class as
`touched-leaderboard-headerless-history-loss`.

## Migration map

| Site | Today | After |
|---|---|---|
| `bo_driver.py:47`, `harvest.py:64`, `botorch_predict.py:26`, `pipeline.py:965`, `graph/config.py:7` | 5 copies of the repo-root literal | `from paths import REPO_ROOT` |
| `graph/pipeline_io.py:22` | `sys.path.insert(0, "…/autoresearch/core")` | `sys.path.insert(0, str(REPO_ROOT / "core"))` |
| `graph/config.py:16,33` + `bo_driver.py:428,833,850` | 4 copies of two data roots | `GRAPH_DATA`, `GRID_DATA_ROOT` |
| `bo_driver.py:240` | `ROOT / spec.leaderboard_rel` | `leaderboard_live(rel)` + `leaderboard_archive(rel)` |
| 10 × `mode_specs/*.json` (`musing`, `grid_tarball`) | absolute `/exp/…/oksuzian/…` | `${ARTIFACT}/Offline_run1bap_partial/setup_local.sh` etc. |
| `core/pipeline.py:402-404` | Run1BAna lib path + `cd` into `autoresearch_muse` | `artifact("autoresearch_muse")` |
| `tests/golden_parity.py:114`, `tests/test_wal_multiwriter_stress.py:213` | grid / graph-data literals | imported constants |
| `tests/fixtures/modes/foilsflash.json` | absolute paths | `${ARTIFACT}` — the fixture stays a faithful copy of a real spec |
| `requirements.txt` header, `README.md` | `oksuzian` in the venv recipe and campaign commands | `$USER`; portability caveat deleted |

**Deduplication is a real win here, not a side effect.** `bo_driver.py:428,833,850`
each carry their own copy of the grid-data root, which can silently disagree
with `graph/config.py:33`. After this change there is one definition.

### `${ARTIFACT}` expansion

`core/mode_json.py` keeps `musing` and `grid_tarball` required
(`_REQUIRED_SOFTWARE`, :34) and adds one rule: a leading `${ARTIFACT}/` is
expanded through `paths.artifact()`. Two validation errors, both at load:

- An unexpanded `${...}` token that is not `${ARTIFACT}` — unknown variable.
- A bare absolute path under `/exp/mu2e/.../users/<name>/` — rejected with a
  message pointing at `${ARTIFACT}`. This is what stops the hardcode returning
  through a new mode spec.

### Leaderboard: archive + live

`core/leaderboard.py` is constructed today with a single `path`. It grows an
optional `archive_path`:

- **Load** reads `archive_path` (if present) then `path`, concatenating rows in
  that order. Header validation applies to both — a malformed archive fails
  loud rather than silently yielding zero rows.
- **Append** writes only to `path`. The archive is never opened for writing.
- **Pending TSV** behaviour is unchanged; pending is live-only state.

Promotion of live rows into the committed archive stays a manual, reviewed git
commit. There is no automatic write-back — that would put campaign output into
git without review, which the project's conventions forbid.

## `setup.sh`

Repo root. The human-facing skin over the same resolver; mirrors muse's verbs.

```
source setup.sh          # export the resolved roots into this shell
./setup.sh --status      # print the four roots + provenance: default | env | backing
./setup.sh --backing P   # create the `backing` symlink
./setup.sh --backing -r  # remove it
```

Sourcing exports `AUTORESEARCH_DATA_ROOT` and `AUTORESEARCH_ARTIFACT_ROOT` at
their resolved values, which pins them for every child process — a campaign
cannot have its roots shift under it mid-flight.

It deliberately does **not** activate the venv and does **not** touch
`PYTHONPATH`: the test suite depends on `PYTHONPATH=` being empty
(it clears what a sourced Mu2e/cvmfs environment leaves behind), and the script
has one job.

`--status` exists because muse's equivalent (`muse status`) is the thing that
answers "what am I actually running against" in one command, which is currently
unanswerable here without reading source.

## Failure modes

| Situation | Today | After |
|---|---|---|
| Env var / root points somewhere wrong | silently creates an empty tree; a fresh leaderboard lands headerless → `load_history()` returns 0 rows forever, GP cold-starts, `no_row_streak` climbs toward a spurious abort | `verify()` fails at launch with the offending path |
| No backing and artifact missing | mode runs; grid ships the wrong tarball; discovered hours later, or never | error naming the `--backing` command |
| `$USER` unset (cron/service) | `graph/config.py` would fall back to a literal | raises; override required |
| Two operators export the same `DATA_ROOT` | n/a | safe — `Leaderboard` already flocks appends — but their rows pool. Documented, not prevented. |
| A new mode spec pastes an absolute personal path | accepted silently | rejected at spec load |

The first two rows are not hypothetical. `prodtarget-env-divergence` and
`foilsflash-tarball-mode-key-omission` were both "preflight ran against a
patched local environment while the grid shipped an unpatched tarball";
neither survives a gate that resolves both through one function at launch.

## Testing

- **`tests/test_paths.py`** (new), against a tmp tree with monkeypatched env:
  precedence (env beats default), `artifact()` prefers local over backing,
  `artifact()` is total when neither exists, `$USER`-unset raises,
  `verify()` raises with a remediation string when an artifact is missing,
  `verify()` passes when the backing supplies it.
- **`tests/test_no_hardcoded_paths.py`** (new): grep tracked sources under
  `core/`, `graph/`, `tests/`, `mode_specs/` for `users/oksuzian` and fail with
  the offending file:line. `wiki/` and `docs/` are excluded — they are a record
  of what happened, not live configuration. This is the test that stops the
  hardcode growing back.
- **`tests/test_leaderboard.py`** gains: archive+live concatenation order,
  append never touches the archive, a malformed archive header fails loud.
- **`tests/test_mode_json.py`** gains: `${ARTIFACT}` expands; an unknown
  `${VAR}` is rejected; a bare personal absolute path is rejected; two specs
  whose leaderboard paths differ only by directory are rejected as a basename
  collision.
- The existing suite must stay green with no `AUTORESEARCH_*` set. Two files
  need edits to stop reaching for literals: `tests/golden_parity.py:114` and
  `tests/test_wal_multiwriter_stress.py:213`.
- `PYTHONPATH= .venv/bin/python tests/golden_parity.py check` must still pass —
  the geometry renderers do not touch paths, but the harness does.

## Open questions

None blocking. Two things are deliberately deferred to spec B: bringing the
artifact build recipes into the repo, and verifying artifact contents rather
than mere existence.
