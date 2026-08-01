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
`concat_cluster.txt` submit stamp and never touched afterward, for **both**
configs: `foilsflashSOBX01` — `mubeam_outputs.txt` 23:45, `concat_cluster.txt`
23:47, `concat_outputs.txt` 23:57 (2026-07-07/08); `foilsflashHOLEDhi` —
`mubeam_outputs.txt` 18:07:39, `concat_cluster.txt` 18:09:11,
`concat_outputs.txt` 18:17:16 (2026-06-30) — same ordering, same-day
snapshot in both cases. So the single merged file's stop count reflects
exactly the landed mubeam files also used for `mubeam_sim_total` in both
configs. **No submitted-vs-landed population mismatch exists for
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

**Provenance of the earlier "carried" figures in §1** (+4.75% champion-x,
+4.76% baseline), traced back to
`docs/superpowers/specs/2026-08-01-run1bak-run1bap-shift-investigation-design.md`
(the design doc §1's figures were carried from, per the Task-1 brief):

- **Champion-x +4.75% traces cleanly.** The design doc's table
  (`...-design.md:37-43`) computes it from a *2-vs-1* subset, not the 3-vs-3
  mean used here: single historical config `foilsflashBASIN01_00`
  (6.4490e-4) vs. the mean of only two of the three arms, `ipafixAB01`
  (6.7555e-4) and `ipaovrAB01` (6.7584e-4) — `ipa625AB01` is absent from
  that table. Reproducing that exact subset from the full-precision
  `summary.json` values: `mean(ipafixAB01, ipaovrAB01) / BASIN01_00 − 1 =
  4.7756%`, matching the carried +4.75% to rounding. This is a narrower
  sample (1 historical, 2 arms) than this audit's 3-vs-3 mean-of-groups
  (+4.93%); the two are consistent (both real, both positive, same order),
  the gap is sampling-basis, not a contradiction.
- **Baseline +4.76% provenance is NOT determined.** The design doc gives a
  `sob` shift for the baseline pair (+4.8%, "3.11 → 3.26, arm D") but **no
  `ce_abs_eff` figure for the baseline pair anywhere in that document** — so
  there is no computation to trace it to. Directly dividing the two
  full-precision `summary.json` `ce_abs_eff` values for this exact pair
  (`foilsflashHOLEDhi` 4.0783e-4, `nominalAB01` 4.2447e-4) gives +4.08026...%,
  unambiguously — there is no alternative pairing or subset (unlike
  champion-x) that could yield +4.76% from an n=1-vs-n=1 comparison, since
  both figures necessarily use the same two configs. Treat the carried
  +4.76% as approximate/unsourced.

This audit's **+4.93% ± 0.20% (champion-x)** and **+4.08% ± 0.41%
(baseline)**, both recomputed directly from raw artifacts with full
precision and a stated σ, are the authoritative, reproducible values —
Tasks 4/7 should quote these, not the carried figures.

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

## 3. Provenance audit

Closes the remaining "our own migration bug?" avenues: rendered-geometry
diffs must match exactly the known override deltas, the grid tarballs must
carry the expected patched-library markers, and the harvest environment must
be pinned identically for both eras. `$GRID` =
`/exp/mu2e/data/users/oksuzian/autoresearch_grid` (`graph/config.py:33`
`GRID_DATA_ROOT`, imported as `DATA_ROOT` at `core/pipeline.py:72`, `ROOT =
DATA_ROOT / cfg` at `:129`).

### 3.1 Pairwise rendered-geom diffs (Step 1)

Diff helper (`$SCRATCH/geomdiff.sh`, comments stripped per the brief):

```bash
strip() { sed -e 's://.*$::' -e 's/^#.*$//' -e '/^\s*$/d' "$1"; }
diff <(strip $GRID/$A/geom/*_geom.txt) <(strip $GRID/$B/geom/*_geom.txt)
```

Each config's `geom/` directory contains exactly one `*_geom.txt` (glob is
unambiguous for all 6 configs touched here).

**Pair 1: `foilsflashBASIN01_00` vs `ipafixAB01`**

