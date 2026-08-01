# Run1Bak vs Run1Bap Shift Investigation

## Question
Identical geometry configurations evaluated under two software releases (Run1Bak vs Run1Bap) exhibit measured shifts in `s_over_sqrt_b` (sob):
- **+4.9% at the champion x geometry** (6 configs: foilsflashSOBX01/BASIN01_00/C400_champ and ipafixAB01/ipa625AB01/ipaovrAB01)
- **+4.8% at the deployed-baseline geometry** (2 configs: foilsflashHOLEDhi vs nominalAB01)

This investigation mechanizes the elimination of possible root causes for these shifts.

## 1. Inventory

### Configuration Summary

| config | s_over_sqrt_b | ce_abs_eff | ce_seen | ce_simulated_events | muminus_stops | mubeam_sim_total | stopping_factor | flash_edep_per_pot | flash_edep_events | flash_n_input | flash_n_files |
|--------|---------------|-----------|---------|-------------------|--------------|-----------------|-----------------|-------------------|-----------------|---------------|---------------|
| foilsflashSOBX01 | 3.9 | 0.0006434968099166264 | 512862 | 975000 | 248849 | 2600000 | 0.09571115384615385 | 1.080642573322103e-06 | 78985 | 19250000 |  |
| foilsflashBASIN01_00 | 3.91 | 0.0006448971175792507 | 474026 | 900000 | 229908 | 2400000 | 0.095795 | 1.0803183062259505e-06 | 45302 | 11000000 | 100 |
| foilsflashC400_champ | 3.9 | 0.000644176254979119 | 552746 | 1050000 | 268064 | 2800000 | 0.09573714285714285 | 1.0639969270327796e-06 | 179588 | 44000000 | 400 |
| ipafixAB01 | 4.1 | 0.0006755457577694941 | 580262 | 1050000 | 229532 | 2400000 | 0.09563833333333334 | 1.0358153515168671e-06 | 44625 | 10890000 | 99 |
| ipa625AB01 | 4.11 | 0.0006764205780049471 | 539022 | 975000 | 268031 | 2800000 | 0.09572535714285714 | 1.0326683685261107e-06 | 45056 | 11000000 | 100 |
| ipaovrAB01 | 4.11 | 0.0006758439092087209 | 497236 | 900000 | 229694 | 2400000 | 0.09570583333333334 | 1.0585555617218336e-06 | 44733 | 10890000 | 99 |
| foilsflashHOLEDhi | 3.11 | 0.00040782891755500897 | 530651 | 975000 | 152426 | 2600000 | 0.058625384615384614 | (no flash data) | 101403 | (no flash data) |  |
| nominalAB01 | 3.26 | 0.0004244694268978349 | 595233 | 1050000 | 152312 | 2600000 | 0.05858153846153846 | 6.854431002611723e-07 | 28206 | 11000000 | 100 |

### Artifact Availability
All 8 configurations are fully artifacted:
- `harvest/summary.json`: present for all configs (primary metric source)
- `harvest/edep.log`: present for all configs
- `harvest/rough_run1a_sensitivity.log`: present for all configs
- `harvest/nts.ce.root`: present for all configs
- `harvest/ce_files.txt`: present for all configs
- `state/mustops_ce_template_materialized.fcl`: present for all configs
- `state/mubeam_template_materialized.fcl`: present for all configs

Note: `foilsflashHOLEDhi`'s summary.json lacks `flash_edep_*` fields; all other configs have complete flash metrics.

### Carried Observation from Design
Measured shifts in run1bak vs run1bap across the two geometry pairs (from `harvest/summary.json`):

**At champion x geometry (6 configs):**
- **Stops**: −0.1% (essentially flat)
- **ce_abs_eff**: +4.75%
- **s_over_sqrt_b**: +4.9%

**At deployed-baseline geometry (2 configs):**
- **Stops**: −0.1%
- **ce_abs_eff**: +4.76%
- **s_over_sqrt_b**: +4.8%

**Verdict: Inventory complete; all 8 configs fully artifacted. Ready for mechanized elimination.**

## 2. Normalization audit

