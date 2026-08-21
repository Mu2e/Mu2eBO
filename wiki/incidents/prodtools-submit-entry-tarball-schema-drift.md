---
type: incident
title: prodtools submit_entry requires entry key 'tarball' — schema drift broke grid submit
description: 'first grid submit after the branch cuts died rc=1 "map entry missing required field: tarball" — the prodtools code-tarball branch was REBASED upstream (2026-08-15 commits, validated SHAs 8d6fe0e6/2eec6842/7a55ab4 gone) and submit_entry now requires the cnf tarball NAME as entry key `tarball`; our json2jobdef entry schema never had it; fixed by stamping Path(cnf).name at the driver seam'
status: resolved
status_note: fixed 2026-08-20 — prodtools_submit_driver.py stamps entry["tarball"] from a new --cnf arg
timestamp: '2026-08-20'
---

# prodtools submit_entry requires entry key 'tarball' — schema drift broke grid submit

## Summary
The first grid submission after the prodtools switch validation
(`gridsmoke01`, 2026-08-20) died at `submit mubeam` rc=1 with
`ValueError: map entry missing required field: 'tarball'` from
`utils/jobdesc.py:tarball_of`. Root cause is upstream drift, not our cuts:
the prodtools `code-tarball` branch was **rebased** after our 2026-08-16/17
validation (the wiki-recorded validated SHAs 8d6fe0e6/2eec6842/7a55ab4 no
longer exist in its history), and a 2026-08-15 commit series
(`b5c5569`..`e47689d`) changed `submit_entry`'s contract: the entry must now
carry the **cnf tarball NAME** under key `tarball` (a `Mu2eName` that parses
as a cnf tarball), with the code tarball path under `code` shipped via
jobsub `--tar_file_name` and digest-gated against the cnf's `code_ref`
(`utils/check_inputs.py:check_code_tarball`). Our checked-in
`stage_entries/<stage>.json` schema is json2jobdef's input schema and never
had a `tarball` key — at validation time `submit_entry` accepted the same
entry without it. The **local path (`runlocal`) is unaffected** — it takes
the cnf as a CLI arg, which is why the same-day local smoke (`cutsmoke01`)
passed while the first grid submit failed.

## Key facts
- Error surfaces in `graph_logs/submit_mubeam_<ts>.log` as a prodtools
  traceback ending `ValueError: map entry missing required field: 'tarball'`
  (`utils/jobdesc.py:36`); the graph child reports `stage[mubeam] FAILED`
  and terminates cleanly with no cluster submitted (no
  `state/mubeam_cluster.txt`).
- Fix (2026-08-20): `core/prodtools_exec.py:submit_cnf` gained a required
  keyword `cnf` and passes `--cnf` to `core/prodtools_submit_driver.py`,
  which stamps `entry.setdefault("tarball", Path(args.cnf).name)` after
  loading the entry. The on-disk `stage_entries/` + `state/<stage>_entry.json`
  schema is deliberately UNCHANGED (json2jobdef's schema stays the single
  source; the submit-map key is stamped at the seam).
- `cnf.<owner>.<desc>.<dsconf>.0.tar` parses as a valid cnf tarball under
  `Mu2eName` (verified against the current checkout), and the driver runs
  with cwd = the stage dir holding the cnf, so the bare basename resolves.
- `json2jobdef` in the same checkout stamps `code_ref` (sha256) into the cnf
  when the entry has `code`, so the new digest gate passes without changes
  on our side — but a cnf built by an OLDER json2jobdef would now fail the
  gate with `code_mismatch` ("entry and cnf disagree about code mode");
  rebuild the cnf (fresh submit) rather than fighting the gate.
- **cvmfs release `v3.1.0` is a drop-in pin**: `/cvmfs/mu2e.opensciencegrid.org/bin/prodtools/v3.1.0` ships all four verbs we shell and its `utils/jobdesc.py` + `utils/submit.py` are byte-identical to the checkout head the fix was validated against — README default switched to it 2026-08-20, which both kills this drift class and drops the personal-path dependency for outside users.
- The operator prodtools checkout
  (`/exp/mu2e/app/users/oksuzian/muse_050125/prodtools`, branch
  `code-tarball`) is a moving target that rebases: pinning validated SHAs in
  the wiki is not enough to reproduce a validated state. Any future
  "prodtools submit failed rc=1" with a schema-shaped ValueError should be
  checked against `git -C $AUTORESEARCH_PRODTOOLS log --since=<last-good>`
  before suspecting autoresearch.

## Cross-links
- Related: [sourced-env-drops-muse-function-local-jobs](/incidents/sourced-env-drops-muse-function-local-jobs.md), [foilsflash-tarball-mode-key-omission](/incidents/foilsflash-tarball-mode-key-omission.md)
- Source files: `core/prodtools_exec.py` (`submit_cnf`), `core/prodtools_submit_driver.py`, `core/pipeline.py` (submit call site)
- Driver: [pipeline](/drivers/pipeline.md)

## Open questions / TODO
- None.
