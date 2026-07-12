---
name: jobsub-disk-quota-stderr-swallowed
description: mu2ejobsub fails rc=1 with no error in graph log — OSError 122 (disk quota) hidden by capture_output=True in submit_stage
type: incident
status: resolved
---

# jobsub-disk-quota — stderr swallowed by submit_stage

**Type:** incident
**Status:** recurring — stderr-swallow code path unchanged (now `pipeline.py:643`); foilsflash04 R1 lost 1/10 with quota HEALTHY 2026-07-01 (cause ≠ quota, still swallowed)
**Updated:** 2026-07-01

## Summary

A chain reaches "preflight: pass", builds the cnf .tar, then dies with
`subprocess.CalledProcessError: ... mu2ejobsub ... returned non-zero exit
status 1` and no stderr in either the graph log or the per-stage
`submit_<stage>_<ts>.log`. The real failure is **`OSError: [Errno 122]
Disk quota exceeded`** thrown by jobsub_lite during RCDS hash
publishing. The error is invisible because `pipeline.py:420` uses
`subprocess.run(..., check=True, capture_output=True)` — `check=True`
raises before lines 421-423 print `out.stderr`.

## Key facts

- **Symptom in graph log:** chain ends after `preflight: pass` with
  `[run] done. final keys: [...]` — no `cluster_id`, no stage transition.
- **Symptom in `submit_<stage>_<ts>.log`:** trace ends at
  `[mubeam] submitting: mu2ejobsub ...` followed directly by the
  `CalledProcessError` traceback — no jobsub_lite output.
- **Root cause (this incident, 2026-05-22):** `/nashome` at 94% global
  usage; per-user quota exhausted. jobsub_lite gzips the cnf .tar to a
  hash and uploads to RCDS; the second hash publish step throws
  `OSError: [Errno 122] Disk quota exceeded`. First hash publish often
  succeeds because the first gzip fits in remaining space.
- **Casualties (2026-05-22 episode):** `helicalQR00_02_ftfp` died at
  mubeam submit (chain never got a cluster_id). Three SR02 chains —
  `helicalSR02R00_01`, `_04`, `_05` — got past mubeam + run1b_mubeam
  with real cluster IDs but died at the *downstream* submit:
  `_01` and `_05` at concat, `_04` at mustops_ce. **The quota
  tightened mid-chain**, between the 12:05 mubeam-batch submissions
  (which succeeded) and the 12:08–12:16 downstream submissions (which
  failed). Lesson: a chain clearing preflight + mubeam is no
  guarantee the next submit will not hit the same wall — quota is a
  moving target during the run, not a one-shot precondition.
- **Per-stage recovery is cheap.** Because `pipeline.py` is per-stage
  idempotent and clusters from earlier stages are recorded in the
  SqliteSaver checkpoint, the recovery path for the 3 SR02 chains is
  `python pipeline.py --config <cfg> submit <stage>` for *just* the
  failed stage — no need to re-run mubeam. Pull the failed stage name
  from the checkpoint's `errors` field, not from the log (the log
  ends silent).
- **Footgun on retrying a template-edit experiment (2026-05-23):** the
  materialized `cnf.<...>.tar` reflects the template's contents at the
  moment pipeline.py rendered it, NOT at the moment the user "set up"
  the experiment. If template.fcl was edited (e.g. FTFP_BERT line
  added), then reverted, then the chain submitted (and the tar
  materialized post-revert), the tar carries the *reverted* state —
  the experimental knob never made it onto the grid. Verified on
  `helicalQR00_02_ftfp/mubeam/cnf...tar`: grepping for
  `physicsListName|FTFP_BERT` inside the tar's `mu2e.fcl` returned
  nothing despite the chain being launched with that intent. **Always
  grep the materialized tar's mu2e.fcl for the edited knob before
  declaring a chain ran the intended variant.** Recovery: delete the
  stale stage-dir contents and re-run with the edit live in template
  so pipeline.py re-materializes — per-stage idempotence will skip
  the re-materialization step if the cnf tar already exists.
