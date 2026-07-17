# bo-noise-budget

**Type:** concept
**Status:** active
**Updated:** 2026-07-13 (GP noise audit logged + first reading)

> **Per-stage wall MEASURED, full n=10 (foilsflash09 all children, 2026-07-09;
> state-file timeline = submit→outputs):** mubeam(15j) mean 87 (34-115),
> concat(1j) 14 (6-30), **mustops_ce(15j) mean 111 (75-175) = longest stage**,
> elebeam_flash(200j) 90 (79-103), inter-stage gaps ~25 min/eval (poll ticks +
> node transitions); eval total ~5.4h vs ~100 min of payload. ff10 (n=8)
> reproduces: mubeam 90 (83-97). Three structural reads: (1) EVERY G4 stage
> runs ~3× its ~30-min payload — overhead (queue+stragglers+poll cadence)
> is uniform, no stage is compute-bound; (2) **narrow 15-job stages are the
> ERRATIC ones** (mubeam 34-115, mustops 75-175 on identical payloads —
> quorum 13/15 still waits on stragglers, one slow node ≈ doubles the stage)
> while 200-job elebeam is the MOST predictable (79-103; width averages
> stragglers); (3) by GRID-HOURS elebeam still dominates ~85%. Fixes ranked:
> overlap elebeam (hides its 90 min → eval ~3.5h); consider quorum 13→12/15
> on the narrow stages to clip the 175-min tail (σ_sob 0.09% has huge margin);
> capacity fix = fewer-bigger elebeam jobs (200×110k→100×220k).
> **"Do we need concat?" (2026-07-09): functionally YES, as a GRID stage no.**
> concat is NOT a merge — it runs `MuonStopSelector.fcl` (species split:
> TargetStops → MuminusStopsCat + MuplusStopsCat), and harvest Step 2 counts
> events in MuminusStopsCat for the `stopping_factor = muminus_stops /
> mubeam_sim_total` denominator (pipeline.py ~:1171-1215) — the per-geometry
> stopping rate. Dropping it means (a) TargetStopResampler feeds mixed-species
> stops to the Ce generator, (b) the mu⁻-stop count needs a SimParticle-level
> counter instead of a cheap event count, (c) MaxEventsToSkip=100720 retuning.
> But it's `ships_geom: False`, no G4, 1 job — its ~14 min wall + ~25 min
> submit/poll cycle is almost all grid latency. Cheapest ~35-40 min/eval
> (~12%) saving: run it LOCALLY (`mu2e -c MuonStopSelector.fcl -S
> mubeam_outputs.txt`, minutes of CPU, xrootd reads) instead of via jobsub.
> **Deeper follow-up "do we need MuonStopSelector?" (2026-07-09): the
> SELECTION is redundant, the FILTER is not — and it can move upstream.**
> CeEndpoint_module.cc re-does the identical selection internally
> (`stoppedMuMinusList` = PDG 13 + ProcessCode muMinusCaptureAtRest, same
> codes as muminusSelector's ParticleCodeFilter) but **THROWS
> cet::exception(BADINPUT) on any event with no stopped mu⁻** — and mubeam's
> TargetStops is charge-mixed (TargetMuonFinder `particleTypes: [13, -13]`,
> pileup/prolog.fcl:41). Measured contamination (foilsflash09R00_00 art.json):
> MuminusStopsCat 258,945 ev vs MuplusStopsCat 2,372 ev ≈ 0.9% → a
> 2500-event mustops_ce job fed raw TargetStops dies with prob ≈ 1−0.991²⁵⁰⁰
> ≈ 100%. So raw-TargetStops resampling is a guaranteed-abort, NOT a small
> bias. Clean kill path: fold `muminusSelector` into mubeam's
> `targetStopPath` (right after TargetStopFilter; same-path product is
> visible downstream) → TargetStopOutput becomes mu⁻-only → DROP the concat
> stage: mustops_ce auxinput=1 over the 15 mubeam files (same structure as
> mubeam↔MuBeamCat), harvest sums `_count_events_art` over 15 files (loop
> already iterates a list), retune `MaxEventsToSkip` 100720 → ≲15k (per-file
> ≈17k events). MuplusStopsCat is consumed by NOTHING in our harvest — free
> to drop. Same ~40 min/eval saving as localizing, but removes a stage
> instead of adding a local-run path.
> **Template change VALIDATED 2026-07-09** (fhicl-dump under Run1Bak, rc=0,
> ff10 in flight so live template untouched): append to
> `pipeline_templates/mubeam/template.fcl` (a) `physics.filters.
> muminusSelector` = the exact ParticleCodeFilter block from
> MuonStopSelector.fcl (`SimParticles: TargetStopFilter`, codes
> `[[13,"uninitialized","muMinusCaptureAtRest"]]`), (b) restated
> `physics.targetStopPath` from MuBeamResampler.fcl:35 with muminusSelector
> inserted between TargetStopFilter and compressPVTargetStops. Dump confirms:
> `@sequence::Pileup.*`/`@sequence::Common.*` PROLOG refs resolve fine in a
> post-include override; final path = [genCounter, protonTimeOffset,
> beamResampler, g4run, g4consistentFilter, TargetStopPrescaleFilter,
> TargetMuonFinder, TargetStopFilter, muminusSelector, compressPVTargetStops];
> `TargetStopOutput.SelectEvents: [targetStopPath]` already → output turns
> mu⁻-only with NO outputs change; other trigger_paths (flash/poly/IPA)
> untouched. Template is SHARED across modes — backward-compatible: modes
> that keep concat just see muminusSelector pass ~100% and an empty
> MuplusStopsCat (nothing consumes it). Rollout gate: apply after ff10 lands
> + one single-eval smoke vs a leaderboard row before any campaign.
> **IMPLEMENTED 2026-07-10** (foilsflash only): mubeam template carries the
> filter; `graph/config.py` foilsflash chain = mubeam→mustops_ce→
> elebeam_flash; `pipeline.py` gained module-level `CONCATLESS = "concat"
> not in GRID_STAGES` gating three seams — mustops submit sources
> `mubeam_outputs.txt`, `_materialize_template` appends
> `MaxEventsToSkip: 8000` for mustops_ce (per-file mu⁻ events ≈16k; shared
> template's 100720 would overrun the slice), harvest counts mu⁻ stops from
> the mu⁻-pure TargetStops files. 93/93 tests pass; live template
> fhicl-dump rc=0. Validation smoke `foilsflashNC01` replays the champion
> geometry: expect muminus_stops ≈ identical (same mubeam seed + same
> filter), flash ≈ 5.976e-7 near-exact (elebeam same-seed), sob 3.31 ±
> ~0.3% (per-file-slice resampling differs from merged-file).
> **Second speed sweep (2026-07-09) — new levers + dead ends:**
> (a) **MEMORY OVER-REQUEST (measured):** elebeam_flash VmHWM = 1311-1313 MB
> across 3 sampled ff09 jobs (near-deterministic), foilsflash mustops_ce
> VmHWM = 1129 MB — both request `memory_mb: 3000` (a HELICAL-line
> inheritance: N_crit≈4144 VmPeak 2.75 GB doesn't apply to foils geometries).
> Right-sizing to 2000 MB improves slot matchability on the 200-job stage
> (85% of grid-hours) and shrinks our footprint against the ~1,250-slot
> ceiling by ~1.5× per job. A/B one child before fleet-wide (watch for
> OOM-holds on extreme foil geometries).
> (b) **ONSITE-ONLY CONFIRMED:** GLIDEIN_Site=FermiGrid in job logs; pipeline
> submit passes no site flags and mu2ejobsub defaults `--site none` →
> jobsub_lite onsite usage model. Pass-through exists:
> `--jobsub-arg` (mu2egrid v8_03_02 bin/mu2ejobsub:40) or `--site=...`;
> jobs already use `--default-protocol root` (xrootd) so offsite-compatible
> in principle. OSG breadth = queue-wait cut AND ceiling lift; risk = WAN
> xrootd flakes (we see PostEndJob xrootd errors even onsite at high
> concurrency). A/B one elebeam cluster offsite first.
> (c) **FUSE mubeam+mustops_ce into ONE grid job** (two `mu2e` processes
> back-to-back in a wrapper; CE resamples the job's own local TargetStops):
> statistically identical to the concat-drop per-file-slice plan, removes an
> entire queue cycle (~111 min stage + gap). With elebeam presubmit overlap,
> eval → max(fused sob job, elebeam) + harvest ≈ ~2h vs 5.4h. Cost: breaks
> mu2ejobdef's one-fcl-per-jobdef convention (custom wrapper, multi-day).
> (d) **σ_flash MEASURED (2026-07-09, ff09R00_00, 188 files, method
> bit-identical to harvest — total reproduces leaderboard flash_edep
> 1.04131e-06 exactly):** per-job rel spread 25.2% (≈5× Poisson on ~450
> flash events/file — broad but benign tail: top job 1.2% of total edep,
> max/median 2.3×) → **σ_flash = 1.84% @ N=188-200, 2.52% @ N=100
> (default), 3.57% @ N=50**; split-half realization median 2.5% confirms.
> **CAVEAT (2026-07-10 late, NC02 finding): that 2.5% is WITHIN-run only.**
> NC02 replayed the champion geometry (µm-identical, identical elebeam FCL,
> same 92 subruns compared per-file) and measured flash **+15% systematic**
> (median per-subrun ratio +11%, no outlier files, missing-8-subrun effect
> only ~1%) ≈ 3.3σ by within-run stats. µm geometry shifts chaos-decorrelate
> the showers (common subruns differ event-by-event, even in filter-passing
> counts), so replays are independent samples — and TWO independent runs
> disagreeing by 15% means an unmodeled RUN-LEVEL flash variance ~5-10%.
> Consequences: (a) cross-config flash differences <~15% are NOT decisive
> at 100 jobs; (b) the ff11R00_07 champion domination (−4.8% flash margin)
> is UNCONFIRMED — 400-job re-eval running; (c) elebeam=100 remains fine
> for BO exploration (GP absorbs noise) but CHAMPION calls need ≥400 jobs
> or replica averaging. Mechanism unknown — candidates: heavy-tail
> undersampling beyond the measured per-job spread, or a real run-level
> common mode (worker mix / EleBeamCat read pattern).
> **(a)+(3) IMPLEMENTED 2026-07-10:** memory right-size — foilsflash
> override now 2000 MB (was 2500; matches the 2 GB/core slot; watch first
> round for OOM-holds). elebeam OVERLAP — `PRESUBMIT_AFTER` seam in
> graph/config.py ({"mubeam": ["elebeam_flash"]} for foilsflash),
> `pio.presubmit_stage` (submit-only, idempotent), hooked inside
> make_stage_node AFTER run_stage succeeds — elebeam submits the moment
> mubeam lands, hides behind mustops_ce; per-child stagger comes free from
> the mubeam completion spread (no round-start flood, the ff05 lesson).
> Best-effort: presubmit failure degrades to the sequential path. 93/93
> tests; all 9 modes build; only foilsflash has a presubmit map.
> Expected eval wall: ~5.4h → ~3h (concat drop + overlap), at ~half the
> grid footprint (elebeam=100 + 2 GB slots). Validate on the next round.
> Vs the flash dynamic range across designs (~70%: 6.3e-7→1.08e-6) even
> 2.5% is negligible → the ELEBEAM_NJOBS=200 env override (inherited from
> ff08's stats run into ff09/ff10 launches) DOUBLE-SPENDS the dominant
> grid cost for nothing. **ADOPTED as standard (user decision 2026-07-09):
> future campaigns run at the default 100 — do NOT set
> AUTORESEARCH_ELEBEAM_NJOBS** → halves elebeam grid-hours (85% of
> total) ≈ 43% total capacity saving per eval. Extraction recipe: per-file
> gallery loop (scratch extract_one.py pattern), 188 files probed+extracted
> in 81 s wall — flash dts files are TINY (only filter-passing events are
> written: ~402-522 events/file, not 110k).
> (e) **DEAD END — poll cadence:** poll ticks are already 120 s with
> queue+settled checks per tick (pipeline.py:738); the ~25 min/eval
> inter-stage gaps are SUBMIT-side (mu2ejobdef build + RCDS publish +
> submit-lock serialization + list-outputs), which the round-shared-tarball
> lever already targets. Tightening poll sleep buys nothing.
> **Throughput analysis (2026-07-08): the eval loop is OVERHEAD-bound, not
> physics-bound.** Per-eval wall ~4.5-5 h but stage payloads total only ~1.5 h
> (each stage already at the ~30-min sweet spot: mubeam 200k×9.1 ms,
> mustops_ce 75k×24.1 ms, elebeam 110k×16.6 ms vs ~44 s setup); the other
> ~3 h = queue wait + stragglers (quorum 0.9 already cuts) + per-child
> cold-start (677 MB tarball rebuild, 15-20 min) + submit-lock ramp
> (40-80 min @q=20). Consequences: sim speedups cap out ~15% (minRangeCut
> −6% is the only safe knob); MORE events is backwards (σ_sob 0.09% is
> overkill; tighter posteriors flat-line acquisition sooner); MORE jobs/eval
> is ceiling-bound (~1,250 concurrent, q=20 already pins it at 1,193).
> **Ranked levers**: (1) round-shared Code tarball — QUANTIFIED 2026-07-10
> from recovery-v2 submits (9-19 min each, 7-12 min = tarball ops: 677 MB
> base unpack + rebzip2 per stage per child; only the ~50 KB geom differs):
> static-tarball + geom-sidecar (ship geom via jobsub -f; needs worker CWD
> on MU2E_SEARCH_PATH, one smoke to verify) saves ~15-25 min/eval critical
> path + collapses the q=10 ramp 40-90→~15 min + retires RCDS re-publish
> (OSError-122 face) and the /exp 2 TB Code.tar.bz2 churn (data-quota
> incident); intermediate = per-child build-once-reuse-3-stages (~half the
> gain, zero worker-side risk). intermediate IMPLEMENTED 2026-07-10 (validating live on NC02's mustops/elebeam submits): ~10-15
> lines in write_code_tarball (cache at ROOT/Code.<base>.tar.bz2, guard =
> exists && newer-than-GEOM_FILE; child submits are serial so no race;
> safe to apply mid-flight — first build identical, later calls hit cache).
> Full variant = ~25-30 lines (write_code_tarball returns static base;
> geom ships via jobsub `-f` through mu2ejobsub --jobsub-arg; base's
> setup_post.sh — rebuilt ONCE offline — prepends the worker input dir to
> MU2E_SEARCH_PATH); UNKNOWN needing one smoke: where mu2egrid's wrapper
> exposes -f files vs the search path. **Full variant KILLED 2026-07-10:**
> mu2ejobdef COPIES the code tarball INTO each per-config cnf (its help,
> ~line 95) so RCDS re-uploads ~677 MB/config no matter how static our
> tarball is (worker CWD IS already on MU2E_SEARCH_PATH —
> mu2ejobsub.sh:~160 — so the geom-sidecar half is trivial but pointless
> alone). Escape routes: (a) `--setup` with a cvmfs-resident release =
> UPSTREAM the holeRadii-vector + helical-plug patches into
> Offline/Production (the true deep fix: no tarball, no RCDS, submits
> ~1-2 min); (b) mu2eprodsys-style `dropbox://` code path (different
> toolchain, days). Variant 1 (per-config cache, live) captured all the
> locally-capturable cost; (2) fewer-BIGGER jobs (elebeam 200×110k→100×220k, same events/σ)
> → q≈40 fits the ceiling → ~2× evals/day at +15% per-eval wall; (3)
> elebeam overlap done right (submit after mubeam lands, per-child stagger —
> ff05's failure was the up-front FLOOD, not the concept; ~25%/eval); (4)
> async rolling BO (kill the barrier's slowest-of-q tail, +30-50%; X_pending
> fantasies already support pending-aware picks; natural after ChildTracker)
> — **IMPLEMENTED 2026-07-12** as `closed_loop --rolling` (c47cd90) and
> **VALIDATED 2026-07-14** (foilsflash16: 10/10 rows, rolling_done clean;
> 1.21 evals/h @q=5 ≈ 10–25% over barrier at mini scale — full +30-50%
> needs many-wave production scale; see [[closed-loop-runner]]);
> (5) early-stop dominated evals (skip the flash stage, 40% of wall, when
> sob stages show deep domination).
> **Quantified stack (2026-07-08, vs measured ~60 evals/day @q=20)**:
> #1+#2 (shared tarball + fewer-bigger jobs, q=40) ≈ 2×; +#3 (elebeam
> overlap) ≈ 2.2-2.5× — SYNERGY: the overlap fully hides #2's bigger 60-min
> flash payload behind the ~2.7 h sob chain, so per-eval wall DROPS to
> ~3-3.5 h while width doubles; +#4 (rolling) ≈ 3× (round tails idle
> ~25-30% of capacity-time). #2 without #1 loses half its gain to a ~2.5 h
> 40-child ramp. CAVEAT: q=40 queue behavior is extrapolated beyond the
> measured q=20 regime — run a 1-round q=40 pilot with reshaped jobs before
> betting a campaign on it. Evals/day converts ~linearly to science only
> pre-saturation (the stack compresses the discovery phase, not the plateau).
> **Beyond the 3× (same-resources/same-eval/same-algorithm ceiling)**: (a) the
> ~1,250 ceiling is our default fair-share, never a negotiated allocation —
> our jobs (30-60 min, 2.5 GB, ~600 KB out) are ideal OSG-opportunistic
> citizens; 2-3× more slots plausible by ASKING; (b) eval-cost shrink ~2×:
> sob stages carry ~10× surplus stats (cut 4× → −25% grid-hours) +
> multi-fidelity screening (1/5-stats screen → promote; textbook-favorable
> here since cheap fidelity = same sim fewer events, corr≈1) + early-stop;
> (c) demand side: cross-line transfer (the transplant = 1 eval worth ~200).
> Stacked plausible ≈ 10× evals/day-equivalent, effort/uncertainty rising
> per factor; take the engineering 3× for the next line, reach for (a)/(b)
> only if the next line is expensive per eval.

## Summary
The bo-foils GP picker has plateaued near `sob ≈ 3.89` with last-5-rounds `Δsob < 0.04` per round — comparable to the per-eval measurement noise. This page records the per-point event budget, the measured σ on each objective channel, and what's worth (and not worth) spending CPU on to sharpen the front. Used to decide whether to raise `events_per_job` vs. widen the search space.

## Breaking the flat-top tie: replicas, NOT denser sampling (2026-06-22)
To decide whether one flat-top champion is *genuinely* above another (sob spread
~0.3% vs σ(sob)≈0.4%), the lever is **reducing σ on the SAME geometry**, two
equivalent ways:
- **More events/config** (×N stats) → σ ∝ 1/√N. `events_per_job` is hardcoded in
  `pipeline.STAGES` and mid-flight edits are hazardous ([[events-per-job-mid-flight-edit]]),
  so this needs an env-override, not an in-place edit.
- **Replicas** (simpler, ZERO code): re-run the SAME config N times via
  `graph.run --x-point <csv> --config-name <name>` (forces exact geometry, skips
  the BO ask — `graph/nodes.py:60-83`), then average → same √N reduction. 8
  replicas ≈ 8× events. Reuses existing machinery.
- **GOTCHA — "more jobs in the high-sob region" does NOT break the tie.** Densely
  sampling the champion box adds many *different* nearby geometries, each still at
  σ≈0.4%; averaging across *distinct* points doesn't sharpen any single one. A is
  3.92 and B is 3.90 both read "3.91±0.015" no matter how many neighbors you add.
  Denser sampling answers "where is the best region", replicas/high-stats answer
  "is A truly > B".

## Key facts

- **Per-BO-point event budget (`pipeline.py`):**
  - `mubeam` (Run1A signal denom): 200 jobs × 5,000 events = **1.0e6 events**
  - `run1b_mubeam` (calo numerator): 200 jobs × 5,000 events = **1.0e6 events**
  - `mustops_ce` (sob numerator, EdepAna ce_seen): 200 jobs × 2,500 events = **5.0e5 events**
  - Total G4 events per BO point: **≈2.5e6**. Stamped per-submit at `pipeline.py:191` so mid-flight `STAGES` edits don't bias historical leaderboard rows (see [[events-per-job-mid-flight-edit]]).

- **Prescale overrides — both objectives keep FULL stats (nPrescale=1):** the
  resampler stages carry a `RandomPrescaleFilter` whose production default throws
  away 999/1000 events (a data-volume convenience). Our templates override to
  `nPrescale=1` so the BO objective sees every event:
  - `mubeam`: `TargetStopPrescaleFilter.nPrescale: 1` (prod default
    `MuminusTargetStopPrescale=1000`, pileup/prolog.fcl:366) — keeps ALL μ⁻ target
    stops feeding the S/√B numerator. Set at `pipeline_templates/mubeam/template.fcl:19`.
  - `elebeam_flash` ([[bo-foilsflash]]): `EarlyPrescaleFilter.nPrescale: 1` (prod
    default `EarlyEleBeamFlashPrescale=1000`) — keeps all early-flash events for
    the `flash_edep` objective. Without it, ~250 events → ~32× (√1000) worse noise.
  - The prescale is a RANDOM subsample → does NOT bias the per-event mean (harvest
    divides by survivors), only inflates variance by √N. `g4run` (dominant CPU)
    runs for every event regardless; removing the prescale only adds downstream
    StepSim CPU + output volume.

- **sob noise DECOMPOSITION — what mubeam stats actually buy (foilsf26R00_07, 2026-06-27):**
  - mubeam stopping fraction = **143,224 μ⁻ stops / 960,000 beam = ~15%** (mubeam is
    EFFICIENT — not mostly fly-through; ~1e6 beam → ~1.4e5 stops). `pipeline.py:1157`
    `stopping_factor = muminus_stops/mubeam_sim_total` enters sob directly.
  - **Poisson σ on the stop count = 0.26% at full mubeam** (200×5000), a real chunk
    of the measured σ(sob)=0.4%. At 40 jobs (1/5) it more than doubles to **0.59%**.
  - `mustops_ce` resamples **480,000 CE primaries from the 143k stop pool → only
    ~3.4× reuse per stop** (mild correlation; pool is large vs the draws). At 40
    mubeam jobs the pool shrinks to ~28k → ~17× reuse (more CE correlation).
  - **Consequence:** trimming mubeam DOES cost sob precision (stopping-factor Poisson
    + CE-reuse correlation both grow) — so keep mubeam at 200 for production. But for
    a SMOKE (sob is throwaway, and the flash objective is independent of mubeam — see
    [[bo-foilsflash]]) mubeam can be slashed to ~40 jobs for free.

- **GRID EFFICIENCY: events_per_job is too SMALL — payload ≈ setup (measured 2026-06-27).**
  Per-job art payload is only **~45 s** (mubeam 5000 ev: `0:45.73elapsed`, 1.1 GB;
  elebeam_flash 2500 ev: `0:41.59elapsed`, 1.3 GB) — vs **~44 s of `muse`/Offline
  setup ALONE** (job-log markers "before the payload" → "After Offline setup"),
  before counting container start, Code.tar.bz2 RCDS download, xrootd input fetch,
  stage-out (another ~1–3 min). So real grid efficiency is only **~15–30%** — most
  of each slot is overhead. **The "small jobs → more parallelism" rationale (e.g.
  mustops_ce 5000→2500) does NOT pay off:** stage WALL is queue-dominated (~12 min
  per stage) vs 45 s compute, so tiny jobs buy no wall benefit while wasting the
  slot and flooding the scheduler. **Fix = raise events_per_job ~5× + cut njobs ~5×
  (constant total events → identical statistics):** e.g. mubeam 40×25000,
  mustops_ce 40×12500, elebeam_flash 60×12500 → ~3–4 min payload, ~80% efficiency,
  5× fewer jobs, same σ. Memory-safe (5× events stays <3 GB request). Pending
  operator decision to apply (foilsflash01 launched with the old small-job config).

- **"Make the eval faster?" — per-eval wall is ~55–60% FIXED grid overhead; more parallel jobs does NOT help (2026-07-02).**
  Fast-config payloads are all ~30 min/job (mubeam 200k×9.1ms, mustops_ce 75k×24.1ms, elebeam 110k×16.6ms
  ≈ 1820 s each) but the measured stage WALLS are ~75–90 min → **~45–60 min/stage is overhead** = queue wait +
  muse setup (~44 s) + the **677 MB `Code.tar.bz2` RCDS download per job** + stage-out. So compute is the
  minority. **"More parallel jobs" is the WRONG lever and was disproven live:** the ff05 elebeam
  parallelization flooded the grid with 2000 concurrent jobs → 4–5× SLOWER ([[closed-loop-runner]]).
  (CAVEAT 2026-07-02: that slowdown was OBSERVED but the CAUSE is UNVERIFIED — fairshare throttling and/or
  dCache/RCDS I/O contention, not confirmed raw compute-slot starvation; FermiGrid is huge but we get a
  fairshare slice. Diagnose next burst via `jobsub_q` idle-vs-running.)
  **FIRST MEASUREMENT (foilsflash06 q=20 mubeam phase, 2026-07-02): real headroom, NOT slot-throttled at ≤120.**
  `jobsub_q` idle-vs-running through the mubeam burst: running climbed 15→45→90→120 while idle stayed ~0–15
  (just the newest just-submitted batch; at one sample ALL 90 were running, 0 idle). So at ≤~120 concurrent
  the grid gives us slots freely — the earlier "fixed ceiling" framing was WRONG at this scale. mubeam demand
  caps at 300 jobs (20×15) so it can't reveal the true ceiling; the definitive test is the **elebeam phase
  (~4,000-job demand)**. **RESOLVED (elebeam ramp, same campaign): real concurrent ceiling ≈ 1,100–1,250
  running jobs.** Running climbed 358→720→903→1049→**1249** then PLATEAUED while `idle` grew to ~700–800 at
  ~2,000 demand. So: **below ~1,250 concurrent → zero queue (idle~0, runs immediately); above → excess sits
  idle and drains as slots free.** The ceiling is ~1,250 — NOT ~120 (mubeam phase just never demanded enough)
  and NOT unlimited. Reframes ff05: it dumped 2,000 elebeam jobs ALL AT ONCE → ~750 over the ceiling + likely
  stage-out I/O contention → 5× slow; ff06's staggered-serial submits keep `running` pinned ~1,250 with a
  manageable backlog (NOT 5×) — why staggered beats the all-at-once flood.
  **INDEPENDENTLY CONFIRMED (foilsflash07 R1, 2026-07-04): 1193 running / 428 idle** at ~1,600 demand —
  running pins ~1,200 (≈ the ff06 ~1,250 measurement), excess queues. Ceiling is real and reproducible ~1,200–1,250. Also observed: at q=20 the **submit-lock serializes mubeam submits ~1 child per few min**
  (each builds+RCDS-publishes the 677 MB cnf tarball) → ~40–80 min just to submit 20 children — a q-tax
  independent of slots.
  **Memory request is a slot-matching lever — APPLIED 3500→2500 MB (2026-07-02, `pipeline.py:270-274`).**
  foilsflash mubeam/mustops_ce/elebeam requested 3500 MB/job (precautionary for the 200k-events fast config)
  but measured **VmPeak is only ~1.1–1.3 GB** — a ~3× over-request, so each job only matched a slot with
  ≥3.5 GB free. **Cut to 2500 MB** (≥1.5× peak, safe HOLD margin) so jobs match MORE slots → more concurrency,
  at NO metric cost (memory affects slot-matching only). Takes effect at the next submit (mid-flight-safe:
  each child re-imports pipeline.py per stage submit; ff06's later stages picked it up). A cheaper concurrency
  lever than raising q; trim further only if the elebeam ramp still shows `running` plateauing. Speedup levers,
  ranked: (1) **trim the over-sampled sob stages** — mubeam 3.0M + mustops_ce 1.125M events give σ_sob
  ~0.24% vs a 0.4% budget (2–3× over-sampled); halving `events_per_job` (KEEP 15 jobs) saves ~30 min/eval,
  σ_sob→~0.35%, zero added contention; (2) drop elebeam 200→100 jobs (σ_flash 2%→3%, less stage-out
  contention); (3) slim the 677 MB tarball (build-level, hard). **Floor ≈ 3.5–4 h/eval** — fixed overhead
  dominates. Do NOT split into more/smaller jobs (that's the "payload ≈ setup → 15–30% efficiency" trap below).
  - **Raising `q` (more BO POINTS in parallel) DOES raise throughput — MEASURED ~+40% at q=20 (foilsflash06, 2026-07-03).**
    q=20×2 delivered **39 evals in 15.6 h (~2.5 evals/h)** vs ff04 q=10×3's 28 evals in ~15-17 h (~1.75/h).
    Higher q hits the ~1,250 ceiling (each round's elebeam ~2,000 demand drains in ~1.6 waves → round is LONGER)
    but you get 2× evals/round, and the round lengthens only SUB-linearly → **net throughput win**. So my earlier
    "raising q does NOT help" was WRONG — it conflated q with the ff05 all-at-once FLOOD (which broke on
    simultaneity, not q itself). Staggered-serial q scales until elebeam demand VASTLY exceeds ~1,250.
    (Caveat: confounded by the concurrent 2500 MB trim + grid-day variance — direction solid, exact % loose.)
    Older framing (kept for the mechanism): each eval = ~231 grid jobs (elebeam 200 dominates);
    **throughput ≈ our-concurrency (~1,250) ÷ jobs-per-eval** — so cutting jobs/eval (elebeam 200→100) is the
    OTHER lever and stacks with higher q. Secondary q-scaling limits (all
    already seen at q=10): shared SqliteSaver checkpoint contention (corruption risk,
    [[closed-loop-sqlite-checkpoint-transient-corruption]]), leaderboard-append contention at the `evaluate`
    node (R00_02 died on a 120 s timeout), submit-lock serialization, and loss of BO adaptivity (qNEHVI commits
    all q points before any results). **The real lever for more points-in-parallel = fewer jobs PER eval**
    (elebeam 200→100) so more evals fit the fixed slot budget — then q can rise safely. More grid fairshare is
    the only other route and isn't ours to grant.
- **foilsflash `flash_edep` noise channel (2026-06-29) — per-eval ≈3.5–4%, floors slowly (√N), NOT improved by ff03:**
  - Per-campaign cross-point CoV: smoke (n=3, ~875 flash events/eval) **12.1%**; foilsflash02 (n=15, ~50k events) **4.1%**; foilsflash03 (n=30, ~37k events) **3.4%**. Pooled 48-point CoV = **5.07%** — but that figure is **dragged up by the 3 low-stats smoke rows**; the real per-eval precision at production stats is **3.4–4.1%**, not 5%. (Don't quote 5% as "the measurement noise" — it's smoke-contaminated.)
  - **Two distinct "stats" — keep separate.** foilsflash03's "increase stats on slide 3" raised the **number of points** (n 18→48), which sharpens cloud coverage + correlation estimates (corr(flash,f_dn) noisy +0.62 @n=15 → +0.05 @n=48) but does **NOTHING** to shrink a single dot's error bar. ff03 actually ran *fewer* flash events/eval than ff02 (37k vs 50k). Per-dot precision is set by **events-per-eval**, which was not increased.
  - **Per-eval flash precision floors at ~3–4% because the per-event tracker flash deposit is HEAVY-TAILED** (a few flash events dump most of the StrawGasStep energy). Precision of the mean = CV_event/√N; with √N≈190–220 and mean-CoV~4%, per-event CV≈**800%**. So 4%→2% needs **4× the flash events** — only √N gains.
  - **Cross-point CoV is NOT pure measurement noise** — it also carries the geometry spread of each campaign's sampled region (ff03 has fewer events yet lower CoV than ff02 → geometry-region effect, not Poisson). Removing the linear geom trend (R²(flash~6 knobs)=0.17) leaves per-eval measurement noise ≈3.5–4%.
  - **Irrelevant to the [[bo-foilsflash]] null:** geometry signal (max/min 1.30, R²=0.17) is far below what even a zero-noise measurement would need to make foils a flash lever; sharper per-eval stats shrink the dots but leave the GP-mean cloud flat. See [[gp-cloud-rendering]] for the dots-vs-cloud-σ story.

- **flash-per-POT (the CORRECTED objective) per-point precision ≈ 2–4% at 100 elebeam jobs (2026-07-01).**
  Measured from two independent runs of the SAME geometry (100-job original vs 400-job hi):
  solid 8.33e-7 vs 8.22e-7 (**1.4%**), holed 6.70e-7 vs 6.45e-7 (**3.9%**) → σ(flash-per-POT) ≈
  **2–4% @100 jobs**, ~**1.5–2% @400 jobs** (σ ∝ 1/√jobs). Distinct from the per-event MEAN noise
  (~5%) and from the flash-event-COUNT Poisson alone (0.6% @100/0.3% @400) — the total carries the
  heavy-tailed per-event edep variance on top of the count. **Implication for a re-run:** the flash
  lever is 2.5× (SNR~50, R²=0.89), so **100 jobs already MAPS the landscape**; more flash jobs only
  buy FINE discrimination near the (already low-flash) default — resolving a ~5% Pareto gain needs
  σ~1.5% → ~4× jobs (`AUTORESEARCH_ELEBEAM_NJOBS`). Keep sob stages at the fast 15-job config
  (σ_sob 0.4% ample). See [[bo-foilsflash]].
- **foilsflash `sob` channel is ~10× TIGHTER than flash — σ(sob)≈0.4%, counting floor ~0.24% (2026-06-29):**
  - Measured ingredients from 46 foilsflash summaries: `ce_seen` median **532k** (1/√N=0.14%), `muminus_stops` median **261k** (1/√N=0.20%) → quadrature **≈0.24%**; conservative end-to-end value matches the documented **0.4%** (helical001 A/B). Absolute ≈ ±0.012 at sob=3.
  - foilsflash's `muminus_stops` (261k) is **LARGER** than standard-foils full-stats (~143k) — the "fast" config runs FEWER but LARGER jobs (per-eval beam events went up, wall-clock down), so the sob channel is well-fed despite the small job count. ("Fast" = fewer jobs, not fewer events.)
  - **Why sob ~10× more precise than flash (0.4% vs ~4%):** (1) far more events (ce_seen 532k vs flash 37k, √14≈3.7×); (2) CE significance is NOT heavy-tailed like the flash deposit (per-event CV~800%). σ(sob)=0.4% is ~200× below the sob RANGE (1.50→3.77) → invisible on the x-axis → that axis shows pure geometry signal (the cloud's sob GP rails its noise at the floor 1e-5, interpolates to 0.001%), unlike the flat flash axis.

- **Measured noise channels:**
  - **σ(sob) ≈ 0.4% relative** (≈ 0.015 absolute at sob=3.8). Source: helical001 half-vs-half A/B run on `mustops_ce`, 97 vs 97 jobs at full stats agreed to 0.4%. Already 10× below the round-to-round improvement signal; **not the binding noise**.
  - **σ(calo) ≈ 8% relative**. Recorded in [[batch-bo]] as the Run1B-mubeam sampling floor. **This is the binding noise channel** — the picker's calo-axis discrimination is limited by it.
  - Top-3 spread (proxy): sob 3.89/3.88/3.87 (Δ ≈ 0.3%); calo 2.03e-5/2.16e-5/2.05e-5 (Δ ≈ 6%) — consistent with the above.

- **prodtarget6d noise channel is DIFFERENT — the 0.4% sob figure does NOT carry over (2026-06-17 review):**
  - `mu_per_POT = total_mu / total_pot` where the numerator is a raw **muon count** at VD sid=8 (`pipeline.py:921`) and the denominator is the exact generated POT. All noise lives in the ~1000-count numerator → **σ ≈ √N/POT ≈ 3% relative** (champion pt6d07R01_07: 1122 counts → 7.4e-5 abs / 2.99% rel). This is **~8× noisier** than the CE `sob` channel; do not reuse σ(sob)=0.4% for prodtarget6d picks.
  - Per-config budget for `pot_only` = **100 jobs × 5,000 = 5.0e5 POT nominal** (`graph/config.py:99`, `pipeline.py:210`); champion lost 10 jobs → 450k POT, denominator derived from **landed** files so the ratio stays unbiased ([[harvest-denominator-bug]] absent here).
  - **Consequence for ranking:** the champion is +6.6 Poisson-σ above the 2.0e-3 bulk (real high-t-corner signal), but its lead over runner-up pt6d07R00_03 (2.402e-3) is only **1.2 Poisson-σ** → the +4% gap is **statistically unresolved** at 500k POT. A confirmation re-run is needed before trusting the #1 ranking. See [[gp-cloud-rendering]] (the forward-LOO z there is GP-prediction surprise, a *different* σ from this measurement-Poisson σ — do not conflate; champion is a modest ~2–3σ GP surprise but +6.6 measurement-σ above bulk).
  - **CONFIRMATION EVIDENCE (pt6d18, 2026-06-29):** a fresh 21-eval high-stats campaign (q=10×3, pot_only 800×2500=2M POT/eval, qNEHVI warm-started on all 359 prior rows) topped out at **mu/POT=2.380e-3** (pt6d18R00_06) and never approached 2.49e-3 — it converged in the 2.32-2.38e-3 band. So an independent campaign at 4× the POT/eval did NOT reproduce pt6d07's 2.49e-3 → strong support that **pt6d07R01_07's 2.49e-3 was a high-side Poisson fluctuation, not a real peak.** Treat the realistic prodtarget6d optimum as ~2.38e-3, not 2.49e-3.

- **TWO SEPARATE GPs — cloud viz ≠ proposal engine (don't conflate; 2026-07-03).** The density cloud
  (`gp_predict_*_cloud.py`, sklearn `GaussianProcessRegressor`, N-sample Sobol pushforward) is
  VISUALIZATION ONLY — its `N`/`n_restarts` affect the picture, NOT what gets proposed. Grid proposals
  come from a DIFFERENT engine: `botorch_predict.py` qLogNEHVI. Raising cloud "stats" changes zero proposals.
- **Proposal acquisition is already well-provisioned — NOT a tuning lever (`botorch_predict.py`, 2026-07-03):**
  qLogNEHVI uses `SobolQMCNormalSampler(sample_shape=128)` (HV Monte-Carlo integral) + `optimize_acqf(
  num_restarts=16, raw_samples=512)` (lines ~288/302, ~328/341) — BoTorch's recommended defaults. Cranking
  them higher gives negligible proposal improvement; the acquisition optimization is not the bottleneck.
  **At convergence the binding limit is MEASUREMENT noise (σ_flash~2%, σ_sob~0.4%), not surrogate fidelity** —
  a higher-fidelity map can't propose better points on a genuinely flat front, it just fits the noise-scatter
  more precisely. To resolve which converged point is best, spend stats on the MEASUREMENT (replicas / more
  elebeam jobs per point), not on the map — same principle as the flat-top-tie note above.
- **GP noise modeling (`botorch_predict.py:_fit_gp`, lines 137–153):** `SingleTaskGP` with `Standardize` outcome + `Normalize` input. **No explicit `noise_constraint` / `WhiteKernel`**; default `GaussianLikelihood` with a learned homoscedastic noise term + default `GammaPrior(1.1, 0.05)` on noise variance. By contrast, the sklearn-based cloud renderer caps WhiteKernel at `noise_level_bounds=(1e-5, 3e-2)` ([[gp-cloud-rendering]]).
- **Independent flash-noise cross-check via LOO z-calibration (2026-07-13):** fitting the GP with FIXED assumed noise (train_Yvar, `tools/gp_loo_benchmark.py` yvar variant) and reading back the LOO z_std gives **effective archive flash noise ≈ 4.5%** (z_std 0.75 under an assumed 6%) → run-level systematic ≈ √(4.5²−2.5²) ≈ **3.7%** — confirms the NC02 run-level estimate at its LOW end (5–10% was the ceiling guess). sob readback: effective σ ≈ 0.5% (assumed 0.4%). Details: [[ml-stack-review-2026-07]].
- **GP noise audit — LOGGED as of 2026-07-13 (commit 163bb2e) + FIRST READING:** `_fit_gp` now prints fitted σ per output, un-Standardize'd to raw units. foilsflash n=274: **σ(sob)=7.0e-3 abs ≈ 0.2% rel** (matches the 0.24% counting floor — GP correctly sees sob as near-noiseless); **σ(log10 flash)=1.31e-2 ≈ 3.0% rel on flash** — squarely the measured *within-run* band (2–4% @100j) but EXCLUDING the ~5–10% run-level systematic (NC02) → **the GP currently treats run-level flash offsets as geometry signal**. Quantifies the train_Yvar case ([[ml-stack-review-2026-07]] gap #1); `tools/gp_loo_benchmark.py` (LOO NLL/z-calibration, variants base/warp/yvar, botorch 0.10-vs-new compat) is the offline judge.

- **Stats-bump decision matrix (verdict 2026-06-07 from agentic research):**
  - **Do NOT 2× globally** — ~10 grid-hours/round extra for ~no win on the sob channel (σ already <round-to-round signal).
  - **Sharpen calo only**: 2× `run1b_mubeam` (5000 → 10000 events/job at `pipeline.py:132`) cuts σ(calo) 8% → 5.7% (√2). Cost: +30–40 min wall/point. The only stage whose noise actually limits Pareto-front HV.
  - **Don't touch mustops_ce** — σ(sob)=0.4% already saturated; raising stats can't beat the genuine plateau.
  - **Better than stats: widen search**. Promoting `n_up`/`n_down` from pinned 6/6 to BO knobs is cheaper per-eval than 2× stats AND addresses the actual ceiling.
  - **Cheap first step: replicate champion** (foilsf03R01_09) at current stats + 2× Run1B stats — ~4 grid-hours, gives *measured* σ at the saturation plateau before committing.

## Cross-links
- Related: [[bo-foils]], [[batch-bo]], [[scalarized-objective]], [[events-per-job-mid-flight-edit]], [[harvest-denominator-bug]], [[gp-cloud-rendering]], [[fast-sim-options-for-bo]], [[pareto-sob-picker]], [[qlnei-sob-only-picker]], [[ml-stack-review-2026-07]]
- Source files: `pipeline.py:116-172` (STAGES dict), `pipeline.py:191` (stamp-at-submit), `pipeline.py:132` (Run1B events_per_job), `botorch_predict.py:137-153` (_fit_gp), `graph/config.py:28-32` (STAGE_TARGETS)

## Open questions / TODO
- ~~Log `model.likelihood.noise` after fit~~ DONE 2026-07-13 (see noise-audit Key fact).
- Run the replicate-champion audit (4 grid-hours) to convert the 0.4%/8% derived bounds into *measured* σ at the saturation plateau.
