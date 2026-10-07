# The `_ax` studies and `ce_chain` on Michael's analyses — design

Date: 2026-10-07. Status: draft for the operator's review.

## Why

Our anakit fork carries three analyses: `ce_sensitivity`,
`flash_edep_per_pot` and `nts_momentum`. They do physics that M.
MacKenzie's analysis-mcp-server now does itself. Two changes make it
possible to drop them:

- `params_from` (merged 5faa629) lets one step's number feed the next
  step's param, so his separate tools can be chained step by step.
- His main branch has the fixes from PR #3 (the acceptance counts
  selected events) and PR #4 (signal = R_μe × captures per stop). The
  fork still has the old 2.7× signal overcount.

The goal is that physics lives only in his repo, and this repo only
wires numbers between steps.

## 1. Where the analyses run: the `SimJob MDC2025ay` Musing

Michael's `edep` needs the EdepAna that ships in Offline v13_39_00
(MDC2025ay or later), because it reads the `EDepAna/tree` that EdepAna
writes. Our work area `autoresearch_muse_ax` has an older EdepAna (a
Mu2eOptAna build), which writes no tree.

- The study setting changes from `kits.anakit: {"work_area": <path>}`
  to `{"musing": "SimJob MDC2025ay"}`. The adapter starts the server
  with `--musing` instead of `--work-area`.
- **The grid jobs stay on MDC2025ax** (`Code_mdc2025ax.tar.bz2`, no
  change). Only the analyses run on MDC2025ay. Checked on 2026-10-07:
  MDC2025ay's EdepAna reads an MDC2025ax CeEndpoint file, and the tree
  agrees with its own printed summary (75,000 generated, 39,152 seen).
  TargetStops and early-flash files have not been checked yet; see
  "Checks", step 1.
- **The adapter loses its work-area checks.** `backing_problem` compared
  the work area's backing with the code tarball's, and `code_commit`
  recorded Mu2eOptAna's commit. Neither has anything left to check. A
  step's `anakit_result.json` records the Musing in their place.
- `autoresearch_muse_ax` stays on disk, unused.

## 2. The anakit checkout: Michael's `main`

