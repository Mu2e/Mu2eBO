---
type: incident
title: G4Cache Cache001 fatal at exit in Mu2eG4MT jobs
description: MT jobs abort 1-of-2 at __run_exit_handlers — exit-time static destruction of per-thread G4HadronicInteractionRegistry runs ParticleHP G4Cache dtors on the main art thread, whose thread-local cache container is too short; fixed by a Cache001-suppressing G4VExceptionHandler installed at endJob
status: resolved
status_note: handler fix implemented 2026-08-26, validated same day (10/10 MT runs clean)
timestamp: '2026-08-26'
---

# G4Cache Cache001 fatal at exit in Mu2eG4MT jobs

## Summary
Mu2eG4MT jobs (Geant4 ≥ ~11.2; here spack geant4-11.3.2 under Run1Bak/p094)
abort stochastically (~1-of-2 at 100 events / 2 schedules) AFTER the art
output file closes, with `G4Exception : Cache001` from
`G4CacheReference<V>::Destroy` and "*** ExceptionHandler is not defined ***".
Data on disk are complete and correct — only the exit status lies, which is
what makes it fatal for grid production (jobs marked failed on good output).
Root-caused by gdb backtrace 2026-08-26; fixed by a targeted
`G4VExceptionHandler` installed on the main thread at `endJob`.

## Key facts
- gdb backtrace (repro `mu2e -c ceSimReco + Mu2eG4MT, 2×2`, hit on attempt 2):
  crash is on **Thread 1 (main art thread) inside `__run_exit_handlers`**:
  `~G4ThreadLocalSingleton<G4HadronicInteractionRegistry>` → `Clean()` →
  `~G4ParticleHPInelastic` → `~G4ParticleHPNInelasticFS` →
  `~G4ParticleHPAngular` → `~G4Cache<toBeCached>` → `Destroy(id=460)` →
  Cache001 (main-thread container size 459). NOT in module teardown, NOT in
  worker/master run-manager destruction.
- Mechanism: `G4Cache<V>::instancesctr` is a **per-template-type** counter;
  the backing store is a **thread-local** vector grown lazily per thread
  (`G4CacheDetails.hh`). HP model instances live in per-thread
  `G4HadronicInteractionRegistry` singletons which are destroyed only by a
  `G4ThreadLocalSingleton` static destructor at process exit — on the main
  thread. Caches created on G4 worker/master threads then have ids beyond
  the main thread's container size → FatalException.
- Why native G4 MT never shows it (Genser observation 2025-08): there the
  main thread IS the G4 master, its container fully grown. It bites
  frameworks that run all G4 on secondary threads — art specifically.
- Stochasticity: with `num_schedules: 2` the main thread sometimes executes
  one schedule's G4 work (TBB can run tasks on the caller); those runs have
  a grown main-thread container and exit cleanly. ~50% observed.
- `G4CacheReference<V>::Destroy` has a clean handled-exception path: when a
  `G4VExceptionHandler` consumes the exception it just `return;`s without
  touching the container — exactly right at exit. Value-spec deletes only
  non-null slots; pointer-spec never deletes (client-owned). So suppression
  is safe, not a leak-hiding hack.
- Fix: `CacheTeardownHandler` (anonymous namespace, `Mu2eG4MT_module.cc`) —
  `Notify()` returns false (continue) for exceptionCode=="Cache001", mimics
  default abort for other fatal severities; installed by
  `installCacheTeardownHandler()` as last line of `Mu2eG4MT::endJob` (main
  thread), deliberately leaked so it survives into `exit()`.
  `G4VExceptionHandler` base ctor self-registers with the thread-local
  `G4StateManager`.
- Dead ends (why not other fixes): pre-growing the main thread's containers
  via dummy `G4Cache<V>` instances fails because every HP `toBeCached` type
  is a **private** nested struct (unnameable); per-thread
  `registry->Clean()` in the endRun destroy tasks leaves the unmatched-thread
  gap (same reason worker RMs are deliberately leaked); Offline cannot patch
  `G4CacheDetails.hh` (header templates compiled into G4 libs).