```
0a1,2
> double zEMCSourceInMu2e = 5000.0;
> double protonabsorber.distFromTargetEnd = 491.666672;
3c5
< vector<double> stoppingTarget.radii          = { ... };   (padded)
---
> vector<double> stoppingTarget.radii = { ... };             (single-space)
6c8
< vector<double> stoppingTarget.holeRadii      = { ... };   (padded)
---
> vector<double> stoppingTarget.holeRadii = { ... };          (single-space)
10,11d11
< bool tracker.inDS2Vacuum = true;
< double ds2.halfLength = 3825;
```

Classification:
- `zEMCSourceInMu2e = 5000.0` added, `tracker.inDS2Vacuum`/`ds2.halfLength`
  override removed — **REAL, expected** (matches brief's stated class
  exactly).
- `protonabsorber.distFromTargetEnd = 491.666672` added in `ipafixAB01` with
  no corresponding `625` line anywhere in either rendered file (`grep -n
  distFromTargetEnd` on both files: zero hits in `BASIN01_00`, one hit —
  `491.666672` — in `ipafixAB01`). The brief's "625 → 491.666672" phrasing
  refers to the *conceptual* default (625, defined in the `#include`d stock
  `geom_run1_a.txt`, not in this per-config override file) vs the explicit
  override — **REAL, expected**, confirmed by the in-file comment at
  `ipafixAB01`'s line 10: *"A/B ARM A (control, CORRECT).
  protonabsorber.distFromTargetEnd 491.666672 holds the IPA at its true
  hardware position 6901-7901 ... Identical to the live foilsflash spec."*
- `radii`/`holeRadii` padding hunks (multiple vs single space before `=`) —
  **FINDING, classified EQUIVALENT**: re-running the diff with whitespace
  collapsed (`sed -E 's/[[:space:]]+/ /g'`) removes both hunks entirely and
  leaves exactly the two REAL deltas above — the numeric vectors are
  byte-identical, only column-alignment formatting differs between the two
  config-template authors (`foils`-mode vs `foilsflash`-mode templates).

Normalized-whitespace confirmation:
```
$ diff <(norm BASIN01_00) <(norm ipafixAB01)
0a1,2
> double zEMCSourceInMu2e = 5000.0;
> double protonabsorber.distFromTargetEnd = 491.666672;
10,11d11
< bool tracker.inDS2Vacuum = true;
< double ds2.halfLength = 3825;
```
Exactly the brief's expected class, nothing else.

**Pair 2: `ipafixAB01` vs `ipaovrAB01`**

```
15a16,17
> bool tracker.inDS2Vacuum = true;
> double ds2.halfLength = 3825.0;
```
**REAL, expected — EXACTLY the override pair restored**, matching the brief
verbatim. One cosmetic note (FINDING, classified EQUIVALENT): `ipaovrAB01`
writes `3825.0` vs `BASIN01_00`/`HOLEDhi`'s `3825` — numerically identical
(GeometryService parses both as the same double), formatting-only.

**Pair 3: `ipafixAB01` vs `ipa625AB01`**

```
2c2
< double protonabsorber.distFromTargetEnd = 491.666672;
---
> double protonabsorber.distFromTargetEnd = 625.0;
```
**REAL, expected — EXACTLY the one `distFromTargetEnd` line**, matching the
brief verbatim. No other hunks, no formatting artifacts.

**Pair 4: `foilsflashHOLEDhi` vs `nominalAB01`** (comparability caveat, per
brief, stated verbatim below)

Raw diff (comments stripped only):
```
1,3c1
< bool hasTSdA = false;
< bool tsda.helical.build = false;
< vector<double> stoppingTarget.radii          = { ... };
---
> vector<double> stoppingTarget.radii = { ... };
6c4,7
< vector<double> stoppingTarget.holeRadii      = { ... };
---
> vector<double> stoppingTarget.holeRadii = { ... };
> double zEMCSourceInMu2e = 5000.0;
> bool hasTSdA = false;
> bool tsda.helical.build = false;
10,11d10
< bool tracker.inDS2Vacuum = true;
< double ds2.halfLength = 3825;
```