- **Recurrence (ptX03R00, 2026-06-09 22:35):** 3/10 R0 children
  (R00_03, _04, _05) preflight=PASS then died at `mu2ejobsub` rc=1 with
  same swallowed-stderr shape. `/exp/mu2e/data` 16% used — disk is
  fine; cause TBD (still no df-of-`~` probe wired; stderr-swallow bug
  also still unpatched). Cluster IDs visible in
  `submit_pot_only_*.log` but never appeared in jobsub_q, so jobsub_lite
  rejected before submit. Pattern matches foilsg01 +
  helicalQR00_02_ftfp episodes — root cause likely home-quota again.
- **Recurrence (2026-06-09):** `foilsg01R00` round 0 lost 3/10 children
  (`_01`, `_03`, `_05`) at `mu2ejobsub` rc=1 with the same swallowed-
  stderr shape (`/pnfs` 27% + `/exp/mu2e/data` 16% — both fine, so disk
  bypass was elsewhere). User confirmed home (`/nashome`) was full at
  launch time and has since been cleaned up. Reinforces: home-quota
  exhaustion is the binding constraint for `mu2ejobsub` (jobsub_lite
  RCDS publish stages the tar through `~` before push), even when
  `/pnfs` and `/exp/mu2e/data` look healthy. Add `df ~ | tail -1`
  to the pre-launch checklist for any closed-loop campaign.
  Stderr-swallow bug still unpatched as of this incident — fix is
  one-liner below but skipped to keep launch hot. The exception line in
  `pipeline.py` is now line **534** (was 420 in the original incident).
- **`/nashome` quota is FILESYSTEM-wide, not per-user (2026-06-11).**
  `df /nashome` reports the **shared** mount across all `/nashome/*`
  users (5.8T total). Our home `/nashome/o/oksuzian` is only 5.1 G
  total (top dirs: `.npm` 2.8 G, `.local.OLD` 1.7 G, `.bun` 198 M,
  `.mozilla` 182 M, `.cache` 103 M). Freeing our own home cannot
  drop the 96%-full reading meaningfully — but RCDS publish only
  needs ~MB of headroom, so even freeing ~1-2 G locally may unstick
  it. The real recovery vector for a persistent "/nashome full"
  episode is **lab-side** (admin or another user freeing space),
  not user-side. Pre-launch `df ~ | tail -1` check is still the
  right cheap probe — but interpret >95% as "submission is at the
  mercy of other users' cleanup", not "I broke something."
- **Recurrence (foilsg04R00, 2026-06-11 07:54–08:25):** **all 10/10**
  R0 children died at `mu2ejobsub` rc=1 within ~25 min of launch (each
  ~5 min after `[mubeam] submitting:`). Manual replay confirmed
  `OSError: [Errno 122] Disk quota exceeded` on the **second** RCDS
  publish (`mu2e/02556053…` — the cnf.tar; first hash `mu2e/93f081aa…`
  for the .json published OK). `df ~` showed `/nashome` **96% full,
  5.5T used / 291G avail** — RCDS stages publish through `~/.cache`
  variant inside jobsub_lite. `/pnfs` 27%, `/exp/mu2e/data` 16% —
  unrelated. **All ten** children failed with the IDENTICAL pattern
  (preflight=PASS → submit-mubeam rc=1) — strongest signal yet that
  this is a binary "home-quota up / down" state, not a per-child race.
  decide_next then legitimately tripped its `zero new rows → all failed`
  guard (this time correctly, vs the false-positive of
  [[closed-loop-barrier-timeout-zero-rows-falsepos]] where children
  were still running). Recovery: free home, relaunch under a new
  `--name-prefix` (foilsg05) — the existing foilsg04R00_* names cannot
  be re-used because [[closed-loop-stale-cluster-silent-no-launch]]
  would skip them all.