- Email thread 2025-08 (Genser/Brown/Culbertson): same signature since
  ~G4 11.2 / envset p084; "safest not to use MT till fixed"; 3 days before
  Production PR#449 removed MT from all production fcls.
- Distinct from Offline#849 (MT irreproducibility, fixed by per-event
  reseed PR#1951) — the two are independent; this crash recurred with the
  reseed fix active.

## Cross-links
- Related: [g4-speed-knobs](/concepts/g4-speed-knobs.md)
- Source files: `Mu2eG4/src/Mu2eG4MT_module.cc` (handler + endJob install),
  `Mu2eG4/src/MTMasterThread.cc` (master RM teardown — exonerated),
  geant4 `source/global/management/include/G4CacheDetails.hh:170`
- Validation 2026-08-26 (100 ev, 2x2, reseed on, 10 MT + 2 ST): 12/12
  exit 0 + "Art has completed"; Cache001 fired in 4/10 MT runs — **2801
  suppressed occurrences each, ids 460–3260 contiguous** (the original
  abort-on-first hid 2800 more would-be fatals; type-enumeration fixes
  were doomed), all during art teardown (before the final art banner),
  none in the exit-handler phase. Output identity: suppressed-vs-clean MT
  pairs bit-identical (15/15 events, g4+digi hashes), ST pair identical —
  handler does not perturb physics. Handler made log-once (first
  occurrence + note, rest silent) for production log hygiene.
- Scale confirmation 2026-08-26: 10,000-event pair at 4 threads x 4
  schedules (100x events, 2x threads vs first validation): both runs exit 0,
  10000/10000 events processed, handler fired exactly once per run
  (log-once verified at scale), ~24 min wall each. Cache001 fix CONFIRMED
  at scale. (Same pair exposed a residual #849-family digi divergence at
  scale — separate issue, recorded in [g4-speed-knobs](/concepts/g4-speed-knobs.md).)
- Repro/validation: scratchpad `mtgdb/` (gdb loop), `mtval/` (10 MT + 2 ST);
  patch: `Offline_mtfix_partial/cache001-teardown-handler.patch`, lib:
  `Offline_mtfix_partial/build/al9-prof-e29-p094/Offline/lib/libmu2e_Mu2eG4_Mu2eG4MT_module.so`

## Upstream status (checked 2026-08-26)
- NOT fixed upstream: 11.4.0's `G4CacheDetails.hh` is byte-identical to
  11.3.2; the 11.5.0.beta rewrite (master, unique_ptr storage) tolerates
  only the empty-store case ("We DO NOT raise an exception" comment) and
  KEEPS the size-mismatch FatalException — our case still aborts there.
- Only tracker entry: Geant4 Bugzilla #2424 (GPS flavor, same ~50%
  intermittency, ASSIGNED, stale since 2021-10-29, no fix); also
  geant4-forum thread 6045 (unresolved Jan 2026).
- Mu2e compiles its own Geant4 via spack (`spackages/241207/spack/opt/...`,
  rlc's build — the gdb paths show /tmp/rlc/spack-stage), so a G4-level fix
  is deployable centrally: 3-line patch making the size-mismatch branch of
  `Destroy` a silent no-op (`Offline_mtfix_partial/g4cachedetails-teardown-tolerant.patch`,
  applies to 11.3.2 + 11.4.0); requires full geant4 rebuild (template code
  baked into libG4processes) + envset republish. The art-side handler
  produces the IDENTICAL post-state, so the 16-run validation covers the
  G4-level fix too.
- Upstreamed as **draft PR Mu2e/Offline#1952** (2026-08-26, branch
  `oksuzian:cache001-teardown-handler` off main, 65 insertions, PR body
  carries the spack recipe); independent of PR#1951 (reproducibility).

## Open questions / TODO
- File a fresh Geant4 Bugzilla report (reproducer + backtrace + patch);
  operator submits under own account.
