---
type: incident
title: sourced_env stderr swallowed — transient setup blips look like silent stage
  death
description: pipeline.py:278 sourced_env() swallows bash stderr; 3/10 foilsX06R00
  children died on transient `setup mu2egrid` rc=127 + missing CET_PLUGIN_PATH mfPlugin
  "cerr" with no captured cause
status: active
timestamp: '2026-07-17'
---

# sourced_env stderr swallowed — transient setup blips look like silent stage death

## SECOND CODE PATH FOUND + FIXED (2026-06-01): cmd_preflight
- The retry fix was applied to `pipeline.py:sourced_env` (submit/harvest)
  but **`cmd_preflight` has its own independent env-source** at
  `autoresearch_bo_michael.py:1039-1046` that had the SAME bug: `source
  {SETUPMU2E} >/dev/null 2>&1 && source {MUSING} >/dev/null 2>&1 && … &&
  mu2e -c surfacecheck.fcl -n 1`, no retry, stderr swallowed.
- **New failure shape — false-ambiguous:** when the cvmfs/spack flake hits
  here, `mu2e` never runs, the subprocess exits nonzero with EMPTY output,
  and `cmd_preflight`'s rc-map (`{0:pass,1:fail_managed,2:fail_init,
  3:ambiguous}` at `autoresearch_bo_michael.py:1140` / `:1115`) reads the
  causeless nonzero exit as **rc=3 ambiguous** — a real-but-rare G4 outcome.
  The preflight log is just the 16-byte template (`\n--- STDERR ---\n`).
- **Impact:** 2 of 3 foilsY02 round-0 children (`foilsY02R00_00/01`) burned
  all 3 graph-level preflight retries inside a single bad cvmfs window
  (20:16–20:19, 2026-06-01) and terminated; a manual re-run at 20:26
  passed rc=0 (741 KB log). Round 0 degraded 3→1 eval.
- **This is almost certainly the unidentified root cause of
  [foilsx04-all-preflight-ambiguous](/incidents/foilsx04-all-preflight-ambiguous.md)** ("whatever made X04 picks
  uniformly fail preflight with rc=3" — 20/20 children, never explained).
- **Fix (`autoresearch_bo_michael.py:1047`):** retry loop with backoff
  `(5,15,30)s`, but retries ONLY when `mu2e` never started — a genuine run
  always emits a Geant4/art banner (`"Geant4"|"%MSG"|"Art has"|"Begin
  processing"|"G4Exception"` in `out`), so real results (pass / geom-fail /
  true-ambiguous) and timeouts are NOT retried; only the empty-output env
  flake is. Source redirect changed `>/dev/null 2>&1` → `>/dev/null` so the
  flake's stderr reaches the captured log. Verified: py_compile clean,
  preflight re-run on both dead geoms passes rc=0. Each preflight is a fresh
  `python autoresearch_bo_michael.py preflight` subprocess
  (`graph/pipeline_io.py:129`), so a live closed-loop campaign picks up the
  fix on its next round without restart.

## REGRESSION + CONFIRMED ROOT CAUSE + FIX (2026-05-31)
- **Regression**: foilsX08R00_03 failed at mubeam submit with rc=**127** on
  `source setupmu2e-art.sh && source Run1Bak/setup.sh && muse setup ops && env`.
  The `muse setup ops` swap was live in the failing command string, so the
  2026-05-30 claim that the swap "removes the rc=127 failure class" is
  **wrong** — the flake is upstream of `muse`. Status reverted resolved →
  active, then fix applied (below).