- `$AUTORESEARCH_ANAKIT` (the `activate.sh` default,
  `../analysis-mcp-server`) checks out
  `michaelmackenzie/analysis-mcp-server` `main`, pinned at `3ba8d23`
  (today's tip). The fork's `autoresearch` branch stays as the record of
  the retired analyses. Nothing runs from it.
- **Pull rule.** Pull only on purpose. Read the diff of the analyses the
  studies use, and bump the adapter's `VERSION` if their numbers change.
  This is the rule we already follow for the fork.
- `VERSION` goes from `anakit-adapter/1` to `anakit-adapter/2`.
- `kits.toml [servers.anakit]` adds `OPENBLAS_NUM_THREADS = "1"` and
  `OMP_NUM_THREADS = "1"`, as his `AGENTS.md` asks. The Python stays
  ana 2.7.0, because his `pyproject.toml` pins `mcp<2`.
- `QUICKSTART.md` clones his repo instead of the fork.

## 3. The seven `_ax` studies

The three prodtools steps are unchanged. The two anakit steps become
four, the same in all seven studies:

| step | analysis | `files_from` | settings |
|---|---|---|---|
| `stops` | `muon_stop_rate` | `mubeam` | `upstream_eff` 0.01278168 (was `input_correction`) |
| `ce_edep` | `edep` | `mustops_ce` | — |
| `sob` | `approx_ce_sensitivity` | `ce_edep` | `params_from` `{"stops_per_pot": "stops.stops_per_pot"}`; `cosmic_rate_per_s_per_mev` 0.0018181818181818182 |
| `flash` | `edep` | `elebeam_flash` | — |

**Objectives.**

- `sob` reads `sob.sensitivity` (it was `sob.s_over_sqrt_b`).
- `flash_edep` reads `flash.avg_trk_edep_per_gen_event_mev`. That is
  MeV per generated beam electron, not per POT. The engine does no
  arithmetic, so the unit change moves into the budget instead:
  - The constraint max becomes 6.50684e-07 × 11.536718606512062 =
    **7.506758e-06**.
  - Under the log10 transform this is only a constant shift, so the GP
    and the pickers see the same surface.
  - The name `flash_edep` stays. The board header and the study `note`
    give the unit.
- Noise:
  - `flash_edep` keeps 0.01 (it is in log10, so relative).
  - `sob` noise is 0.006 scaled by new sob / old sob at the check point
    (about 0.0021). This is provisional until replicates re-measure it.

**Dropped settings.**

- `dio_fraction`: Michael fixes 0.391.
- `dio_table`: he reads his own copy of the table.
- `pot_per_electron`.
- `input_correction`: renamed `upstream_eff`.

**Kit declaration** (`core/kit_registry.py`):

- `anakit.study_keys` = `{"musing": string}`.
- `fixed_keys` = `analysis`, `upstream_eff`,
  `cosmic_rate_per_s_per_mev`, `trigger_paths`.
- Old keys are refused at load.

**New boards.** Each study writes
`leaderboards/leaderboard_bo_<study>_upstream.tsv`. Study names do not
change. The old boards stay as files, as history. They are not mixed
in.

**What happens to the numbers.**

- sob falls to about 0.35 × its old value. On one real file it went from
  3.86 to about 1.35:
  - the signal fix multiplies it by 0.371 everywhere;
  - counting only selected events lowers it about 6% more.
- The signal factor is a constant, so it does not reorder geometries.
  The acceptance change may reorder them a little.

## 4. `ce_chain`

- The `plot` step runs `trigger_efficiency_ntuple` on the `nts` files,
  with `trigger_paths` "apr_TrkDe_80m70p, cpr_TrkDe_80m70p" (the example
  in his docs). Both branches are in our ntuple: cechainL01 has 56
  `trig_` branches.
- The objective is `n_selected`, the number of events with a good
  downstream e- track under his default selection. Extra metrics are
  `efficiency`, `n_triggered` and `n_events`.
- **Caveat:** the ntuple is the triggered stream
  (`CeEndpointOnSpillTriggered`), so every event already passed some
  trigger. The efficiency is conditional on that, so this study checks
  the chain's plumbing. It does not measure trigger efficiency.
- Without `nts_momentum`, the median |p| sanity number goes away.
- `kits.anakit` = the Musing. The board is
  `leaderboard_ce_chain_upstream.tsv`.

## Not in scope

- **Running the grid jobs on MDC2025ay.** That needs our patched Offline
  (holeRadii, the IPA absolute position) rebuilt on it.
- **Sophie Middleton's `fullsim.sensitivity`.** It needs mixed,
  reconstructed CE EventNtuples and SAM provenance, and our per-point
  files are neither.
- **Changes in Michael's repo.** A note for him, not blocking:
  `approx_ce_sensitivity` reads the DIO table from his personal area.
- **Re-measuring the flash budget on the deployed geometry**, unless
  check 1 shows that the new flash differs from the old one.

## Checks before acceptance

1. **Re-analyse an old point without the grid.** `bpzax01R12_00` still
   has all 130 files. Run the four new anakit steps on them through the
   engine, in a sandbox data root holding copies of the point's
   prodtools step records, so only the anakit steps run. Pass
   conditions:
   - **stops:** `stops_per_pot` = 296174 / 3e6 × 0.01278168 =
     1.2618671e-03, exactly (the same counts).
   - **flash:** `avg_trk_edep_per_gen_event_mev` = 6.58426068582917e-06,
     to 1e-5 relative. If it is off, stop and report, because the budget
     then needs re-measuring.
   - **sob:** it equals `approx_ce_sensitivity` run by hand on the same
     ntuple with the same `stops_per_pot`. Record new/old (expected
     about 0.35).
2. **The launch check.** `check_study` passes on all eight studies. The
   launch check now reads his catalogue for the parameters, the
   required ones and the metrics.
3. **`ce_chain` locally.** One local run lands a row.
4. **One grid point.** A `foilspfbpz_ax` point runs end to end and lands
   a row on the new board. This step submits grid jobs, so it needs the
   operator's OK.

## Tests

- **Adapter:**
  - the server gets `--musing`;
  - there is no backing check and no `code`;
  - the result records the Musing;
  - `VERSION` is 2.
- **Registry:** the new anakit keys are accepted, and the old ones are
  refused.
- **Studies:**
  - the seven `_ax` studies have the four steps in the table, the `sob`
    `params_from` and the new board names;
  - the pinned `measure_basis_sha` change for the eight studies, and
    `ptg4bl`'s is unchanged.
- **Fake catalogue** (`tests/fakeanakit.py`): it mirrors his four
  analyses (names, parameters with required/minimum/maximum, metrics,
  `input_kind`). The launch check refuses a missing `upstream_eff`, and
  `stops_per_pot` through `params_from` satisfies the parameter.
- **anakit to anakit:** one step's result file (the ntuple) is the next
  step's input.

## Docs

- `wiki/external/anakit.md` is rewritten: Michael's `main`, the Musing,
  the retired fork.
- `wiki/drivers/contract-engine.md` and `CONTEXT.md`: "fork commit"
  becomes "checkout commit".
- Updates to `wiki/index.md`, a `wiki/log.md` bullet,
  `mode_specs/README.md` and `QUICKSTART.md`.
