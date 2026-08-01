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
not change between eras.**