- **Confirmed root cause (from the persisted `.err`, finally read)**: the
  `.err` files DID get written (to `/tmp/sourced_env_errs_oksuzian/`, 8 of
  them on 2026-05-31). The child submit log only *looked* empty because
  `CalledProcessError.__str__` omits `.stderr` — the cause was sitting in
  `/tmp` the whole time. Actual stderr:
  ```
  ==> Error: [Errno 5] Input/output error          # spack, during setupmu2e-art.sh
  /cvmfs/.../setupmu2e-art.sh: line 47: /bin/museDefine.sh: No such file or directory
  /cvmfs/.../Run1Bak/setup.sh: line 4: muse: command not found
  ```
  A **transient cvmfs read flake (Errno 5 EIO)** mid-`setupmu2e-art.sh`
  leaves the dir var empty → `museDefine.sh` resolves to bogus
  `/bin/museDefine.sh` → the `muse` shell function is never defined →
  `muse setup ops` is "command not found" → rc=127. NOT a PYTHONPATH issue:
  the closed-loop parent PID runs with a CLEAN env (verified via
  `/proc/<pid>/environ` — no PYTHONPATH/PYTHONHOME, no cvmfs on PATH), and
  8/10 round-0 children succeeded, so it's an intermittent cvmfs flake, not
  deterministic pollution.
- **Fix applied (retry with backoff)**: `sourced_env()` now wraps the
  `bash -c` source chain in a 4-attempt loop with 5/15/30s backoff
  (`pipeline.py:285-301`). cvmfs EIO flakes don't repeat seconds later, so
  retries recover the eval instead of losing the child. Sits *after* the
  if/else, so it covers both the submit path AND the `with_muse=True`
  harvest path. Verified: `py_compile` clean, 56/56 unit tests green. This
  is the retry-with-backoff that the old TODO wrongly dropped on the
  (now-disproven) assumption the `muse setup ops` swap removed the class.
- Line numbers (post 2026-05-30 edit): `sourced_env` `pipeline.py:301`
  (was 278; retry loop now spans 285-301), `cmd_submit` `pipeline.py:586`
  (was 559).
- Loss rate before the fix: 8th+ documented closed-loop child lost to this
  mode (X05 quartet + X06 trio + X08R00_03). Does NOT address the rc=69
  mfPlugin variant (source returns rc=0, so retry won't trigger).

## Env-source coverage map — CONSOLIDATED 2026-06-01
The cvmfs/spack flake can hit ANY env-source path; the four sites are NOT
redundant with each other (a child can flake at submit, harvest, preflight,
OR token-renew). **All four now route through one shared helper**
`graph/sourced_bash.py:run_sourced_bash(cmd, *, login, timeout, backoffs,
should_retry, label, log)`:
| Site | Guards | Retry (via helper) | `should_retry` gate |
|---|---|---|---|
| `pipeline.py:sourced_env` | grid submit + harvest | ✅ 4× 5/15/30s | `rc!=0` (default) |
| `autoresearch_bo_michael.py:cmd_preflight` | local preflight | ✅ | `rc!=0 AND no Geant4/art banner` |
| `pipeline.py` getToken (submit) | token renew (submit) | ✅ (was ❌) | `rc!=0` |
| `graph/closed_loop.py:node_renew_token` getToken | token renew (round) | ✅ (was ❌) | `rc!=0`, then FATAL exit if still failing |
- The helper handles the loop + subprocess + timeout (timeouts are
  NON-retriable → returned as `CompletedProcess(returncode=-1, timed_out=True)`,
  since a timeout means the command was running, not an env flake). Callers
  keep their own pre/post logic (env parse / raise CalledProcessError /
  sys.exit). Tests: `tests/test_audit_fixes.py:TestRunSourcedBash` (5 cases);
  `TestRenewToken` now mocks `cl.run_sourced_bash`, not `cl.subprocess.run`.
- **Do NOT remove any retry or revert the `muse setup ops` swap.** The swap's
  original "removes the rc=127 class" justification was disproven (top of
  file) but it's still the better baseline vs UPS `setup mu2egrid` (whose
  `setup` bash function is the thing that goes undefined). Retries are the
  actual fix.
- **Live-update nuance (load-bearing):** `pipeline.py` + `cmd_preflight`
  changes take effect IMMEDIATELY for a running closed-loop campaign because
  children re-invoke them as fresh subprocesses each stage/round. But
  `node_renew_token` lives in the **long-lived parent process**, which
  imported the old code at launch — so its new getToken-retry only applies to
  **future** parent launches, not an in-flight one. See
  [kerberos-mid-run-expiry](/incidents/kerberos-mid-run-expiry.md).

