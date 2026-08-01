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

## 4. Box-scan decomposition

Decomposes the sob shift into the three candidate mechanisms: does the
macro's momentum test-box move between eras, does acceptance at a *fixed*
box rise, or does background fall. Quoting §2's audited figures per the
brief: **+4.93% ± 0.20% (champion-x, ce_abs_eff)** / **+4.08% ± 0.41%
(baseline, ce_abs_eff)** — these are the audited **ce_abs_eff** input-ratio
figures (§2.3), not sob ratios; §4.3 recomputes the actual sob ratios here
and checks them against these as the "pure normalization" expectation.

### 4.1 Macro mechanism (Step 1)

`s_over_sqrt_b = hv.run_sensitivity_macro(harvest_dir, nts_path, ce_abs_eff,
runner=_root_runner)` (`core/pipeline.py:1346`) calls `run_sensitivity_macro`
(`core/harvest.py:98-121`), which shells out:

```python
cmd = ["root", "-q", "-b", "-l",
       f'scripts/rough_run1a_sensitivity.C("{nts_path}", '
       f'{ce_abs_eff:.16g}, "{harvest_dir}")']
```

i.e. `ce_abs_eff` is passed positionally as `rough_run1a_sensitivity.C`'s
second argument, bound to the macro's `sig_eff` parameter
(`Run1BAna/workflows/scripts/rough_run1a_sensitivity.C:93`,
`int rough_run1a_sensitivity(TString sig_file_name, double sig_eff, const
char* run_dir = ".")`. `run_sensitivity_macro` then parses the return value
from stdout via `parse_s_over_sqrt_b` (`core/harvest.py:52-57`), which
`search`es `S_OVER_SQRTB_RX = re.compile(r"^Signal box.*S/sqrt\(B\)\s*=\s*
([\d.eE+-]+)\s*$", re.MULTILINE)` (`core/harvest.py:36-37`) — **the single
"Signal box" line**, not any of the many "Test box" lines.

**Where `sig_eff`/`ce_abs_eff` enters the macro (verbatim line cites):**

- `h_sig` (signal, `EDepAna/hist_2/trk_front_energy` from `nts_path`) is
  rebinned then absolutely normalized: `h_sig->Scale(npot * signal_br *
  sig_eff / h_sig->GetEntries())` (`rough_run1a_sensitivity.C:127`) — with
  `npot = 1.e18` and `signal_br = 1.e-13/0.609` fixed constants
  (`:110-111`). This is the **primary, direct** entry point: `ce_abs_eff`
  linearly rescales the absolute signal-count normalization of every bin.
- `response` (`EDepAna/hist_2/trk_front_energy_diff`, per-config energy-loss
  shape) is separately scaled `response->Scale(sig_eff /
  response->GetEntries() / response->GetBinWidth(1))` (`:128`). This
  `response` object is used **twice**: once cosmetically for a diagnostic
  plot (`:137-138`, `response.png`), and again as the convolution kernel for
  the DIO background: `TH1* dio_resp = convolve(convolve(dio, response),
  res)` (`:165`) — so `sig_eff` enters the DIO background a *second* time
  through this kernel, on top of the direct `dio->Scale(0.39*sig_eff*npot)`
  at `:162`. (The signal itself is smeared with a *different*, `sig_eff`-independent
  Gaussian resolution kernel, `res = trk_resolution()` at `:129`, used at
  `h_sig = convolve(h_sig, res)` `:130` — `response` never touches the
  signal path.)
- Cosmic background (`:174-179`) is built from a **fixed** assumed rate,
  `cosmic_rate_second = 2e4/1.1e7` (`:115`), scaled only by `seconds =
  nevents*1.695e-6` where `nevents = npot/mean_pot` (`:112-114`) — `npot` is
  the same fixed `1.e18` constant, `mean_pot` a fixed `1.6e7`. **Cosmic has
  zero functional dependence on `sig_eff`/`ce_abs_eff`.**
- The double loop (`:205-234`) scans every `(x_1_l, x_2_l)` box pair,
  computing `sensitivity_l = signal_rate_l / sqrt(bkg_rate_l)` per box
  (`:221`) and printing a `"  Test box = ..."` diagnostic line for **every**
  box tried (`:222-223`, 41,905 lines/config in this audit's logs). The loop
  tracks the running best (`:224-232`) and, after the loop, prints **one**
  final `"Signal box = ..."` line (`:236-237`) — the argmax over the whole
  scan — which is exactly the line `S_OVER_SQRTB_RX` parses.

**How raw ~1e-8/1e-9 scan values become the ~3.9 final number:** verified
directly against `foilsflashSOBX01`'s log — near the DIO-dominated low-energy
end of the scan (e.g. `Test box = [50.1, 50.1] MeV/c, ... dio = 6.3e+10 ...
S/sqrt(B) = 1.83e-09`), `sensitivity_l` is astronomically suppressed because
the DIO spectrum tail is huge there (`bkg ~ 1e10-1e11`). As the box slides up
toward the CE endpoint (~103-105 MeV/c), the DIO tail has fallen off by
~13-14 orders of magnitude (theoretical Michel/DIO spectrum, `get_dio_spectrum()`
`:6-40`) while `cosmic` stays flat (`~190-350`, box-width-dependent only), so
`bkg_rate` collapses from `~1e11` to `~190-350` and `sensitivity_l` jumps from
`~1e-9` to `O(1)`. **The final ~3.9 is not a transform of the small values —
it is the literal maximum of the per-box `sensitivity_l` array over the whole
scan**, which lands at the box where DIO has become negligible and cosmic
(background-floor, `ce_abs_eff`-independent) sets the background. This is
directly confirmed by this audit's own scan grep: every `"Signal box"` line's
five fields exactly match the max-`S/sqrt(B)` `"Test box"` row for that same
config (verified programmatically in §4.2 below — `best(rows)` reproduces the
grep'd `"Signal box"` line for all 8 configs).

### 4.2 `$SCRATCH/boxscan.py` + argmax boxes (Step 2)

Script (matches the brief's script verbatim, plus tsv-dump and an
exact/tolerance match-kind report, both requested by the brief):
`$SCRATCH/boxscan.py`. Per-config full scan dumps:
`$SCRATCH/boxscan_<config>.tsv` (8 files, `lo hi signal dio cosmic bkg sob`,
41,905 rows each).

**Box grid identity check (the brief's stated fallback path):** all 8
configs' `(lo,hi)` tuple sequences are **byte-identical** (`md5sum` of the
first two tsv columns is `00fb2009...` for all 8, same 41,905-row count) —
the scan grid did **not** change between eras; every match below is
`match=exact`, no tolerance fallback needed.

```
$ python3 $SCRATCH/boxscan.py
ref_box (argmax of foilsflashBASIN01_00) = (103.1, 104.7)
foilsflashSOBX01:      argmax_box=[103.3,104.7] sob_at_own=3.9  sob_at_ref=3.89 signal_at_ref=72 dio_at_ref=0.0016  cosmic_at_ref=350
foilsflashBASIN01_00:  argmax_box=[103.1,104.7] sob_at_own=3.91 sob_at_ref=3.91 signal_at_ref=73 dio_at_ref=0.0016  cosmic_at_ref=350
foilsflashC400_champ:  argmax_box=[103.1,104.7] sob_at_own=3.9  sob_at_ref=3.9  signal_at_ref=73 dio_at_ref=0.0016  cosmic_at_ref=350
ipafixAB01:            argmax_box=[103.1,104.7] sob_at_own=4.1  sob_at_ref=4.1  signal_at_ref=76 dio_at_ref=0.0017  cosmic_at_ref=350
ipa625AB01:            argmax_box=[103.1,104.7] sob_at_own=4.11 sob_at_ref=4.11 signal_at_ref=76 dio_at_ref=0.0017  cosmic_at_ref=350
ipaovrAB01:             argmax_box=[103.3,104.7] sob_at_own=4.11 sob_at_ref=4.1  signal_at_ref=76 dio_at_ref=0.0017  cosmic_at_ref=350
foilsflashHOLEDhi:     argmax_box=[103.9,104.7] sob_at_own=3.11 sob_at_ref=2.84 signal_at_ref=53 dio_at_ref=0.001   cosmic_at_ref=350
nominalAB01:           argmax_box=[103.9,104.7] sob_at_own=3.26 sob_at_ref=2.95 signal_at_ref=55 dio_at_ref=0.0011  cosmic_at_ref=350
```

`ref_box` is the champion-x-historical `foilsflashBASIN01_00`'s own argmax,
per the brief's script. The baseline pair's own argmax box (`[103.9,104.7]`)
differs from the champion-x `ref_box` — this is a **cross-geometry**
difference (baseline runs a different stopping-target geometry than
champion-x, so a different CE box optimum is expected), not a same-geometry
within-era migration, so §4.3's baseline-pair analysis uses the baseline
pair's own (shared) box rather than the champion-x `ref_box`.

**Precision caveat (applies throughout §4.3):** the macro's own `printf`
formats are `%.2g` for `signal`/`dio`/`cosmic`/`bkg` and `%.3g` for
`S/sqrt(B)` (`rough_run1a_sensitivity.C:222-223,236-237`) — the log carries
**no more precision than 2-3 significant figures**, confirmed by re-reading
the raw tsv rows directly (no hidden extra digits). All σ below account for
this quantization floor explicitly, in addition to (for n=3 groups) the
empirical spread across the 3 configs.

### 4.3 Fixed-box decomposition + the three questions (Step 3)

**σ formula (methodology, matching §2.3's precedent of stating the
formula):** for n=3 groups (champion-x), relative σ per group = sample
standard error of the mean of the 3 values = `stdev(3 vals, ddof=1) / √3 /
mean`; a ratio's relative σ = `sqrt(relσ_arm² + relσ_hist²)`, absolute σ =
`ratio × relσ_ratio`. Worked example, sob @ fixed box: historical
`[3.89,3.91,3.90]` → mean 3.9000, sd 0.01000, SEM 0.00577, relσ=0.148%;
arm `[4.10,4.11,4.10]` → mean 4.1033, sd 0.00577, SEM 0.00333, relσ=0.081%;
`relσ_ratio = sqrt(0.148%² + 0.081%²) = 0.169%`, `σ = 1.05214 × 0.169% =
0.178%` — reproduces the table entry exactly. For n=1 comparisons
(baseline pair) or wherever a group's 3 members print identically (no
usable sample spread, e.g. champion-x `cosmic`), relative σ per value
instead uses the macro's own print-quantization floor, `0.5 ×
10^(⌊log₁₀|v|⌋ − sigfigs + 1) / |v|` (half the last significant digit of
the `%.2g`/`%.3g` format at `rough_run1a_sensitivity.C:222-223,236-237`),
combined the same way. Worked example, baseline sob: `3.11` (3 sig figs) →
quantum 0.005, relσ=0.161%; `3.26` → quantum 0.005, relσ=0.153%;
`relσ_ratio = sqrt(0.161%²+0.153%²) = 0.222%`, `σ = 1.04823 × 0.222% =
0.233%` — reproduces the table entry exactly.

**Champion-x group (3 historical: SOBX01/BASIN01_00/C400_champ vs 3 arms:
ipafixAB01/ipa625AB01/ipaovrAB01), at the shared `ref_box=[103.1,104.7]`:**

| quantity | historical mean | arm mean | ratio | shift | σ (quadrature: group-spread SEM ⊕ print-quantization) |
|---|---|---|---|---|---|
| sob (fixed box) | 3.9000 | 4.1033 | 1.05214 | +5.214% | ±0.178% |
| signal (fixed box) | 72.667 | 76.000 | 1.04587 | +4.587% | ±0.480% |
| dio (fixed box) | 0.0016 | 0.0017 | 1.0625 | +6.25% | negligible weight (see below) |
| cosmic (fixed box) | 350.0 | 350.0 | 1.00000 | +0.000% | ±0.000% (identical to 2 sig figs for all 6 configs) |
| bkg = dio+cosmic (fixed box) | 350.0 | 350.0 | 1.00000 | +0.000% | ±0.000% |
| dio/bkg fraction | 4.6e-6 (0.00046%) | 4.9e-6 (0.00049%) | — | — | dio contributes <0.0005% of total bkg — physically irrelevant despite its own +6.25% shift |

`sob` at each config's **own** argmax (i.e. what actually lands in
`summary.json`/the leaderboard): historical mean = 3.9033, arm mean =
4.1067, ratio = 1.05209, **shift = +5.209% ± 0.124%** — statistically
identical to the fixed-box figure above (own-argmax − fixed-box =
**−0.004 percentage points**, consistent with zero).

**This +5.21% supersedes the carried "+4.9%" figure in §1.** Tracing it the
same way §2.3 traced the ce_abs_eff carried figure: `mean(BASIN01_00) vs
mean(ipafixAB01, ipaovrAB01)` (excluding `ipa625AB01`, the same 2-vs-1
narrower subset found in §2.3) gives `4.105/3.91 − 1 = +4.99%` ≈ the carried
+4.9%. **Same provenance pattern as §2.3's ce_abs_eff finding: the carried
figure is a narrower 1-vs-2 subset; the audited 3-vs-3 group-mean sob shift
is +5.21% ± 0.12%, not +4.9%.**

**Baseline pair (`foilsflashHOLEDhi` vs `nominalAB01`), at their shared own
argmax box `[103.9,104.7]`** (identical box for both — no separate
"fixed-box" table needed, own-argmax *is* the fixed box here):

| quantity | HOLEDhi | nominalAB01 | ratio | shift | σ (print-quantization) |
|---|---|---|---|---|---|
| sob | 3.11 | 3.26 | 1.04823 | +4.823% | ±0.233% |
| signal | 43 | 45 | 1.04651 | +4.651% | ±1.683% |
| dio | 2.6e-05 | 2.8e-05 | 1.0769 | +7.69% | negligible weight (see below) |
| cosmic | 190 | 190 | 1.00000 | +0.000% | ±0.000% |
| dio/bkg fraction | 1.37e-7 (0.0000137%) | 1.47e-7 (0.0000147%) | — | — | utterly negligible |

**Why the `dio` ratio (+6.25%/+7.69%) runs above the `ce_abs_eff` ratio
(+4.93%/+4.08%):** per §4.1, `dio_resp` is scaled by `sig_eff` **twice** —
once directly (`dio->Scale(0.39*sig_eff*npot)`, `:162`) and again through
its convolution kernel `response`, itself pre-scaled by `sig_eff`
(`response->Scale(sig_eff/...)` `:128`, used at `convolve(dio, response)`
`:165`) — so `dio`'s `sig_eff` dependence is closer to quadratic than
linear, which is consistent with a ratio (~1.05²≈1.10-ish territory,
roughly matching the observed +6-8%) exceeding the linear `ce_abs_eff`
ratio. This is immaterial to every conclusion below: `dio` is <0.0005% of
total background in both groups (table rows above), so its super-linear
scaling has no measurable effect on `sob`.

**Three questions, both groups:**

**1. Did the optimal box move?**
- Champion-x: argmax boxes are `{[103.1,104.7]×2, [103.3,104.7]×1}`
  historical vs `{[103.1,104.7]×2, [103.3,104.7]×1}` arms — **the identical
  two-point set on both sides** of the 0.2 MeV/c scan grid, no systematic
  direction. Isolated box-migration contribution to sob: **−0.004 percentage
  points** (own-argmax ratio minus fixed-box ratio), consistent with zero at
  the print-quantization floor. **No box migration.**
- Baseline: `[103.9,104.7]` for **both** `HOLEDhi` and `nominalAB01` —
  **exactly the same box**. Box-migration contribution: **0% by
  construction** (own argmax = shared box for both configs). **No box
  migration.**

**2. At fixed box, signal-side vs background-side fraction of the shift?**
- Champion-x: signal ratio +4.587% vs cosmic (=bkg, dio negligible) ratio
  +0.000%. Decomposing `sob = signal/sqrt(bkg)`: since `bkg` is unchanged,
  100% of any *bkg-driven* sob rise is 0% — background contributes ~0% and
  signal-side (acceptance) contributes ~100% of the fixed-box shift.
- Baseline: signal ratio +4.651% vs cosmic ratio +0.000%. Same conclusion:
  **~100% signal-side (acceptance), ~0% background-side**, for both groups.
  **Caveat on the cosmic-ratio=1.0000 reading:** per §4.1, `cosmic` is a
  pure function of box width and hardcoded globals
  (`cosmic_rate_second=2e4/1.1e7`, `npot=1e18`, `mean_pot=1.6e7`,
  `rough_run1a_sensitivity.C:174-179`) — none of which vary by config or
  era. The ratio is therefore **structurally guaranteed** to print as
  1.0000 at a fixed box regardless of whether real cosmic-ray background
  conditions actually differed between Run1Bak and Run1Bap; this macro has
  no mechanism to see such a difference even if one existed. "0%
  background-side" here means *unchanged within what this macro's model
  can express*, not an independently-measured physical invariant.
  (Note: the fixed-box `sob` ratio computed directly from the log's
  3-sig-fig `S/sqrt(B)` field, +5.214%/+4.823%, is numerically somewhat
  above the ratio implied by recombining the coarser 2-sig-fig
  `signal`/`bkg` fields, +4.587%/+4.651% — this ~0.6pp/0.2pp gap is
  **print-rounding noise between the macro's independently-rounded fields**,
  not a real background effect, since `cosmic` itself prints **bit-identically**
  at both 2 and 3 significant figures across every one of the 8 configs.)

**3. Is the signal-side ratio consistent with the ce_abs_eff ratio, or is
there a residual spectrum/shape effect?**

Using the more precise `S/sqrt(B)` field (3 sig figs) as the "sob route",
and the coarser `signal` field (2 sig figs) as the "signal route", against
§2.3's audited ce_abs_eff ratios (+4.93%±0.20% champion-x, +4.08%±0.41%
baseline):

| group | route | measured ratio | expected (ce_abs_eff) | residual | σ | significance |
|---|---|---|---|---|---|---|
| champion-x | sob @ fixed box | +5.214% | +4.93% | **+0.270%** | ±0.255% | 1.06σ |
| champion-x | sob @ own argmax | +5.209% | +4.93% | **+0.266%** | ±0.225% | 1.18σ |
| champion-x | signal @ fixed box | +4.587% | +4.93% | **−0.327%** | ±0.495% | 0.66σ |
| baseline | sob @ shared box | +4.823% | +4.08% | **+0.714%** | ±0.456% | 1.57σ |
| baseline | signal @ shared box | +4.651% | +4.08% | **+0.549%** | ±1.665% | 0.33σ |

**No residual is significant at 2σ in either group or via either route.**
The sob-route and signal-route residuals for champion-x even carry
**opposite signs** while both sitting near 1σ — exactly what print-rounding
noise on independently-quantized log fields produces, not a coherent
physical effect (a real shape/spectrum shift would push both routes the
same direction). The baseline pair's sob-route residual (+0.71%, 1.57σ) is
the largest single figure found, but it is an n=1-vs-n=1 comparison with no
replicate to check reproducibility, and still falls short of 2σ.

**Conclusion for all three questions, both groups: the sob shift is fully
consistent with pure `ce_abs_eff`-normalization scaling — no box migration,
no background change, and no statistically significant residual
spectrum/shape effect at the log's 2-3-significant-figure precision.**

**Verdict: champion-x +5.21% ± 0.12% (own-argmax; supersedes the carried
+4.9%, same 1-vs-2-subset provenance issue §2.3 found for ce_abs_eff) =
~100% acceptance-at-fixed-box (+5.21%) + ~0% box-migration (−0.004pp,
identical argmax box set both eras) + ~0% background (cosmic ratio =
1.0000 exactly; dio <0.0005% of bkg), with residual-beyond-ce_abs_eff =
+0.27% ± 0.26% (1.1σ, not significant). Baseline pair +4.82% ± 0.23%
(supersedes carried +4.8%) = ~100% acceptance-at-fixed-box + 0%
box-migration (identical shared argmax box) + 0% background (cosmic ratio =
1.0000 exactly), residual-beyond-ce_abs_eff = +0.71% ± 0.46% (1.6σ, not
significant, n=1 no replicate). Both groups: the +4.9%/+4.8% sob shift is
essentially entirely explained by the `ce_abs_eff` normalization-input
ratio audited in §2.3 — the momentum test box does not move and background
(cosmic-dominated; DIO is <0.0005% of total bkg at the optimal box) does
not change between eras. *Caveat: "0% background" above is unchanged by
construction within this macro's model, not an independently-confirmed
physical invariant — `cosmic` (§4.1, `rough_run1a_sensitivity.C:174-179`)
is computed from fixed globals with no era or config dependence, so it
would print identically even if real cosmic-ray background conditions
genuinely differed between Run1Bak and Run1Bap; this analysis cannot rule
that out, it can only say the macro's background term is unchanged.***

## 5. Spectra + flash

Closes the two remaining Phase-2 items: does the CE spectrum *shape* also
shift (vs. the pure event-count/normalization effect established in §2-§4),
and does the flash side of the shift (declared −4.1% champion / +6.3%
baseline in the design doc) hold up under a proper accounting with σ.

### 5.1 Tree inspection — the brief's `t1`/`e`/`w` premise was wrong (Step 1)

Per the brief, `$SCRATCH/tree_inspect.py` opened
`foilsflashBASIN01_00/harvest/nts.ce.root` and looked for a top-level `t1`
tree. **`f.Get("t1")` returned null.** `f.ls()` showed the file's only
top-level object is a single `TDirectoryFile EDepAna`, containing four
cut-tier subdirectories `hist_0`..`hist_3` (`hist_0` "all events", `hist_1`
"edep 1 MeV", `hist_2` "edep 10 MeV", `hist_3` "edep 50 MeV") — no tree
anywhere in the file (`$SCRATCH/tree_inspect2.py`/`tree_inspect3.py`
confirm this by directory listing).

Re-reading `Run1BAna/workflows/scripts/rough_run1a_sensitivity.C` explains
the mismatch: `TTree tree("t1","t1")` at **line 7**, inside
`get_dio_spectrum()`, is a **local helper tree used only to parse a fixed
theoretical DIO table file**
(`/exp/mu2e/app/users/mmackenz/run1b/Run1BAna/data/heeck_finer_binning_2016_szafron.tbl`,
`tree.ReadFile(table,"e/D:w/D")`, `:8-11`) — it has no connection to
`nts.ce.root` at all; it is the same `t1`/`e`/`w` names Task 4 saw while
reading the macro, misattributed. The macro's **actual** CE-signal input
(what `sig_eff`/`ce_abs_eff` scales, per §4.1) is read directly as a
histogram: `TH1* h_sig = (TH1*) sig_file->Get("EDepAna/hist_2/trk_front_energy")`
(`:119`), and `response = ...Get("EDepAna/hist_2/trk_front_energy_diff")`
(`:120`) — both `TH1F`, not trees. `hist_2` ("edep 10 MeV") is one of the
four cut-tier directories.

**Adjustment made (brief explicitly allows this):** `$SCRATCH/spectra.py`
was rewritten to load `EDepAna/hist_2/trk_front_energy` (and, for a
population cross-check, `EDepAna/hist_0/trk_front_energy`) as `TH1F`
objects directly, rather than `Draw("e>>h","w")` off a nonexistent tree.
`hist_2` is binned 1500×[0,150] MeV — the CE endpoint (~104.97 MeV/c) and
the macro's signal box (103.1-104.7, §4.2) sit comfortably inside this
range, so no range adjustment was needed once the correct object was
identified.

### 5.2 Population cross-check: histogram entries vs audited `ce_seen` (Step 2)

`hist_0` ("all events", no edep cut) is expected to reproduce `ce_seen`
("EdepAna summary: Saw N events" in `harvest/edep.log`, `EDEP_SAW_RX`,
§2.1) almost exactly, since both count every event EdepAna processed with
no downstream selection. Confirmed directly:

```
foilsflashBASIN01_00: hist_0 entries=474023  vs ce_seen=474026  (diff -3)
ipafixAB01:           hist_0 entries=580254  vs ce_seen=580262  (diff -8)
foilsflashHOLEDhi:    hist_0 entries=530647  vs ce_seen=530651  (diff -4)
nominalAB01:          hist_0 entries=595228  vs ce_seen=595233  (diff -5)
```

Match to <0.002% (a handful of events fall outside the histogram's [0,150]
MeV binning range and are silently dropped from the `TH1`, while still
counted in EdepAna's own `Saw N events` line — a fill-vs-counter edge
effect, not a population mismatch). **Entries-ratio cross-check against the
established `ce_seen` ratio (self-review requirement):**

```
Pair 1 (BASIN01_00 vs ipafixAB01): hist_0 ratio = 1.22411 (+22.411%)  vs  ce_seen ratio = 1.22411 (+22.411%)  — MATCH
Pair 4 (HOLEDhi vs nominalAB01):   hist_0 ratio = 1.12170 (+12.170%)  vs  ce_seen ratio = 1.12170 (+12.170%)  — MATCH
```

Exact match (5 significant figures) confirms `nts.ce.root`'s `hist_0` is
reading the identical landed-file population already audited in §2 — this
is a data-integrity check, not a physics cross-check: these single-pair
ratios are naturally much larger than the audited group `ce_abs_eff`
shift (+4.93%/+4.08%, §2.3) because raw `ce_seen` is not yet normalized by
`ce_simulated_events`/`stopping_factor` (BASIN01_00 ran 900k simulated CE
events vs ipafixAB01's 1050k — different job counts, not a shift), exactly
as the `ce_abs_eff` formula (§2.1) already accounts for.

### 5.3 Shape comparison — mean/RMS/KS at the CE peak (Step 2)

`$SCRATCH/spectra.py` output, `hist_2` (`trk_front_energy`, the macro's
`h_sig` input):

```
                        entries  mean(MeV)  rms(MeV)
foilsflashBASIN01_00:   444637   102.7048    4.0696
ipafixAB01:             545791   102.5911    4.4477     hist_2 entries ratio +22.750%
foilsflashHOLEDhi:      499248   103.4528    3.2699
nominalAB01:            561134   103.3952    3.5644     hist_2 entries ratio +12.396%

KS prob (full 0-150 MeV binning):        Pair1 = 2.514e-14   Pair4 = 7.288e-11
mean shift (full range): Pair1 -0.1138 MeV (-0.111%, 13.3sigma)  Pair4 -0.0576 MeV (-0.056%, 8.7sigma)
```

At face value the full-range KS/mean-shift figures look like a real shape
change — but at N~4.4e5-5.6e5 events, a KS test is powerful enough to
reject the null on infinitesimal bin-level fluctuations, and the full-range
`hist_2` mean/RMS is dominated by the **sub-peak tail** below the CE box
(a broad low-energy population between the "edep>10 MeV" cut and the CE
peak, ~9-10% of `hist_2`'s events for the champion pair, ~5% for baseline)
— not the box-relevant CE peak itself. Restricting to **[100,106] MeV**
(bracketing the macro's signal box, 103.1-104.7 / 103.9-104.7, §4.2)
isolates the physically relevant comparison:

```
                                        mean(MeV)   rms(MeV)   frac of hist_2
Pair 1  foilsflashBASIN01_00 [100,106]:  103.6793    0.9735      91.1%
        ipafixAB01           [100,106]:  103.6800    0.9670      90.6%
        dmean = +0.0007 MeV  dRMS = -0.67%

Pair 4  foilsflashHOLEDhi    [100,106]:  104.0534    0.7816      94.8%
        nominalAB01          [100,106]:  104.0625    0.7780      94.6%
        dmean = +0.0091 MeV  dRMS = -0.47%

KS prob ([100,106] MeV only): Pair1 = 8.721e-13   Pair4 = 1.376e-16
```

**At the box, the mean shift essentially vanishes** (+0.0007 MeV / +0.0091
MeV — three orders of magnitude below the box scan's 0.2 MeV/c grid step,
§4.2, and consistent with §4.3's box-migration finding of −0.004
percentage points / "identical argmax box set both eras") and RMS changes
by <1% either direction. The KS test still rejects the null at these
statistics (N~4-5×10^5 is enough power to detect any nonzero bin
difference) — this is a **statistical-power artifact, not a physically
meaningful shape difference**: the same N~5×10^5 regime that makes the
13σ/8.7σ full-range mean shift "significant" while it is only a −0.11%/
−0.06% relative change. Visual overlays (`$SCRATCH/spec_*.png`, read
directly, both pairs) show the historical (red) and arm (blue) curves
overlapping essentially everywhere, including the sharp ~104.97 MeV/c
CE-endpoint edge and the radiative-tail shape below it — no visible peak
shift, broadening, or edge displacement in either pair.

**Verdict for 5.1-5.3: the CE spectrum SHAPE is unchanged between eras at
the box.** Mean/RMS at the box-relevant [100,106] MeV window differ by
<0.01 MeV / <1% (both far below the box scan's 0.2 MeV/c resolution); the
full-range KS/mean-shift figures that look large are a statistical-power
artifact of N~5×10^5 combined with a sub-peak tail-population effect
unrelated to the CE peak. This is consistent with — not in tension with —
§4's finding that the sob shift is a pure `ce_abs_eff`-normalization effect
with no box migration: **more events survive the mustops_ce→EdepAna chain
under Run1Bap (the hist_0/ce_seen entries-ratio match, §5.2), and those
extra events populate the SAME spectral shape**, not a shifted or widened
one.

### 5.4 Flash-side accounting (Step 3, no ROOT)

`$SCRATCH/flash_accounting.py` builds the table from `summary_table.tsv`
(§1) plus the design-doc-carried champion figures, and propagates σ from
the reference `σ_flash = 2.52% @ N=100 elebeam jobs` scaled as `σ(N) =
2.52% × √(100/N)` (Poisson counting-stat scaling; anchor-checked against
the brief's second reference point, `N=400 → ~1.3%`: `2.52×√(100/400) =
1.26%` ≈ "~1.3%", confirming the scaling law). `N` (elebeam job count) is
`flash_n_files` from `summary_table.tsv`, except `foilsflashSOBX01` (column
blank in the harvest — recovered as `flash_n_input/110000 = 19,250,000/110,000
= 175`, where 110,000 events/job is confirmed constant across every other
config's `flash_n_input/flash_n_files`) and `foilsflashHOLEDhi` (its own
`summary.json` lacks flash fields entirely, per §1's Note — its flash
figure is the deck/wiki-quoted historical value from the dedicated
high-stats matched A/B test, `wiki/log.md` 2026-06-30, **400 elebeam jobs**
for both `NOHOLEhi`/`HOLEDhi`).

**Per-config flash + σ:**

| config | role | flash_edep_per_pot | N (elebeam jobs) | σ_flash |
|---|---|---|---|---|
| `foilsflashSOBX01` | champion historical | 1.080643e-6 | 175 | 1.905% |
| `foilsflashBASIN01_00` | champion historical | 1.080318e-6 | 100 | 2.520% |
| `foilsflashC400_champ` | champion historical | 1.063997e-6 | 400 | 1.260% |
| `ipafixAB01` | champion arm A (distFromTargetEnd=491.67, no override) | 1.035815e-6 | 99 | 2.533% |
| `ipa625AB01` | champion arm B (distFromTargetEnd=625.0, no override) | 1.032668e-6 | 100 | 2.520% |
| `ipaovrAB01` | champion arm C (=A + override pair restored) | 1.058556e-6 | 99 | 2.533% |
| `foilsflashHOLEDhi` | baseline historical (deck/wiki-quoted) | 6.445e-7 | 400 | 1.260% |
| `nominalAB01` | baseline arm (Run1Bap deployed stack) | 6.854431e-7 | 100 | 2.520% |

**Champion decomposition** (historical mean n=3 = 1.074986e-6, relσ=1.134%;
arm A/B mean n=2, no override = 1.034242e-6, relσ=1.786%; arm C, override
restored = 1.058556e-6, relσ=2.533%):

| quantity | ratio | shift | σ | significance |
|---|---|---|---|---|
| total: mean(A,B) / historical mean (no-override arms vs historical) | 0.96210 | **−3.79%** | ±2.12% | 1.79σ |
| (a) **override-pair contribution**: C / mean(A,B) | 1.02351 | **+2.35%** | ±3.10% | 0.76σ |
| (a′) seed-paired cross-check: C / A (both N=99, seed-matched) | 1.02195 | **+2.20%** | ≤3.58% (upper bound, see below) | — |
| (b) **residual version shift**: C / historical mean | 0.98472 | **−1.53%** | ±2.78% | 0.55σ |

Multiplicative consistency: `(1 + total)(1 + override) = (1 + residual)` —
`0.96210 × 1.02351 = 0.98472`, exact to 5 sig figs, confirming the
decomposition is arithmetically closed.

**Seed-pairing note (brief's explicit ask):** `ipafixAB01` (A) and
`ipaovrAB01` (C) are the **only same-N pair** among the three champion arms
(both N=99). Per the wiki `elebeamcat-tape-migration...`/2026-07-26 log
entry, the elebeam template pins a fixed `baseSeed:1` +
`MaxEventsToSkip:319542` + `run_number 1810` for every config — so two
configs with the **same job count** process the **literally identical**
EleBeamCat input population (same subrun draw per job index), differing
only in downstream geometry. A vs C is therefore a genuinely paired
comparison: **+2.20%**, matching (a′) — and this figure is exactly the
source of the design doc's carried "arm C ... worth +2.2%" figure, traced
here to the precise seed-matched A-vs-C pair rather than the C-vs-mean(A,B)
group comparison (+2.35%, (a) above). The naive independent-quadrature σ
(±3.58%) quoted for (a′) is an **overestimate** for a seed-paired
comparison — input-sampling (Poisson) noise cancels between A and C by
construction; the true residual noise on a seed-paired difference (G4/
EdepAna stochastic scatter only) cannot be quantified from these summary
artifacts alone (no per-event data was pulled), so no tighter number is
asserted — flagged as an open precision gap, not resolved here.

**Reading:** (b) the residual version shift (−1.53% ± 2.78%, 0.55σ) is
**not statistically significant** — consistent with zero. Once the
override-pair geometry is restored to match the historical configs (arm
C), no further Run1Bak→Run1Bap effect on flash is resolvable within this
σ budget. **Essentially the entire −3.79% champion-arm flash gap is
attributable to the override-pair removal** (+2.20-2.35% of the
compounded −3.79%), not to a version-driven flash effect — this is a
genuinely different conclusion from the sob/`ce_abs_eff` side (§2-§4),
where the version-driven acceptance shift was the dominant, highly
significant (>10σ) effect. Flash and sob are different observables on
different chains (elebeam/DS-off vs mustops_ce/DS-on) and there is no a
priori reason they should share a mechanism; this section's finding is
that they evidently do not.

**Baseline pair** (`foilsflashHOLEDhi` → `nominalAB01`):

| quantity | ratio | shift | σ | significance |
|---|---|---|---|---|
| nominalAB01 / HOLEDhi | 1.06353 | **+6.35%** | ±2.82% | 2.25σ |

This is mildly significant (>2σ) and, critically, **opposite in sign** from
the champion group's net shift (−3.79% before accounting for the override,
−1.53% after). Per the brief, the baseline pair carries **two stated
confounds** that the champion arms do not:

1. **Unequal job counts, no seed-pairing possible.** `foilsflashHOLEDhi`
   ran at 400 elebeam jobs (σ≈1.26%, from the dedicated high-stats A/B
   test) vs `nominalAB01` at 100 (σ≈2.52%) — the two job counts do not
   match, so (unlike champion's A-vs-C) the deterministic
   `baseSeed=index+1` structure does **not** give this pair a matched
   EleBeamCat input population; the comparison is a plain independent one,
   at its full naive-quadrature σ (±2.82%, no tightening available).
2. **Different emission mechanism.** The two configs write the deployed
   37-foil stack via different code paths — `foilsflashHOLEDhi` is a
   `foils`/foilsflash-mode template with the up/down-extras seam pinned to
   `N_UP=N_DOWN=0`, while `nominalAB01` is a `nominal`-mode template that
   writes the stack out explicitly via `base_*` consts (Task 3 §3.1 Pair
   4). §3.1 already proved this difference is **geometrically inert** — an
   order-independent set-diff shows byte-identical resolved key/values —
   but it remains a *provenance* confound (different template code paths)
   even though not a *geometry* confound.

**Additional note (not in the brief, found while cross-referencing §3.1):**
the baseline pair's raw rendered-geom diff (Task 3 §3.1 Pair 4) reduces, after
normalization, to **exactly the same override-pair-removed delta** found in
the champion pair (Pair 1: `tracker.inDS2Vacuum`/`ds2.halfLength=3825`
removed, `zEMCSourceInMu2e` added going historical→arm). If the champion's
measured override-pair effect (+2.20-2.35%, restoring override *raises*
flash) transferred identically to the baseline geometry, the *un-restored*
baseline arm (`nominalAB01`, override absent, like champion's A/B) would be
predicted to sit **below** `HOLEDhi` by a comparable margin — the same
qualitative direction as the champion group's total gap (−3.79%). Instead
the baseline pair moves **substantially positive** (+6.35%). No
override-restored arm exists for the baseline geometry (no baseline analog
of arm C), so this cannot be decomposed the way the champion group was —
flagged as an open question: **the override-pair effect measured at the
champion x-point does not obviously transfer to (or is swamped by some
other, larger effect at) the deployed-baseline geometry.** This is
consistent with — not contradicted by — the two stated confounds, but goes
beyond them as an additional, unresolved observation.

**Verdict: CE spectrum unshifted (KS=8.7e-13/1.4e-16 at [100,106] MeV —
formally rejects at N~5×10^5, but this is a statistical-power artifact, not
a physical shape change: Δmean <0.01 MeV, ΔRMS <1% at the box, both ≪ the
0.2 MeV/c box-scan grid; `hist_0` entries-ratio matches the audited
`ce_seen` ratio exactly for both pairs, confirming pure event-count
normalization per §2-§4).
Flash shift = override (+2.20% seed-paired / +2.35% group-mean, both
sub-1σ alone) + residual version shift (−1.53% ± 2.78%, 0.55σ, consistent
with zero) — i.e. the champion flash gap (−3.79% ± 2.12%, 1.79σ) is
essentially fully explained by the override-pair geometry difference, with
no significant residual Run1Bak→Run1Bap flash effect once it is accounted
for. Baseline-pair flash shift (+6.35% ± 2.82%, 2.25σ) runs the OPPOSITE
sign from the champion group and is not decomposable the same way — its
two confounds (job-count mismatch/no seed-pairing; different emission
mechanism, proven geometrically inert but still a provenance difference)
are stated per the brief, plus an additional open observation that the
champion-derived override effect does not obviously explain the baseline
pair's sign or magnitude.**

## 6. Environment diff

Targets the implicated quantity from Tasks 4-5 directly: event-level CE
acceptance (`ce_seen/ce_simulated`, the fraction of simulated CE events
surviving the `mustops_ce` chain into EdepAna) at an **unchanged energy
response** (§5: Δmean <0.01 MeV, ΔRMS <1% at the box). Candidates are judged
against that mechanism test: can this delta move an event *count* without
moving the *energy scale*? `$GRID = /exp/mu2e/data/users/oksuzian/autoresearch_grid`.
Release roots: `ROOT_BAK=/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/backing`,
`ROOT_BAP=/cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bap/backing` (both
hold `geom_run1_a.txt` at `Offline/Mu2eG4/geom/geom_run1_a.txt`, confirmed by
direct `find -L`, Step 1).

### 6.1 Geometry base-tree diff (Steps 1-3)

`$SCRATCH/resolve_geom.py` — verbatim from the brief, a SimpleConfig
`#include`-chain resolver with last-wins key/value semantics, trying
`root/inc` then `root/Offline/inc` for each include (handles both release
layouts).

**Self-test (required before trusting any cross-tree diff):**
```
$ python3 resolve_geom.py "$GEOM_BAK" "$ROOT_BAK" "$GEOM_BAK" "$ROOT_BAK"
# total keys: bak=6283 bap=6283 differing=0
$ python3 resolve_geom.py "$GEOM_BAP" "$ROOT_BAP" "$GEOM_BAP" "$ROOT_BAP"
# total keys: bak=6283 bap=6283 differing=0
```
**Self-test PASSES on both sides** (identical tree vs itself → `differing=0`,
6283 keys resolved each time) — the resolver is trusted.

**Cross-tree diff:**
```
$ python3 resolve_geom.py "$GEOM_BAK" "$ROOT_BAK" "$GEOM_BAP" "$ROOT_BAP"
# total keys: bak=6283 bap=6283 differing=0
```
**Zero differing keys.** The entire resolved `geom_run1_a.txt` include tree —
every `double`/`int`/`bool`/`string`/`vector<...>` key that GeometryService
would see for this base file — is identical between Run1Bak and Run1Bap.

**Verification beyond the resolver (not asserted, checked):** the resolver's
"seen" file set (421 transitively-`#include`d files, `$SCRATCH/included_files.txt`)
was diffed pairwise, byte-for-byte, between the two release roots:
```
$ <loop: diff -q $ROOT_BAK/$rel $ROOT_BAP/$rel for each of 421 included files>
total included files: 421, byte-differ: 0, missing: 0
```
All 421 files are byte-identical, not merely KV-resolved-identical — this
rules out both a resolver blind spot (e.g. a value changed in one file and
silently compensated in another) and any comment/formatting-only difference
this task might have waved away. The top-level `geom_run1_a.txt` file itself
also matches by md5 (`582733d150f60940c1d5455d68c7c636` both sides).

Confirmed this is the file actually loaded at run time, not a resolver-only
artifact: both configs' rendered per-config geom overlays open with
`#include "Offline/Mu2eG4/geom/geom_run1_a.txt"` verbatim
(`$GRID/foilsflashBASIN01_00/geom/*_geom.txt`,
`$GRID/ipafixAB01/geom/*_geom.txt`, first line of each) — i.e. `mu2e`
resolves this exact `#include` against whichever release's
`MU2E_SEARCH_PATH` the job actually ran under.

**Sanity check that the resolver isn't blind (the two releases genuinely
differ elsewhere in `Mu2eG4/geom/`, just not in this chain):** `diff -rq`
on the two `Mu2eG4/geom/` directories directly turns up 7 differences —
`crv_counters_extracted_v03/v04.txt` (new in Run1Bap), `geom_common_extracted.txt`
(differs — its own `#include` bumped `v02`→`v04`), `geom_common_extracted_v03/v04.txt`
(new in Run1Bap), `geom_run1_b_v40.txt` (differs — adds
`degrader.supportArm.offsetz/dz`, comments out `tracker.inDS2Vacuum`), and
`ProductionTarget_Stickman_v1_0.txt` (differs — Inconel718 plate-list
formatting/comment changes). Traced each: `geom_common_extracted.txt` is
`#include`d only by `geom_common_trackerVST.txt`/`geom_common_trackerStationVST.txt`
(VST test-stand geoms, not Run1A); `geom_run1_b_v40.txt` is `#include`d only
by `geom_run1_b_ds_on_v40.txt` (the DS-on **Run1B** production chain, a
different physics config from our Run1A `mustops_ce`); `ProductionTarget_Stickman_v1_0.txt`
is `#include`d only by `geom_run1_a_stickman.txt` (a Stickman-PT variant of
Run1A, not the plain `geom_run1_a.txt` our configs use). None of the 7
differing files are reachable from `geom_run1_a.txt`'s own include chain —
consistent with, not contradicting, the resolver's `differing=0` result.

**Classification: geometry-config candidate set is EMPTY.** Every key the
mustops_ce stage's `GeometryService` resolves from the base include tree is
byte-identical between Run1Bak and Run1Bap — there is nothing here that
could move `ce_abs_eff` in either direction. This goes strictly further than
Task 3 (§3.1), which only diffed the *rendered* per-config geom file (the
literal `#include` line plus our own override lines) and therefore could not
see whether the two releases' copies of `geom_run1_a.txt`'s *resolved
content* differed — this section closes exactly that gap the Task 3 brief
flagged, and finds nothing.

### 6.2 Job-config diff (Step 4)

**Materialized-FCL diff (ours, the two grid configs' actual submitted FCLs):**
```
$ diff $GRID/foilsflashBASIN01_00/state/mustops_ce_template_materialized.fcl \
       $GRID/ipafixAB01/state/mustops_ce_template_materialized.fcl
18c18
< services.GeometryService.inputFile:  "autoresearch_foilsflashBASIN01_00_geom.txt"
---
> services.GeometryService.inputFile:  "autoresearch_ipafixAB01_geom.txt"
```
Exactly the expected near-identical result — the only delta is each config's
own geometry-overlay filename (already fully audited, §3.1). No semantic
FCL-authoring delta between the two configs' own submitted job files.

**`mu2e --debug-config` (subagent shells, muse setup one-shot per shell,
`SPACK_USER_CACHE_PATH` set before sourcing CVMFS per the brief):**
```
# shell 1 (Run1Bak): muse setup ops && muse setup SimJob Run1Bak
#   mu2e --debug-config cfg_bak.txt -c .../foilsflashBASIN01_00/.../mustops_ce_template_materialized.fcl
#   banner: art v3_15_00  root v6_32_06  KinKal v03_05_01 | build al9-prof-e29-p094
#   exit 0, cfg_bak.txt = 1702 lines
# shell 2 (Run1Bap): muse setup ops && muse setup SimJob Run1Bap
#   mu2e --debug-config cfg_bap.txt -c .../ipafixAB01/.../mustops_ce_template_materialized.fcl
#   banner: art v3_15_00  root v6_32_06  KinKal v03_06_00 | build al9-prof-e29-p101
#   exit 0, cfg_bap.txt = 1721 lines
```
Both succeeded cleanly (exit 0), no errors in either `/tmp/m1.log`/`/tmp/m2.log`.

**`diff $SCRATCH/cfg_bak.txt $SCRATCH/cfg_bap.txt`** (full raw diff, 8 hunks,
saved to `$SCRATCH/debug_config_diff_raw.txt`):
```
68a69
>          MaximumCaloPartMom: 1e6
69a71
>          MinimumCaloPartMom: 0
73a76
>          MinimumSumCaloE: 45
251,252c254,255
<                "DoseDeposit",
<                "DelayedDose"
---
>                "PromptDoseAmb",
>                "ResidualDoseAmb"
450a454,468
>       KinKalMaterial: { CRVMaterialName: "CRVModule" ElectronBrehmsFraction: 4e-2
>          GasScatteringFraction: 9.999999e-1 IPAMaterialName: "HDPE"
>          IonizationEnergyLossMode: 1 STMaterialName: "Target"
>          SolidScatteringFraction: 9.99999e-1 elements/isotopes/materials: "Offline/TrackerConditions/data/*.data"
>          strawGasMaterialName: "straw-gas" strawWallMaterialName: "straw-wall" strawWireMaterialName: "straw-wire" }
452c470
<       inputFile: "autoresearch_foilsflashBASIN01_00_geom.txt"     (config-name artifact, already audited §3.1)
---
>       inputFile: "autoresearch_ipafixAB01_geom.txt"
477c495,496
<          ADC2MeV: 6.25e-2
---
>          ADC2MeVCsI: 6.25e-2
>          ADC2MeVlyso: 3.75e-3
1680c1699
<          fileName: ".../cfg_bak.txt"     (debug-config's own output-file self-reference — a tool artifact, not a job delta)
---
>          fileName: ".../cfg_bap.txt"
```
(Full, unabbreviated hunks in `$SCRATCH/debug_config_diff_raw.txt`.)

**Classification, hunk by hunk — every surviving delta traced to its owning
module/service and to whether that module is actually *scheduled* on
`physics.PrimaryPath` (confirmed via `physics.PrimaryPath: [...]`,
`module_label:` list — identical 14-module set both sides:
`TargetStopResampler, generate, genCounter, GenFilter, g4run,
g4consistentFilter, StrawGasStepMaker, CaloShowerStepMaker, CrvSteps,
MakeSS, PrimaryFilter, compressDetStepMCs, FindMCPrimary` plus the
`genCountLogger`/`PrimaryOutput` end-path):**

- **`PrimaryFilter` — RELEVANT, top candidate: TWO independent
  acceptance-relaxing levers found in Run1Bap, both traced to source, both
  only ever widen (never narrow) the `selectcalo` decision.**
  `PrimaryFilter` (`module_type: "DetectorStepFilter"`) **is scheduled** on
  `PrimaryPath`, directly downstream of `StrawGasStepMaker`/`CaloShowerStepMaker`/`MakeSS`
  and upstream of `compressDetStepMCs`/`FindMCPrimary`/`PrimaryOutput` — i.e.
  it is the literal gate that decides which simulated CE events survive into
  the output `.art` file that concat feeds to EdepAna. This is not a
  parallel-subsystem default; it sits *inside* the implicated chain. Traced
  the code: `diff Offline/Filters/src/DetectorStepFilter_module.cc`
  (Run1Bak vs Run1Bap, `$SCRATCH/DetectorStepFilter_module_diff.txt`).

  **Lever 1 — new OR-branch, `MinimumSumCaloE: 45`.** Run1Bap's module
  gained a new **optional** calo-acceptance branch:
  `fhicl::OptionalAtom<double> minSumCaloTotalE{Name("MinimumSumCaloE"), ...}`
  → `useMinSumCaloTotalE_ = conf().minSumCaloTotalE(minSumCaloTotalE_)` (only
  engaged if the key is explicitly present in FHiCL) → in the per-CaloShowerStep
  loop, a running `total_edep` is accumulated across *all* good particles, and
  `if (useMinSumCaloTotalE_ && total_edep > minSumCaloTotalE_) selectcalo = true;`
  — **in addition to**, not replacing, the pre-existing per-particle branch
  (`caloESum` map, code-unchanged). Traced the FHiCL source:
  `diff Production/JobConfig/primary/prolog.fcl`
  (`$SCRATCH/prolog_fcl_diff.txt`) shows Run1Bap's prolog explicitly adds
  `MinimumSumCaloE : 45.0 # or at least this much calo total energy by
  accepted sim particles` (and clarifies the old key's comment to "by a
  single sim particle" — confirming the new key is a genuinely distinct,
  additional criterion, not a rename). Production-repo prolog change paired
  with the Offline-repo C++ change that gives the new key an effect — both
  required together, both land in Run1Bap.

  **Lever 2 — `MinimumCaloPartMom: 0` removes the calo-step momentum floor.**
  *(Correction to an earlier pass of this section, which misclassified this
  as a numerically-inert companion by comparing it against the new field's
  own C++ default instead of against Run1Bak's actual pre-change behavior —
  fixed here.)* Run1Bak's (pre-diff) calo-step loop bounded
  `css.momentumIn()` with the **shared** `minPartM_`/`maxPartM_` members —
  `css.momentumIn() > minPartM_ && css.momentumIn() < maxPartM_`
  (`DetectorStepFilter_module.cc:167` pre-diff) — sourced from the *same*
  `MinimumPartMom`/`MaximumPartMom` keys the tracker-step branch uses
  (`minPartM_(conf().minPartMom())`, `:101`). The materialized configs show
  `MinimumPartMom: 50` **unchanged** in both `cfg_bak.txt`/`cfg_bap.txt` —
  i.e. under Run1Bak, a calo step's parent particle needed momentum >50
  MeV/c to be counted toward *any* calo-based acceptance criterion at all.
  Run1Bap's module splits this into dedicated `minCaloPartM_`/`maxCaloPartM_`
  members (`css.momentumIn() > minCaloPartM_ && css.momentumIn() < maxCaloPartM_`)
  bound to new, independently-configurable `MinimumCaloPartMom`/`MaximumCaloPartMom`
  keys, and Run1Bap's prolog sets `MinimumCaloPartMom: 0.0` explicitly —
  **the 50 MeV/c momentum floor on calo-step particles is removed for
  Run1Bap.** (`MaximumCaloPartMom: 1e6` stays numerically equal to the old
  shared `maxPartM_`≈1e6 either way — the *maximum* bound genuinely is
  inert; only the *minimum* bound is a real relaxation.) This is a second,
  independent lever, and it compounds with Lever 1 two ways: **(a)** it
  widens the calo-step population feeding Lever 1's `total_edep` sum;
  **(b)** it *also* widens the population feeding the pre-existing,
  code-unchanged per-particle `caloESum` branch
  (`if(icalo->second >= minSumCaloE_ && icalo->second <= maxSumCaloE_) selectcalo = true;`,
  `DetectorStepFilter_module.cc:209`, bound to `MinimumSumCaloStepE: 45`,
  numerically unchanged both releases) — so `selectcalo`'s pass rate can
  rise under Run1Bap **even without Lever 1's new key**, purely because
  lower-momentum calo steps (≤50 MeV/c, previously excluded outright from
  the sum) now accumulate toward each particle's 45 MeV calo-energy total.

  **Combined direction.** Both levers only ever *widen* the `selectcalo`
  decision (Lever 1 adds a disjunct; Lever 2 only loosens a bound, from 50
  to 0 MeV/c, never tightens one) — neither can flip an event from passing
  to failing. `retval = (or_ && (selecttrk||selectcalo||selectcrv)) ||
  (!or_ && (selecttrk&&selectcalo&&selectcrv))`, with `ORRequirements`
  (`or_`) defaulting `true` in the C++ and **never set in any Production or
  Offline prolog on either release** (`grep -rn ORRequirements` — zero hits
  in FHiCL on both trees) — so both releases use the identical, unset,
  default-true OR-combination at run time, under which a `selectcalo` that
  can only become *more* true can only make `retval` more permissive too.
  **`PrimaryFilter`'s combined pass rate under Run1Bap can only be ≥
  Run1Bak's for the identical input population — never lower** — a provably
  monotonic, same-direction mechanism for "more CE events produce accepted
  output under Run1Bap," matching the observed sign exactly, now via two
  independent, compounding relaxations rather than one.

- **`KinKalMaterial` (new subtree of `services.GeometryService`) — NOT
  RELEVANT, present but structurally inert for this FCL.** No producer or
  filter on `PrimaryPath` (or anywhere in either `cfg_*.txt`) references
  `KinKal` (`grep -in kinkal` on both dumps: only this one hit, the
  `GeometryService` default block itself). KinKal is Offline's Kalman-filter
  **track-fit** package (bumped v03_05_01→v03_06_00, `services` toolchain
  table, §6.3) — this job is a truth-level generate→G4→digitize→filter
  chain with no track-reconstruction producer scheduled; `GeometryService`
  publishes this material-lookup subtree unconditionally (a new default in
  the newer release) whether or not anything downstream reads it. No
  mechanism to move `ce_seen`/`ce_abs_eff` for a stage that never invokes a
  KinKal fit.

- **`ADC2MeV` → `ADC2MeVCsI`/`ADC2MeVlyso` (`services.ProditionsService.calCalib`)
  — NOT RELEVANT, same reasoning.** This is calorimeter ADC-to-MeV
  *digitization/reconstruction* calibration — consumed by CaloDigi/CaloReco
  producers, neither of which is scheduled on `PrimaryPath` (only the
  truth-level `CaloShowerStepMaker` is present, which produces
  `CaloShowerStep` objects directly from G4 energy deposits, no ADC
  modeling). `ProditionsService` publishes all registered conditions
  entities regardless of whether this job's producer schedule consumes
  them — same "declared but not exercised" pattern as `KinKalMaterial`. The
  CsI/lyso split reflects an evolving two-crystal-type calorimeter model in
  the newer release, with no consumer in this chain to be affected.

- **`Scoring.scorerNames` (`DoseDeposit`,`DelayedDose`→`PromptDoseAmb`,`ResidualDoseAmb`,
  under `physics.producers.g4run.Scoring`) — NOT RELEVANT, block is
  disabled.** Same hunk shows `enabled: false` unchanged on both sides
  (context lines, `$SCRATCH/debug_config_diff_raw.txt`) — the
  Mu2eG4ScoringManager dose-mesh scorer is off entirely for this job; a
  renamed scorer list inside a disabled block cannot affect any output.

- **`inputFile` (config-name) and the debug-config `fileName`
  self-reference — NOT RELEVANT, tool/config-naming artifacts.** The first
  is each config's own geometry-overlay filename (identical mechanism to
  the materialized-FCL diff above, already fully audited in §3.1); the
  second is `--debug-config`'s own output-file path, which necessarily
  differs because `cfg_bak.txt`/`cfg_bap.txt` are different scratch
  filenames — neither reflects a release difference.

**No other hunks exist** — the 8 hunks above are the complete raw diff
(`$SCRATCH/debug_config_diff_raw.txt`).

### 6.3 Toolchain versions (Step 5)

`ups active | grep -iE "^geant4|^art |^root |^g4|^xerces|^cry |^artg4"` in
both shells returned **only the `art` line** — `root`/`geant4`/`xerces`/`cry`/`artg4`
are not `ups`-registered products under either build (`MU2E_SPACK = true` in
`muse status` on both sides: these are resolved via **spack**, not `ups`,
under this Musing generation). Confirmed this is not a fetch miss by
dumping the full unfiltered `ups active` list on both sides (7 products
each: `art, encp, mu2efilename, mu2efiletools, mu2egrid, mu2ejobtools, ups`)
and cross-checking versions via the `mu2e --debug-config` startup banner,
`muse status`'s `MUSE_ENVSET` line, and `spack find` inside each shell.

**Geant4 hash evidence (re-run and captured to file per review — the
original pass asserted the hash-match from uncaptured shell output; this is
the fix):** two additional fresh sourced shells (one per release,
`SPACK_USER_CACHE_PATH` set before sourcing CVMFS, `muse setup` never
piped, one-shot per shell as required), each running
`geant4-config --version`, `spack find -l geant4`, `spack find -lv geant4`
(full hash + build variants), and `env | grep -E "^G4LIB=|^G4INCLUDE="`,
captured to `$SCRATCH/g4_hash_bak.txt` (Run1Bak) and `$SCRATCH/g4_hash_bap.txt`
(Run1Bap). `diff $SCRATCH/g4_hash_bak.txt $SCRATCH/g4_hash_bap.txt` touches
only the environment name/root-spec-count lines and the three genuinely
different packages (`artdaq-core-mu2e`, `kinkal`, new `mu2e-ort`) — every
Geant4-related line is byte-identical across the two files: same
`geant4-config --version` (`11.3.2`), same short hash (`k4bezfr`), same
full spec (`geant4@11.3.2+data~hdf5~ipo~motif~opengl~qt~tbb+threads~timemory~vecgeom~vtk~x11
build_system=cmake build_type=RelWithDebInfo cxxstd=17 generator=ninja`),
same `G4LIB`/`G4INCLUDE` paths (both
`.../geant4-11.3.2-k4bezfrnxuvotgxrwtgcfhjqzagc2iyw/...`). The re-run
**confirms** the original claim rather than contradicting it.

| component | Run1Bak (p094) | Run1Bap (p101) | changed? |
|---|---|---|---|
| MUSE_ENVSET | p094 | p101 | — |
| backing Offline musing | `v13_12_10` | `v13_32_10` | **YES** (many intervening tagged releases) |
| build stub / date | al9-prof-e29-p094, 2026-05-13 | al9-prof-e29-p101, 2026-07-15 | — |
| art | v3_15_00 | v3_15_00 | no |
| ROOT | v6_32_06 | v6_32_06 | no |
| **Geant4** | 11.3.2 (`v4_11_3_p02`) | 11.3.2 (`v4_11_3_p02`) | **no — bit-identical, same spack build hash** `geant4-11.3.2-k4bezfrnxuvotgxrwtgcfhjqzagc2iyw` on both sides (literally the same installed package, not just the same version string; evidence in `$SCRATCH/g4_hash_bak.txt`/`g4_hash_bap.txt`) |
| Geant4 physics data (G4EMLOW/PhotonEvaporation/RadioactiveDecay/G4NDL/G4PARTICLEXS/G4ABLA/G4SAID/G4INCL/...) | 8.6.1/5.7/5.6/4.7.1/4.1/3.3/2.0/1.2 | identical, same paths under the p101 spack-env view | no |
| CRY | 1.7 | 1.7 | no |
| xerces | 0 hits either side (not a discrete spack root spec; bundled under `art`/`root` externals unchanged) | 0 hits | no evidence of change |
| KinKal | v03_05_01 (spack `kinkal@3.5.1`) | v03_06_00 (spack `kinkal@3.6.0`) | **YES, but not exercised** — no KinKal-fit producer on `PrimaryPath` (§6.2) |
| artdaq-core-mu2e | v9_03_00 | v9_04_00 | **YES** — DAQ dataproduct/format bookkeeping, no physics-list/G4/tracker-MC content; not on `PrimaryPath` |
| mu2e-ort (ONNX runtime) | absent (18 root specs) | present, v1.25.1 (19 root specs) | **NEW**, but no ML-inference producer scheduled on `PrimaryPath` — this truth-level chain has no ML-based selection |

**Geant4 is the toolchain's first-class candidate per the brief, and it is
definitively ruled out**: not merely version-matched but the *same spack
build artifact* (identical hash) is loaded by both environments, alongside
identical physics-data table versions — nothing in the G4 transport/physics
engine itself differs between the two eras. art and ROOT are bookkeeping
per the brief and are also unchanged. KinKal, artdaq-core-mu2e, and
mu2e-ort all changed but are excluded by the same "not exercised on
`PrimaryPath`" test applied in §6.2 — none has a scheduled consumer in the
mustops_ce chain. The only toolchain-adjacent fact that *is* real and
substantial is the backing-Offline-musing jump (`v13_12_10`→`v13_32_10`,
many releases apart) — but §6.1 already resolved the one Offline subsystem
that jump could plausibly move for this chain (the geometry base tree) and
found it byte-identical; §6.2 found the one FCL-prolog delta the jump
actually produced that both (a) sits inside the scheduled `PrimaryPath` and
(b) has a stated, monotonic, same-direction mechanism on event count at
unchanged energy response.

**Verdict: candidate deltas = [`physics.filters.PrimaryFilter` — TWO
independent, compounding acceptance-relaxing levers in Run1Bap, both
scheduled on `PrimaryPath`, both provably monotonic same-direction on
event-count acceptance: **(1)** `MinimumSumCaloE` (new `OptionalAtom`-gated
total-calo-energy OR-branch in `Offline/Filters/src/DetectorStepFilter_module.cc`,
engaged by `Production/JobConfig/primary/prolog.fcl`'s new
`MinimumSumCaloE: 45.0` line); **(2)** `MinimumCaloPartMom: 0` (removes the
50 MeV/c momentum floor Run1Bak inherited on calo steps via the shared
`MinimumPartMom`, widening the population feeding both the new branch and
the pre-existing, code-unchanged per-particle `caloESum`/`MinimumSumCaloStepE`
branch — `MaximumCaloPartMom` alone remains numerically inert, 1e6 both
ways)], toolchain = Geant4 11.3.2 **unchanged** (identical spack build hash
`k4bezfrnxuvotgxrwtgcfhjqzagc2iyw` + physics-data tables, captured to
`$SCRATCH/g4_hash_bak.txt`/`g4_hash_bap.txt` — ruled out), art v3_15_00 unchanged, ROOT
v6_32_06 unchanged, KinKal v03_05_01→v03_06_00 and artdaq-core-mu2e
v9_03_00→v9_04_00 and mu2e-ort (new) all changed but **not exercised** on
`PrimaryPath` (no scheduled consumer), backing Offline musing
v13_12_10→v13_32_10. Geometry base-config candidate set is EMPTY (§6.1,
421/421 included files byte-identical, resolver self-test PASS). All other
job-config deltas (`KinKalMaterial`, `ADC2MeV`→`ADC2MeVCsI`/`ADC2MeVlyso`,
`Scoring.scorerNames`) are present-but-inert defaults with no scheduled
consumer on `PrimaryPath`, or self-referential config-naming artifacts.**