### 2.1 Formulas from code (verbatim, line-cited)

All quantities are computed in `cmd_harvest` (`core/pipeline.py:1279-1420`), which
calls into the pure-logic module `core/harvest.py`.

```
stopping_factor = muminus_stops / mubeam_sim_total                          # core/pipeline.py:1331
ce_scale        = RUN1A_MUBEAM_INPUT_CORRECTION * stopping_factor
                    / ce_simulated_events                                    # core/pipeline.py:1332
ce_abs_eff      = ce_seen * ce_scale                                         # core/pipeline.py:1333
```

- `RUN1A_MUBEAM_INPUT_CORRECTION = 0.01278168` — `core/harvest.py:30`.
- `mubeam_sim_total = len(mubeam_files) * _events_per_job("mubeam")` —
  `core/pipeline.py:1313-1314`, where `mubeam_files = hv.read_outputs(STATE,
  "mubeam")` (`:1313`).
- `ce_simulated_events = len(ce_files) * _events_per_job("mustops_ce")` —
  `core/pipeline.py:1315`, where `ce_files = hv.read_outputs(STATE,
  "mustops_ce")` (`:1301`).
- `ce_seen, nts_path = hv.run_edepana(harvest_dir, ce_files, runner=...)` —
  `core/pipeline.py:1324-1325`; `run_edepana` (`core/harvest.py:69-95`) writes
  `harvest/ce_files.txt` from that **same** `ce_files` list, runs EdepAna, and
  parses `ce_seen` via `parse_edepana_saw` (`core/harvest.py:44-49`) against
  `EDEP_SAW_RX = re.compile(r"EdepAna summary:\s*Saw\s+([\d.eE+-]+)\s+events")`
  (`core/harvest.py:35`, `int(float(...))` — the scientific-notation guard
  from wiki incident `edepana-saw-events-scientific-notation-parse`).
- `muminus_files, muminus_source = hv.resolve_muminus_inputs(STATE)` —
  `core/pipeline.py:1307`, defined at `core/harvest.py:166-200`.
  `muminus_stops = sum(_count_events_art(f, env, harvest_dir) for f in
  muminus_files)` — `core/pipeline.py:1329`; `_count_events_art`
  (`core/pipeline.py:1167-1186`) parses `TrigReport Events total =\s*(\d+)`
  (`:1183`) from a `mu2e -n -1` dump of each file.
- `s_over_sqrt_b = hv.run_sensitivity_macro(harvest_dir, nts_path, ce_abs_eff,
  runner=_root_runner)` — `core/pipeline.py:1346`. The macro driver
  (`core/harvest.py:98-120`) runs
  `Run1BAna/workflows/scripts/rough_run1a_sensitivity.C` (path built at
  `core/harvest.py:66`, `SENSITIVITY_MACRO`) via `root -q -b -l
  scripts/rough_run1a_sensitivity.C("<nts_path>", <ce_abs_eff>,
  "<harvest_dir>")`, and parses the returned sob from the stdout line matching
  `S_OVER_SQRTB_RX = re.compile(r"^Signal box.*S/sqrt\(B\)\s*=\s*([\d.eE+-]+)\s*$",
  re.MULTILINE)` (`core/harvest.py:36-37`).

**Key semantics question — landed vs. submitted.** All three of
`mubeam_sim_total`, `ce_simulated_events`, and `ce_seen` are **LANDED-file**
based, not submitted-job based, by explicit design:

- `mubeam_files`/`ce_files` come from `hv.read_outputs(STATE, stage)`
  (`core/harvest.py:143-152`), which reads `state/<stage>_outputs.txt` — the
  list of files a prior `list-outputs` glob actually found on `/pnfs`, i.e.
  landed output, never `STAGES[stage]["njobs"]`. `core/pipeline.py:1309-1312`
  states the rationale explicitly: *"Derive denominators from the actual
  files we'll harvest, not STAGES.njobs — if any grid jobs were lost (OOM,
  held), STAGES.njobs over-counts and biases ce_abs_eff / s_over_sqrt_b high
  by the loss fraction. See A/B test on helical001 (2026-05-16)."*