**Comparability caveat (verbatim from brief context):** the two configs emit
the deployed 37-foil stack via different mechanisms —
`foilsflashHOLEDhi` (a `foils`/foilsflash-mode BO point with the "up/down
extras" env-seam pinned to `N_UP=N_DOWN=0`, per its header comment "+ 0 up
... + 0 dn") vs `nominalAB01` (a `nominal`-mode config that writes the
deployed stack out **explicitly** via `base_*` consts, per its header
comment: *"Deployed 37-foil stack written out EXPLICITLY via the base_*
consts. Bit-identical to the base include ... Written out so the baseline is
self-describing and so preflight's as-built GDML check has a vector to
verify."*). The raw line-diff above therefore looks large (reordering, not
just value changes) — enumerated and classified hunk-by-hunk below rather
than forced into a one-line story, per the task instructions.

Classification, confirmed by an order-independent (sorted, whitespace-normalized)
set-diff:
```
$ diff <(norm HOLEDhi | sort) <(norm nominalAB01 | sort)
5d4
< bool tracker.inDS2Vacuum = true;
8d6
< double ds2.halfLength = 3825;
11a10
> double zEMCSourceInMu2e = 5000.0;
```
- `hasTSdA`/`tsda.helical.build`/`stoppingTarget.radii`/`stoppingTarget.halfThicknesses`/
  `stoppingTarget.holeRadius`/`stoppingTarget.holeRadii` — present in both
  files with **byte-identical values** (37×75.0000 rOut, 37×0.0528
  halfThickness, 1.0e6 poison-pill scalar, 37×21.5000 holeRadii); only their
  **line order** differs (HOLEDhi: `hasTSdA`/`tsda.helical.build` before the
  vectors; nominalAB01: vectors before `hasTSdA`/`tsda.helical.build`, with
  `zEMCSourceInMu2e` interleaved) plus the same `radii`/`holeRadii` padding
  seen in Pair 1. Mu2e's GeometryService `SimpleConfig` format is a flat,
  order-independent key=value table (each key here is assigned exactly once
  in each file, no redefinition) — **FINDING, classified EQUIVALENT**: this
  is exactly the "different emission mechanism, same resulting geometry"
  the brief flagged as expected, now proven byte-for-byte via the
  order-independent set-diff, not asserted.
- `zEMCSourceInMu2e = 5000.0` added, `tracker.inDS2Vacuum`/`ds2.halfLength`
  override removed — **REAL, expected** — the identical delta class as Pair
  1 (HOLEDhi is historical/foilsflash-family, nominalAB01 is Run1Bap-era,
  same override-pair-removed + EMC-relocation pattern).

**Net result for Pair 4: after accounting for reordering and padding, the
semantic content reduces to exactly the same two REAL deltas found in Pair
1** (override pair removed, `zEMCSourceInMu2e` added) — the deployed-stack
values themselves are provably identical between the two emission
mechanisms. No hunk falls outside the established delta class.

### 3.2 Tarball provenance + strings gates (Step 2)

Provenance per config, `grep -ho "[^ ]*tar.bz2" $GRID/<config>/graph_logs/submit_mubeam_*.log | sort -u`:

| config | tarball |
|---|---|
| `foilsflashBASIN01_00` | `Code_helical_holeradii.tar.bz2` |
| `foilsflashHOLEDhi` | `Code_helical_holeradii.tar.bz2` |
| `ipafixAB01` | `Code_run1bap_holeradii.tar.bz2` |
| `ipa625AB01` | `Code_run1bap_holeradii.tar.bz2` |
| `ipaovrAB01` | `Code_run1bap_holeradii.tar.bz2` |
| `nominalAB01` | `Code_run1bap_holeradii.tar.bz2` |

Matches the brief exactly: historical + HOLEDhi on the helical tarball, all
four arms on the run1bap tarball.

In-dir preserved copies (`Code.<name>.tar.bz2`) exist only for the four arm
configs (`$GRID/<config>/Code.Code_run1bap_holeradii.tar.bz2`, sizes
15,233,454 / 15,234,937 / 15,233,506 / 15,233,817 bytes for
ipafixAB01/ipaovrAB01/ipa625AB01/nominalAB01 respectively — all close but not
byte-identical to each other, and to the shared build-area original at
`/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_run1bap_holeradii.tar.bz2`,
which has since been overwritten by a later build, `md5` differs from all
four in-dir copies). Neither historical config (`foilsflashBASIN01_00`,
`foilsflashHOLEDhi`) has a preserved in-dir copy, so per the brief's stated
fallback the extraction used the `autoresearch_muse/` original for the
helical side.