## Resolution (2026-05-30)
- `pipeline.py:271-310` swapped `setup mu2egrid` → `muse setup ops`;
  dropped `>/dev/null 2>&1` redirects; on rc!=0 the bash stderr is now
  persisted to `/tmp/sourced_env_errs_<user>/sourced_env_<ts>_rc<N>.err`
  before raising CalledProcessError (tail of stderr also injected into
  the exception's `.stderr` so the calling pipeline log shows the cause
  inline, not just a bare path).
- Verified end-to-end: `sourced_env()` returns rc=0 with 244-key env;
  `mu2ejobsub` resolves to
  `/cvmfs/mu2e.opensciencegrid.org/artexternals/mu2egrid/v8_03_02/bin/mu2ejobsub`,
  `mu2ejobdef` to `.../artexternals/mu2ejobtools/v2_03_00/bin/mu2ejobdef`.
- Unit suite (51 tests) stays green.
- pipeline.py:420 jobsub stderr swallow NOT yet mirrored — separate
  TODO; quota errors there aren't transient so retry isn't needed,
  only stderr capture.

## Summary
`pipeline.py:278 sourced_env()` runs
`bash -c 'source setupmu2e-art.sh >/dev/null 2>&1 && source <Musing>/setup.sh >/dev/null 2>&1 && setup mu2egrid >/dev/null 2>&1 && env'`
and on non-zero rc raises CalledProcessError with NO stderr captured. Any
transient cvmfs/setup blip surfaces as a bare `submit <stage> failed
(rc=1)` from pipeline.py — the actual failure reason (rc=127 for
`setup mu2egrid`, missing mfPlugin "cerr", etc.) is permanently lost.
Same anti-pattern as [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md) but a
DIFFERENT code path (line 278, not 420).