- `ce_seen` is EdepAna's count over that **same** `ce_files` list — i.e. the
  numerator and denominator of the `ce_seen/ce_simulated_events` term are
  drawn from the identical landed population by construction, so job loss at
  the `mustops_ce` stage cancels rather than biasing the ratio.
- `muminus_stops`'s population depends on `resolve_muminus_inputs`
  (`core/harvest.py:166-200`), decision order: stage-chain stamp
  (`state/stage_chain.txt`) first, else `concat_outputs.txt` presence for
  pre-stamp legacy configs (`:178-182`). Two cases arose across the 8 configs
  (§2.2): **concat-based** (`source="concat"`, one merged
  `MuminusStopsCat` file) and **concatless** (`source="mubeam"`, the raw
  `TargetStops` files, one per landed mubeam job). In the concatless case the
  population is *literally* `state/mubeam_outputs.txt` filtered for
  `TargetStops` (`core/harvest.py:194-200`) — the same landed list used for
  `mubeam_sim_total`. In the concat case, `cmd_submit`'s `concat` branch
  builds its merge-job input list directly from `state/mubeam_outputs.txt` at
  concat-submit time (`core/pipeline.py:948-953`), so the merged file's stop
  count reflects the same landed-mubeam population *as long as
  `mubeam_outputs.txt` was not re-globbed larger after concat consumed it* —
  verified per-config in §2.2.

### 2.2 Recompute and closure (Step 2/3)

`$SCRATCH/recompute.py` parses, per config, directly from
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/<config>/{state,harvest}/`
(never `summary.json`): `ce_seen` from `harvest/edep.log` (`EDEP_SAW_RX`),
`muminus_stops` summed across every `harvest/count_sim.*.log`
(`TrigReport Events total =\s*(\d+)`), landed-file counts (`wc -l` equivalent
on `state/mubeam_outputs.txt`, `state/mustops_ce_outputs.txt`,
`harvest/ce_files.txt`), and `events_per_job` from
`state/{mubeam,mustops_ce}_events_per_job.txt`. It reproduces
`stopping_factor`/`ce_abs_eff` with the code's formula and compares to
`harvest/summary.json`.

```
$ python3 $SCRATCH/recompute.py
config                  ce_abs_eff (recomp) ce_abs_eff (summary)      ratio     src  #logs  mubeam_n   ce_n
foilsflashSOBX01            0.0006434968099      0.0006434968099   1.000000  concat      1        13     13
foilsflashBASIN01_00        0.0006448971176      0.0006448971176   1.000000  mubeam     12        12     12
foilsflashC400_champ         0.000644176255       0.000644176255   1.000000  mubeam     14        14     14
ipafixAB01                  0.0006755457578      0.0006755457578   1.000000  mubeam     12        12     14
ipa625AB01                   0.000676420578       0.000676420578   1.000000  mubeam     14        14     13
ipaovrAB01                  0.0006758439092      0.0006758439092   1.000000  mubeam     12        12     12
foilsflashHOLEDhi           0.0004078289176      0.0004078289176   1.000000  concat      1        13     13
nominalAB01                 0.0004244694269      0.0004244694269   1.000000  mubeam     13        13     14

