# Run1Bak → Run1Bap +4.9% sob shift — mechanism investigation (design)

**Date:** 2026-08-01
**Status:** approved (brainstormed with operator; goal = mechanism + rule out
our own bug; budget = decompose first, grid only if needed; approach A,
metric-led funnel)
**Context:** `wiki/log.md` 2026-07-28 entries (A/B arms A–D, elimination
ladder); `wiki/projects/bo-foilsflash.md` (migration block);
`leaderboards/leaderboard_ab_*.tsv`; state dirs
`/exp/mu2e/data/users/oksuzian/autoresearch_grid/{ipafixAB01,ipa625AB01,ipaovrAB01,nominalAB01,foilsflashBASIN01_00}`

## Problem

At the identical champion x (`foilsflashBASIN01_00`:
112.4760 / 109.9162 / 0.063100 / 0.144736 / 0.1778 / 0.0000), evaluations
under Run1Bap sit **+4.9% in sob** above the Run1Bak history — 3.90 / 3.91 /
3.90 (n=3, historical) vs 4.10 / 4.11 / 4.11 (arms A/B/C) — **~32σ** on the
declared `obs_noise` 0.006, with flash −4.1%. The deployed baseline moved the
same +4.8% (3.11 → 3.26, arm D), so the *ratio* claim (+25.6% → +25.8%) is
preserved, but old and new rows can never share a GP, and the open
leaderboard archive-vs-baseline-column decision hangs on understanding the
shift.

The 2026-07-28 A/B campaign excluded, by direct paired measurement: **IPA
position** (arm A vs B, Δsob 0.01), **the `tracker.inDS2Vacuum` +
`ds2.halfLength=3825` override pair** (arm C, sob 4.11), and, by inspection,
**`zEMCSourceInMu2e`** (massless VD) and **the analysis binary** (harvest
pins EdepAna to Run1Bak/p094 on both sides, `core/pipeline.py:423-451`).
The standing conclusion — "the Offline **v13_12_10 → v13_32_10** G4
simulation itself" — is an *elimination* result, explicitly flagged
unconfirmed, and the mechanism (what physically changed) is unknown.

## Starting evidence (measured 2026-08-01, from existing harvest artifacts)

Champion x, historical vs Run1Bap arms — `harvest/summary.json`:

| quantity | BASIN01_00 (Run1Bak) | ipafixAB01 | ipaovrAB01 | shift |
|---|---|---|---|---|
| `muminus_stops` | 229,908 | 229,532 | 229,694 | **flat** (−0.1%) |
| `stopping_factor` | 0.095795 | 0.095638 | 0.095706 | **flat** (−0.2%) |
| `ce_abs_eff` | 6.4490e-4 | 6.7555e-4 | 6.7584e-4 | **+4.75%** |
| `ce_seen/ce_simulated` | 0.5267 | 0.5526 | 0.5525 | +4.9% (job-loss-contaminated — audit) |
| `s_over_sqrt_b` | 3.91 | 4.10 | 4.11 | **+4.9%** |

So the target physics (muon stopping) is stable across the version bump; the
whole shift sits in the **conversion-electron efficiency chain**
(`mustops_ce` sim → tracker `StrawGasStep` → EdepAna → sensitivity macro),
with background B implied nearly unchanged (sob and `ce_abs_eff` move
together). Two artifact facts make the decomposition tractable without grid:

- `harvest/rough_run1a_sensitivity.log` records the **full momentum test-box
  scan** per config (`signal`, `dio`, `cosmic`, S/√B per box). Since
  `s_over_sqrt_b` is a *max over boxes*, the shift can come from acceptance
  at a fixed box OR from the optimal box migrating (spectrum shift) — both
  distinguishable from the logs already on disk.
- Per-job `count_sim.*.log` files + `edep.log` ("Saw N events") expose the
  landed-file accounting (e.g. ipafixAB01 landed 12/14 CE jobs), so the
  normalization audit has all its inputs.

## Non-goals

- Not deciding the leaderboard archive-vs-baseline-column question (that
  stays with the operator; this work produces its *input*).
- Not launching BO campaigns; not repricing the deck.
- Not fixing anything upstream — a Mu2e report is a possible follow-up
  outside this scope.
- No production code changes. Analysis scripts live in the session
  scratchpad, not the repo; results land in the evidence doc and wiki.

## Design — metric-led funnel

Four phases; each has an exit that can end the investigation early. Grid
time appears only in Phase 4 and is gated on an explicit operator go.

### Phase 1 — normalization & own-bug audit (no grid)

Prove the +4.75% `ce_abs_eff` shift is physics, not accounting or a
migration artifact:

1. Recompute `sob` and `ce_abs_eff` by hand from `edep.log` +
   `rough_run1a_sensitivity.log` + `count_sim` per-job logs for all six
   configs (3 historical, 3 arms), confirming every denominator is
   per-landed-file (job loss differs across arms and history).
2. Diff the rendered geoms historical-vs-arms (expect exactly the known
   deltas: override pair, IPA dist, `zEMCSourceInMu2e`).
3. Verify the tarball each config actually shipped (`Code.*.tar.bz2` is
   preserved in every state dir) — extract and `strings`-check the
   patched-lib markers, confirming historical rows ran the Run1Bak-patched
   lib and arms ran the Run1Bap one.
4. Confirm the harvest env pinning (Run1Bak/p094 EdepAna) did not change
   between the historical harvest dates and the A/B (git log on
   `core/pipeline.py`), and note the cosmetic `Run1Bak_*` dataset naming in
   arm harvest dirs is naming only.