## Key facts
- **Trigger conditions** seen in foilsX06R00 (2026-05-30):
  - **rc=127 on `setup mu2egrid`** (R00_07, R00_08 concat submit) — both
    prior stages (mubeam, run1b_mubeam) succeeded 1-2h earlier in the
    same pipeline process. Transient — re-running by hand works.
    PR2/#6 logs surface it as `[graph] stage[concat/<name>] FAILED:
    submit concat failed (rc=1)`, but `sourced_env`'s stderr is gone.
  - **rc=69 on EdepAna harvest with mfPlugin "cerr" missing** (R00_09)
    — env source DID succeed but `CET_PLUGIN_PATH` ended up missing the
    message-logger plugin lib, so art's MessageLoggerScribe died at
    config-parse with `Library specification "cerr" does not correspond
    to any library in CET_PLUGIN_PATH of type "mfPlugin"`. Different
    shape: env was sourced but incomplete.
- **Loss rate in production**: 7 of 35 closed-loop children across X05+X06
  (foilsX05R00_04, R01_05, R01_06, R02_00 — all rc=127 silent under
  pre-PR2 logging; foilsX06R00_07/08 rc=127 + R00_09 rc=69 mfPlugin —
  visible thanks to PR2/PR3 diagnostics). **This is the dominant silent-
  failure mode of the closed-loop runner**, not an edge case. PR2/#6/#8
  catch the *symptom* but not the *cause*.
- **Root cause (cvmfs/spack flake, not 2 distinct bugs)**: On AL9
  `setupmu2e-art.sh` is `MU2E_SPACK=true` → `source spackages/241207/
  spack/setup-env.sh && spack load git/q3orrja && spack load muse/
  di7thnq`. Script has NO `set -e`. When a `spack load` hits a cvmfs
  read miss (worker `/etc/cvmfs/default.local`: single squid
  `squid.fnal.gov:3128`, `CVMFS_TIMEOUT=5`, `CVMFS_QUOTA_LIMIT=7000`),
  the script keeps going with a partial env. Two surface symptoms:
  - **rc=127** (R00_07/08, X05 quartet): `setup` ends up undefined →
    `setup mu2egrid` → bash "command not found". Exit code 127, not
    1, is the smoking gun.
  - **rc=69 with missing mfPlugin** (R00_09): source returns rc=0 but
    `CET_PLUGIN_PATH` is missing the
    `messagefacility-2.11.00-*/lib/` entry; art dies at MessageLogger
    config parse downstream. spack's view loads use `||`-tolerant per-
    line sourcing → silent partial-env propagation.
- **Why POMS doesn't see this**: Mu2e production uses the exact same
  chain (`source setupmu2e-art.sh && muse setup SimJob && setup
  mu2egrid` — `/cvmfs/.../Run1Bak/Production/CampaignConfig/
  mdc2020_stage1.cfg:15`), but POMS retries failed jobs at the
  campaign level. Autoresearch pipeline has no such wrapper.
- **Source file**: `pipeline.py:278` (`sourced_env`), called from
  `cmd_submit` at `pipeline.py:559` and `cmd_harvest` similarly.
  Both invocations use `subprocess.run(check=True, capture_output=True)`,
  but the CalledProcessError's `.stderr` is never logged before re-raise
  → only the bash command string survives.
- **Why retries would help**: foilsX06 R00_07 happened ~30s after
  R00_06's successful concat submit on the same node; cvmfs/grid-setup
  flakes are routinely transient. None of the 3 failures repeated on
  manual re-run.

## Cross-links
- Related: [jobsub-disk-quota-stderr-swallowed](/incidents/jobsub-disk-quota-stderr-swallowed.md) (sibling: pipeline.py
  swallows mu2ejobsub stderr at line 420 — same anti-pattern, different
  line), [edepana-saw-events-scientific-notation-parse](/incidents/edepana-saw-events-scientific-notation-parse.md), [mmackenz-edepana-lib-qualifier-bump](/incidents/mmackenz-edepana-lib-qualifier-bump.md)
- Related: [closed-loop-thread-id-checkpoint-collision](/incidents/closed-loop-thread-id-checkpoint-collision.md) (PR2/#6/#8
  surfaced these — closed-loop fix told us WHERE to look)
- Source files: `pipeline.py:278` (sourced_env), `pipeline.py:559`
  (cmd_submit env =), pipeline.py:cmd_harvest (same call)
- Detection logs:
  `/exp/mu2e/data/users/oksuzian/autoresearch_graph_data/closed_loop_logs/foilsX06R00_{07,08,09}.log`
  + `graph_data/.../foilsX06R00_09/harvest/edep.log`

## Open questions / TODO
- **Primary fix (single-line)**: replace `setup mu2egrid` (UPS — `setup`
  bash function is what silently goes undefined when `spack load` in
  `setupmu2e-art.sh` hits a cvmfs miss, producing rc=127) with
  `muse setup ops` (rc=0, provides identical binaries:
  `/cvmfs/.../artexternals/mu2egrid/v8_03_02/bin/mu2ejobsub`,
  `/cvmfs/.../artexternals/mu2ejobtools/v2_03_00/bin/mu2ejobdef`,
  `mu2eprodsys`). Verified 2026-05-30: `muse setup ops` rc=0 after
  `source setupmu2e-art.sh && source Run1Bak/setup.sh`.
  - Gotcha: `Run1Bak/setup.sh` alone does NOT add mu2egrid to PATH —
    something must add it. `muse setup ops` is the spack-native answer;
    `setup mu2egrid` is the UPS legacy answer (the brittle one).
  - Gotcha: `muse setup ops` invoked at top level (without sourcing
    Run1Bak first) gives rc=2 + "Exit code 2"; needs the Musing context.
- **Defense in depth (still worth doing)**: drop `>/dev/null 2>&1` in
  `sourced_env`, capture stderr to `graph_logs/sourced_env_<ts>.err` on
  rc!=0 before raising. Catches the orthogonal R00_09 case (partial
  CET_PLUGIN_PATH from a spack-view race, rc=0 from source, art rc=69
  downstream) which the `muse setup ops` swap does NOT eliminate.
  Mirror fix at pipeline.py:420 (jobsub stderr — sibling incident).
- **Dropped from TODO**: retry rc=127 with backoff + post-source env
  validation. Both were scaffolding to survive the UPS `setup` mode;
  swapping to `muse setup ops` removes the failure class so the
  scaffolding is unnecessary.
- Open question: what causes the partial `CET_PLUGIN_PATH` after a
  successful Musing source? Race against another mid-source process?
  Stale env inherited across foilsX06 children that share PIDs in
  /tmp? Out of scope for the immediate fix.