Extraction (member path found first via `tar -tjf | grep GeometryService`,
since the lib path differs by build qualifier between the two tarballs:
`Code/build/al9-prof-e29-p094/...` for helical vs
`Code/build/al9-prof-e29-p101/...` for run1bap — itself confirming these are
genuinely distinct qualifier builds, p094 (Run1Bak) vs p101 (Run1Bap), not
just a rename):

```bash
tar -xjf /exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2 \
    -C $SCRATCH/tb_helical --wildcards "*libmu2e_GeometryService.so"
tar -xjf $GRID/ipafixAB01/Code.Code_run1bap_holeradii.tar.bz2 \
    -C $SCRATCH/tb_run1bap --wildcards "*libmu2e_GeometryService.so"
```

Strings gate (note: the brief's `**` glob needs `shopt -s globstar`, or it
silently expands to a literal unmatched string and `strings`/`grep -c`
silently report `0` — verified this failure mode, then re-ran with
`globstar` enabled):

```bash
$ shopt -s globstar
$ strings $SCRATCH/tb_helical/**/libmu2e_GeometryService.so | grep -c "holeRadii vector active"
1
$ strings $SCRATCH/tb_run1bap/**/libmu2e_GeometryService.so | grep -c "holeRadii vector active"
1
```
Match context in both: `StoppingTargetMaker: holeRadii vector active (n=`.

**Marker present (=1) in BOTH distinct tarballs** — both eras ran the
holeRadii-patched `StoppingTargetMaker`, per the brief's PASS criterion.

Cross-check: extracted the same lib from `nominalAB01`'s in-dir tarball copy
(the other run1bap-era arm used in this audit, at
`$GRID/nominalAB01/Code.Code_run1bap_holeradii.tar.bz2`) and confirmed both
the marker (`grep -c` = 1) and an **exact md5 match**
(`ae39b58dd7e0c33d7be571943e70cdc1`) against the `ipafixAB01` copy's
`libmu2e_GeometryService.so` — the small tarball-size differences noted
above are metadata/other-file noise, not a different library build across
the four arm configs.

### 3.3 Harvest env pinning + naming note (Step 3)

`core/pipeline.py:423-452` (`sourced_env(..., with_muse=True)`), quoted:

```python
def sourced_env(extra="", *, with_muse=False) -> dict:
    ...
    if with_muse:
        # Use our own autoresearch_muse work area (same one that produces the
        # base Code.tar.bz2). `-q p094` is required: without it muse picks
        # p095 from main-HEAD's Offline/.muse and errors on the backing.
        ...
        mmlib = "/exp/mu2e/app/users/oksuzian/autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib"
        prelude = (
            "cd /exp/mu2e/app/users/oksuzian/autoresearch_muse && "
            f"source {SETUPMU2E} >/dev/null 2>&1 && "
            "muse setup -q p094  >/dev/null 2>&1 && "
            f"export CET_PLUGIN_PATH={mmlib}:$CET_PLUGIN_PATH && "
            f"export LD_LIBRARY_PATH={mmlib}:$LD_LIBRARY_PATH && "
        )
```

`with_muse=True` unconditionally `cd`s into `autoresearch_muse` and runs
`muse setup -q p094` — a **hardcoded qualifier**, independent of whichever
musing/tarball (`Code_helical_holeradii.tar.bz2` vs
`Code_run1bap_holeradii.tar.bz2`, i.e. p094 vs p101) actually simulated that
config. `CET_PLUGIN_PATH`/`LD_LIBRARY_PATH` are pinned to the same
`.../autoresearch_muse/build/al9-prof-e29-p094/Run1BAna/lib` for every
config, so every harvest — historical and arm alike — runs mmackenz's
EdepAna module built against the **same fixed p094/Run1Bak-era Offline
build**, regardless of which release produced the raw art files being
harvested.

This is the *sole* call site: `cmd_harvest` calls `sourced_env(with_muse=True)`
exactly once (`core/pipeline.py:1297`), unconditionally for every mode (no
mode branch on this call), and threads the resulting `env` into both the
EdepAna runner (`_mu2e_runner`, `core/pipeline.py:1318-1325`, used by
`hv.run_edepana`) and the muminus-stops counter (`_count_events_art(f, env,
harvest_dir)`, `:1329`) — i.e. **all** of the harvest-stage tooling for
**all 8 configs in this audit** ran under this one pinned environment.