**Exit:** "shift survives audit" → Phase 2; or root cause = our bug → write
it up, stop.

### Phase 2 — CE-efficiency decomposition (no grid)

Compare 3 historical champion evals vs 3 Run1Bap arms:

1. From the box-scan logs: sob at the *historical* optimal box vs at each
   config's own optimal box → splits "acceptance rose at fixed box" from
   "box migrated". Extract `signal`, `dio`, `cosmic` at both boxes.
2. From `nts.ce.root` (PyROOT under `muse setup` — uproot cannot read these,
   see wiki incident): CE momentum/edep spectra overlaid, historical vs
   arms; count events at each cut stage if the trees expose them.
3. Decompose sob into S and B contributions and state which carries the
   +4.9%.
4. Account for the **flash** side of the shift as well: champion −4.1%
   (1.0803e-6 → 1.0327/1.0358e-6) vs nominal **+6.3%** (6.445e-7 →
   6.854e-7), with arm C measuring the override pair alone worth **+2.2%**
   of it. The `--x-point` seed structure is deterministic (`baseSeed =
   index+1`), so historical-vs-arm flash comparisons are near-paired;
   state the residual after the override contribution and whether it is
   resolvable against σ_flash 2.52% @ N=100.

**Exit:** one implicated quantity (e.g. "CE tracker-hit efficiency at fixed
box +5%, spectrum unshifted" or "spectrum hardened, box moved").

### Phase 3 — targeted environment diff (no grid)

Read only the layer Phase 2 implicates:

1. **Geometry config:** textually resolve the `geom_run1_a.txt` include
   chain under both Musings (plain-text `#include` walk, python) and diff
   the fully-resolved key/value sets. The base-include content differing
   between Offline versions is a co-introduced candidate the A/B arms never
   isolated.
2. **Job configuration:** `mu2e --debug-config` (or `--annotate`) of the
   materialized mustops_ce chain under both Musings, diffed — captures the
   Production version delta.
3. **Toolchain:** Geant4 / art / ROOT versions pinned by envset p094 vs
   p101 (read the envset files on cvmfs).
4. **Code:** Offline release notes + `git log v13_12_10..v13_32_10` scoped
   to the implicated subsystem (e.g. Mu2eG4 physics config, TrackerMC /
   StrawGasStep, EM options) — not a blind sweep of all ~20 intermediate
   versions.

**Exit:** a named candidate (specific config line, FCL parameter, G4 version
bump, or Offline commit) consistent with Phase 2's quantity — or a short
list needing Phase 4.

### Phase 4 — conditional paired grid arm(s) (gated)

Only if Phases 1–3 leave ≥2 live candidates, or one candidate needs direct
proof. Reuse the proven throwaway JSON-clone arm method (own leaderboard,
`SHIPPED_SPECS` temporarily extended, paired deterministic seeds at the
champion x, delete specs after):

- **Config-level candidate** → Run1Bap arm with the candidate line(s)
  reverted to their Run1Bak-resolved values. Binary read-out: sob returns
  to ~3.90 (cause found) or stays ~4.10.
- **Code-level candidate** → the Run1Bak+override control arm with today's
  harness (expected ~3.90) — this is also the direct confirmation that
  closes the elimination gap, if the operator wants it regardless.

Each arm is one eval, ~4–5 h wall. One at a time; every launch individually
approved by the operator.

## Error handling

- Historical champion replicas: identify the n=3 configs by grepping the
  leaderboard for the exact champion x. If any state dir is missing its
  harvest artifacts, fall back to the surviving replicas (n≥1 suffices for
  the decomposition; the 3-replica spread just tightens it).
- `nts.ce.root` reads go through PyROOT under `muse setup`
  (uproot `NotImplementedError` on `mu2e::StepPointMC` vectors — wiki
  incident) with `SPACK_USER_CACHE_PATH` exported first; harvest-side NFS
  hangs are killed per the harvest-pyroot incident recipe.
- If `--debug-config` needs a full env the sandbox can't source, run it via
  a subagent shell (session-known limitation: controller Bash can't source
  cvmfs setups).

## Testing / verification discipline

- Every headline number in the evidence doc is recomputed independently of
  `summary.json` (from the underlying logs) at least once.
- Any claim of "flat" or "shifted" carries its σ against the measured noise
  (σ_sob 0.4%, σ_flash 2.52% @ N=100; paired-seed arms tighter).
- Phase conclusions are written to the evidence doc as they land, not at
  the end (compaction-proof).

## Deliverables

- `docs/run1bak_run1bap_shift_evidence.md` — decomposition tables, audit
  verdicts, candidate ledger with per-candidate status
  (excluded/confirmed/open + strength of evidence).
- Wiki: `bo-foilsflash` key-facts update; `log.md` entries as facts land;
  a new concept page for the shift mechanism once named (page name decided
  when the mechanism is known).
- A stated recommendation *input* for the leaderboard decision (e.g.
  "multiplicative +4.9% on sob, geometry-independent within measurement →
  baseline-column with a fixed scale factor is defensible" — or whatever
  the evidence supports).

## Rollback

Nothing to roll back in Phases 1–3 (read-only analysis). Phase 4 arms are
throwaway modes with their own leaderboards, deleted after use — identical
lifecycle to the 2026-07-28 A/B arms (whose four specs are still pending
their own approved deletion).