- **Recurrence (foilsflash04R01_06, 2026-07-01) — quota was NOT the cause; the incident is BROADER than "disk quota".**
  1/10 R1 children died at the **mustops_ce** `mu2ejobsub` rc=1 (mubeam+concat had submitted fine) with the
  identical swallowed-stderr shape. But **quota was healthy**: `/exp/mu2e/data` 48.8% (1023 G headroom), token
  renewed OK, cnf tarball built (`Wrote ./cnf...tar`), FCL rendered fine — and **9/10 siblings submitted at the
  same instant**. So this instance is a **transient jobsub_lite/RCDS submit hiccup**, NOT `/exp/mu2e/data` EDQUOT.
  **CAVEAT (2026-07-01): the "quota healthy" check only looked at `/exp/mu2e/data` — NOT `/nashome`, the actual
  binding constraint** (RCDS stages the cnf tar through `~`). `/nashome` was **96% full (237 G avail)** shortly
  after, so a momentary `~` squeeze during the 10-way concurrent submit burst is a MORE likely cause than a
  generic jobsub hiccup. Unprovable here (stderr swallowed), but the lesson stands: when diagnosing a submit
  rc=1, check `df ~` FIRST, not just the CephFS data quota. Lesson: the
  `check=True`+`capture_output=True` swallow at the submit call hides **ALL** mu2ejobsub rc=1 causes (transient
  server/RCDS/network), not just disk quota — the page title undersells it. 1 lost eval of 30; qNEHVI robust,
  campaign proceeded (decide_next `+9 rows`); NOT recovered (no value re-running mid-next-round). The line is now
  **`pipeline.py:643`** (was 534/420).
- **BENIGN-NOISE trap when diagnosing a submit rc=1 (2026-07-01):** the submit log is full of
  `sh: <fn>: line 1: syntax error: unexpected end of file` / `sh: error importing function definition for
  '\`muse\`'/'\`spack\`'/'\`setup\`'/'\`slc\`'/'\`unsetup\`'/'\`_spack_shell_wrapper\`'` lines (~396 of them).
  These are **HARMLESS** exported-bash-function-into-`sh` warnings — verified they appear IDENTICALLY (~396 lines)
  in all 9 SUCCESSFUL sibling submit logs. Do NOT chase them as the cause of an rc=1; the real cause is the
  swallowed mu2ejobsub stderr.
- **`pipeline.py:534` stderr-swallow bug:**
  ```python
  out = subprocess.run(submit, ..., capture_output=True, text=True, check=True)
  print(out.stdout)
  if out.stderr.strip():
      print("STDERR:", out.stderr, file=sys.stderr)
  ```
  `check=True` raises `CalledProcessError` before the `print` lines.
  `CalledProcessError.stderr` *is* populated but Python's default
  `str(exc)` doesn't include it. Fix: wrap in `try/except
  CalledProcessError as e: print("STDERR:", e.stderr); raise`.

## Recovery recipe (when stderr is hidden)

1. Look at the per-stage log under
   `/exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/graph_logs/submit_<stage>_<ts>.log`.
   If it ends at the `[<stage>] submitting: mu2ejobsub ...` line + a
   traceback, stderr was swallowed.
2. Re-run mu2ejobsub by hand with the full env to see jobsub_lite
   output:
   ```bash
   cd /exp/mu2e/data/users/oksuzian/autoresearch_grid/<cfg>/<stage>
   bash -c 'source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh >/dev/null 2>&1 \
     && source /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak/setup.sh >/dev/null 2>&1 \
     && setup mu2egrid >/dev/null 2>&1 \
     && getToken >/dev/null 2>&1 \
     && mu2ejobsub --jobdef <cnf.tar> --firstjob 0 --njobs 1 \
        --default-location disk --default-protocol root --predefined-args=al9'
   ```
   `setup mu2egrid` is required to put mu2ejobsub on PATH; sourcing
   setupmu2e + Run1Bak musing alone is not enough.
3. If error is `OSError: [Errno 122] Disk quota exceeded`: free
   `/nashome` space (and possibly `/exp/mu2e/app`), then re-run
   `pipeline.py --config <cfg> submit <stage>`. The materialized
   `.tar` is per-stage idempotent so the FCL/code in the tar is
   preserved across the retry.

## Cross-links

- Related: [[concurrent-token-contention]] (other mu2ejobsub failure
  mode — also under submit-lock, but token-races, not quota), [[data-quota-exhausted-grid-accumulation]], [[sourced-env-stderr-swallowed]], [[venv-relocated-to-data-volume]].
- Source files: `pipeline.py:413-432` (`submit_stage` jobsub call +
  swallowed stderr), `pipeline.py:265-274` (env construction —
  `setup mu2egrid` requirement).
- Driver page: [[pipeline]] (per-stage submit semantics).

## Open questions / TODO

- Patch `pipeline.py:420` to surface stderr on CalledProcessError
  before re-raising. One-liner; do next time we touch that block.
- Add a pre-submit quota probe (e.g., `df` of `/nashome`) and skip
  submit with a clear error if free-space < 200 MB.