max |ratio - 1| across all 8 configs: 0.000000% (CLOSES <0.1%)
```

**Closure: PASS for all 8 configs, to <0.0001% (float round-trip only) — well
inside the <0.1% gate.** This proves both that the formula transcription in
§2.1 is exact and that no hidden re-normalization happens between the raw
artifacts and `summary.json`.

**Landed-population consistency check** (the case-by-case verification for
the muminus_stops caveat in §2.1): for every concatless config, the number of
`count_sim.*.log` files (one per counted `TargetStops` file) equals
`mubeam_n` (the landed `mubeam_outputs.txt` line count) exactly —
`foilsflashBASIN01_00` 12==12, `foilsflashC400_champ` 14==14, `ipafixAB01`
12==12, `ipa625AB01` 14==14, `ipaovrAB01` 12==12, `nominalAB01` 13==13. For
the two concat-based configs (`foilsflashSOBX01`, `foilsflashHOLEDhi`), the
`state/` file mtimes confirm `mubeam_outputs.txt` was written *before* the
`concat_cluster.txt` submit stamp and never touched afterward (e.g.
`foilsflashSOBX01`: `mubeam_outputs.txt` 23:45, `concat_cluster.txt` 23:47,
`concat_outputs.txt` 23:57 — same day, same snapshot), so the single merged
file's stop count reflects exactly the 13 landed mubeam files also used for
`mubeam_sim_total`. **No submitted-vs-landed population mismatch exists for
any of the 8 configs** — every numerator/denominator pair in the formula is
built from the same landed-file population, by the deliberate design cited
in §2.1.

Aside: dataset filenames for every config (including the Run1Bap arms) carry
the literal prefix `Run1Bak_<config>` (e.g.
`count_sim.oksuzian.TargetStops.Run1Bak_ipafixAB01...`). This is **not** a
software-release marker — `DSCONF = f"Run1Bak_{cfg}"` (`core/pipeline.py:135`)
is a fixed dataset-naming string baked in regardless of which musing actually
ran the job. Release identity for this investigation is carried by each
config's `mode_specs/*.json` `software.musing`/`grid_tarball` fields (and by
submit date relative to the 2026-07-26 JSON-mode migration, `b361e09`), not
by this filename prefix — noted here so a future reader of raw `harvest/`
logs doesn't misread it as a release tag.

### 2.3 Loss-consistent shift (Step 4)

Since §2.1/§2.2 establish that **no denominator is submitted-based** — every
quantity is already computed from a landed-consistent population — there is
no correction to apply: the "loss-consistent" `ce_abs_eff` is exactly what
`summary.json`/the recompute already report. The shift below is the direct
ratio of group means, computed from the recomputed (not `summary.json`)
`ce_abs_eff` values, with σ from pooled counting statistics on `ce_seen` and
`muminus_stops` (`1/√N` per the brief; relative σ on a group's pooled
`ce_abs_eff` is `sqrt(1/Σce_seen + 1/Σmuminus_stops)`, propagated in
quadrature for the historical/arm ratio):

```
champion-x (3 historical vs 3 arm):
  historical mean ce_abs_eff = 0.00064419  (rel sigma 0.14%; SOBX01/BASIN01_00/C400_champ)
  arm mean ce_abs_eff        = 0.00067594  (rel sigma 0.14%; ipafixAB01/ipa625AB01/ipaovrAB01)
  shift = +4.93% +/- 0.20%

baseline pair (1 vs 1):
  historical ce_abs_eff = 0.00040783  (rel sigma 0.29%; foilsflashHOLEDhi)
  arm ce_abs_eff        = 0.00042447  (rel sigma 0.29%; nominalAB01)
  shift = +4.08% +/- 0.41%
```

Both shifts are many σ from zero (champion-x: 4.93/0.20 ≈ 25σ; baseline:
4.08/0.41 ≈ 10σ) — the shift is a real, statistically robust effect on the
landed-consistent normalization, not counting noise.

Note on the earlier "carried" figures in §1 (+4.75% champion-x, +4.76%
baseline): those came from the pre-Task-2 investigation framing, not from
this audit's ratio-of-group-means method. The champion-x figure is close
(+4.75% carried vs. +4.93% audited here) and both round to the "+4.9%"
`s_over_sqrt_b` shift, consistent with `s_over_sqrt_b ∝ ce_abs_eff` at fixed
background. The baseline figure diverges more (+4.76% carried vs. +4.08%
audited here, vs. +4.8% for `s_over_sqrt_b`) — plausible given it is an n=1
vs n=1 comparison (no averaging to suppress per-config counting noise), but
worth flagging since the `s_over_sqrt_b`-vs-`ce_abs_eff` shift agreement that
holds at champion-x does not hold as tightly at baseline. This audit's
**+4.93% ± 0.20% (champion-x)** and **+4.08% ± 0.41% (baseline)** are the
authoritative, reproducible values — Tasks 4/7 should quote these, not the
carried figures.

### 2.4 Constants/macro drift check (Step 5)

```
$ git log --oneline --since=2026-06-25 -- core/harvest.py core/pipeline.py
c0d3f1d feat(pipeline): gate per-submit getToken on bearer-token age (1h)
b361e09 refactor(modes): retire the Python foilsflash mode; JSON spec owns the line
1f1101c Revert "fix(pipeline): write code tarball and cnf jobdef to dCache scratch"
0d207b6 fix(json-modes): close final-review findings before merge
3e9bf15 fix(pipeline): write code tarball and cnf jobdef to dCache scratch
1809635 refactor: harvest Steps 1+4 behind injected runners in harvest.py
d6e9f53 test: grid-verb coverage + injectable jobsub_q runner in poll_cluster
b369eda refactor: retire dormant ipa mode + mustops_pileup stage (-190 lines)
ad46b8e chore: Tier 1 cleanup — dead env seam, fail-open fallback, stale comments
761b009 refactor: rename autoresearch_bo_michael.py -> core/bo_driver.py
3e880fd refactor: consolidate root dirs — bo_work/, templates+slides relocated
e82160d refactor: reorganize root into core/ + leaderboards/ + pending/
```

Harvest window under audit: historical harvests span `foilsflashHOLEDhi`
2026-06-30 through `foilsflashC400_champ` 2026-07-23 (mtimes on
`harvest/summary.json`); A/B (arm) harvests are `ipafixAB01`/`ipa625AB01`
2026-07-28 and `ipaovrAB01`/`nominalAB01` 2026-07-29. Checked every commit in
the `--since=2026-06-25` window for touches to `RUN1A_MUBEAM_INPUT_CORRECTION`,
`run_edepana`, `run_sensitivity_macro`, or `sourced_env`:

- **`RUN1A_MUBEAM_INPUT_CORRECTION`**: never changed in this window (only
  ever set once, at `e82160d`, a pure root-reorg move — value `0.01278168`
  throughout). No drift.
- **`run_edepana` / `run_sensitivity_macro`**: `1809635` moved these two
  functions from `pipeline.py` into `harvest.py` — a verbatim relocation
  (`core/harvest.py`'s module docstring: *"moved verbatim from pipeline.py"*);
  the diff shows only code motion, no logic or constant changes. No other
  commit in the window touches either function body. No drift.
- **`sourced_env`**: two touches in-window. `ad46b8e` (2026-07-18) only
  edited a docstring (mmackenz's copy → own-build EdepAna comment), no
  functional change. `c0d3f1d` (2026-07-31 18:00) reworked bearer-token
  refresh gating on the *submit* path (`getToken` caching) — it does not
  touch the harvest-time `with_muse=True` env-sourcing branch or anything
  that would change which `mu2e`/ROOT binaries or FHiCL paths harvest sees,
  **and it postdates every harvest in this audit (07-08 through 07-29)** by
  at least 2 days, so it is out of the causal window regardless. No drift
  affecting either the historical or arm harvest dates.
- **Sensitivity macro file identity**: `Run1BAna/` is a separate git checkout
  (mmackenz's personal repo, not a submodule of this repo — see wiki
  `mmackenz-workflow`/`Run1BAna` reference). `git -C Run1BAna log -1 --
  workflows/scripts/rough_run1a_sensitivity.C` → commit `9c520d9`, dated
  2026-04-28; filesystem mtime on both `rough_run1a_sensitivity.C` and
  `edep.fcl` is 2026-04-29 14:40, i.e. **more than two months before the
  earliest harvest in this audit**. The macro was untouched across the
  entire historical→arm window.

**No constants or macro drift found between the historical and A/B harvest
dates.** The +4.93%/+4.08% shifts found in §2.3 cannot be attributed to a
changed `RUN1A_MUBEAM_INPUT_CORRECTION`, a changed sensitivity macro, or a
changed harvest-time environment-sourcing path.

**Verdict: shift survives audit at +4.93% ± 0.20% (champion-x) / +4.08% ± 0.41% (baseline) — accounting is landed-consistent by construction, closure passes to <0.0001%, and no constants/macro drift exists in the window.**