Git-window check (from §2.4 / Task 2 Step 5, restated here as the Step 3
confirmation): `git log --oneline --since=2026-06-25 -- core/pipeline.py`
shows two touches to `sourced_env` in the audited window — `ad46b8e`
(2026-07-18, docstring-only) and `c0d3f1d` (2026-07-31, reworks the
*submit-path* `getToken` bearer-token caching, not the `with_muse=True`
harvest branch, and postdates every harvest in this audit by ≥2 days). No
commit in the window changed the pinning lines quoted above. **Confirmed: no
drift.**

**Naming note.** `harvest/count_sim.*.log` filenames (produced by
`_count_events_art`, `core/pipeline.py:1167-1186`, `log = harvest_dir /
f"count_{art_path.stem}.log"`, `:1177`) inherit their name from the
`TargetStops` input `.art` file's own SAM dataset name — the `mubeam` stage's
`output_glob` is `"sim.*.TargetStops.*.art"` (`core/pipeline.py:160`), and
the `<dsconf>` field embedded in that filename comes from `DSCONF =
f"Run1Bak_{cfg}"` (`core/pipeline.py:135`, set unconditionally in
`_bind_config()`), overridable only via a per-stage `dsconf_musing` key
(`_stage_dsconf`, `:139-141`) — which the `mubeam` STAGES entry does **not**
set (`core/pipeline.py:148-160`, no `dsconf_musing` key present). So every
config's `mubeam`-stage output files, and therefore every `count_sim.*.log`
harvest artifact, carry the literal string `Run1Bak_<config>` **regardless
of which musing actually ran mubeam** — this reproduces the same naming
quirk already noted in §2.2's Aside (dataset filenames), now traced to its
exact source (`DSCONF` template + `TargetStops` output_glob). It is a fixed
dataset-naming string, cosmetic, and carries no release-identity information
— consistent with, not contradicting, §2.2.

### 3.4 Summary

| Step | Result |
|---|---|
| Rendered-geom diffs (4 pairs) | All hunks classified; every REAL delta matches the brief's stated class exactly; all non-matching hunks (padding, line order, `3825` vs `3825.0`) verified EQUIVALENT via whitespace/order-normalized re-diff, not asserted |
| Tarball provenance | Historical + HOLEDhi → `Code_helical_holeradii.tar.bz2` (p094 build); all 4 arms → `Code_run1bap_holeradii.tar.bz2` (p101 build) — matches brief exactly |
| `holeRadii vector active` strings gate | Present (=1) in **both** distinct tarballs; cross-checked identical (md5) across two arm configs' in-dir copies |
| Harvest env pinning | `sourced_env(with_muse=True)` hardcodes `muse setup -q p094` + a fixed `Run1BAna` lib path, called once in `cmd_harvest` (`:1297`), threaded into every metric-producing subprocess, for every one of the 8 configs; no in-window commit touched the pinning lines before any of the 8 harvests |
| `count_sim.*.log` naming | Traced to `DSCONF = f"Run1Bak_{cfg}"` (`:135`) × `mubeam` `output_glob` (`:160`); cosmetic, no `dsconf_musing` override for `mubeam` |

No hunk, tarball, or environment-pinning check surfaced anything outside an
expected delta class across all four geometry pairs, both distinct
tarballs, and the harvest environment. The rendered geometries differ by
exactly the documented override deltas (plus provably-equivalent
formatting/ordering noise), both eras' grid tarballs carry the
holeRadii-patched `StoppingTargetMaker` library, and the harvest environment
is bit-for-bit pinned across the historical→arm window.

**Verdict: our migration ruled out — rendered-geom diffs match the expected
override-delta class exactly (all excess hunks verified equivalent, not
asserted), both distinct tarballs gate PASS on the holeRadii-patched
GeometryService lib, and the harvest environment (`sourced_env(with_muse=True)`,
`core/pipeline.py:423-452`) is pinned bit-identically across every historical
and arm harvest in this audit, with no in-window commit touching the pinning
path (no finding).**
