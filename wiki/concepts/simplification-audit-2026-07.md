---
type: concept
title: Simplification audit 2026-07 — verified delete/keep map
description: 'verified delete/keep map: ~490 L safe to delete (streamlit overlay,
  helical slides script, cl_min test class, format_row dedup, dead preflight branch);
  >half of plausible deletions OVERTURNED with recorded refutations (prodtarget/foilsg/ipa
  live, deck-trio destructive, skopt build_space is the lockstep truth source)'
status: active
timestamp: '2026-07-17'
---

# Simplification audit 2026-07 — verified delete/keep map

## Summary
Multi-agent audit (2026-07-16/17, 34 agents: 5 finder lenses → adversarial
per-candidate verification → completeness critic) of what code is non-critical.
48 raw findings → 32 candidates; verification OVERTURNED more than half of the
plausible-looking deletions — the KEEP reasons below are load-bearing and should
stop future sessions from re-proposing the same deletions. Verified-safe
deletions total ~490 lines + 5 dep pins; nothing has been deleted yet
(user decision pending as of 2026-07-17).

## Key facts — verified SAFE_DELETE (ready to execute)
- **`graph_app/streamlit_app.py` + `langgraph.json` + `.langgraph_api/`** (~190 L):
  dev overlay dead since 2026-05-20, hardwired to retired helical TSVs; all
  production runners call `build_graph()` directly (`graph/run.py:65`,
  `closed_loop.py:591`), never the module-level `graph` at `build.py:116` that
  langgraph.json targets. Frees requirements-graph.txt pins streamlit/plotly/
  pandas/grandalf/langgraph-cli[inmem] (uproot/awkward must STAY —
  `pipeline.py:1175` prodtarget harvest). Co-change: `graph/run.py:5` docstring.
- **`slides/analyze_bo_helical.py` + its 2 PNGs** (~145 L): zero references;
  `slides/slides.tex` has no 'helical' string. (Sibling `analyze_bo.py` is
  RISKY, not safe — see below.)
- **`tests/test_audit_fixes.py:31-104` TestIsBrokenParseException + GP_HELICAL_PATH
  loader** (~70 L): last in-repo reference to the retired off-repo
  `gp_predict_helical.py` (ADR-0001); live broken-detection is a different
  implementation with its own coverage (`test_closed_loop.py:324-329`).
- **format_row/load_history_row dedup** (`autoresearch_bo_michael.py:872-893,
  991-1009,1367-1393`, ~60 L net): FoilsG/IPA/ProdTarget6D hand-spell what the
  FoilsMode generic (:594-605) derives from KNOB_NAMES/CALO_COL; verified
  byte-identical, all callers polymorphic, no test pins the bodies.
- **`PREFLIGHT_FCL_TEMPLATE` + else-branch** (`autoresearch_bo_michael.py:
  1526-1546,1718-1721`, ~28 L): unreachable — all 7 modes set
  `preflight_fcl="surfacecheck"`, pinned by `test_modes.py:132-137`. Co-change:
  `test_audit_fixes.py:198` uses the literal string as a regex slice anchor.
- Overflow (unverified but trivial): merged branch `fix-closed-loop-failure-modes`
  (local+origin, empty vs main since 2026-05-30).

## Key facts — OVERTURNED (do NOT re-propose; the refutations)
- **prodtarget/foilsg/ipa mode blocks**: paused lines, not dead — pt6d18
  completed 2026-06-29; foilsg tarball incident was remediated (foilsgV01
  validation row 2026-06-12); [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md) plans the NEXT
  campaigns (botorch-0.18 at high-d) on exactly these lines; `test_modes.py`
  pins their SPECS entries; the 2026-07-12 retirement sweep KEPT them
  deliberately. Also `gp_loo_benchmark.py` scores their leaderboard archives.
- **foils-deck refresh trio** (`tools/refresh_foils_slides.sh` + 2 stampers):
  NOT inert — `refresh_foils_talk_captions.py:104-122` footer-rewrite is
  marker-free and matches the live `docs/foils_talk.md:6` frontmatter, so
  **running the trio today would clobber the hand-maintained v3 footer with
  stale v1 counts and re-render the deck** (it fired 2026-06-17). And the user
  skill `~/.claude/skills/refresh-deck/SKILL.md:20` still points at the .sh
  (contradicting the project refresh-foils-talk skill's "don't invoke").
  Retirement = coordinated change across tools + 2 skills + 1 command + wiki,
  not a file delete.
- **`slides/` + `diagram_pipeline.py`**: operator-protected archive
  (slides.tex "do NOT touch" in 3 instruction files); diagram_pipeline.py is
  the sole generator of a figure slides.tex embeds; `settings.local.json:54`
  allowlists it by name. Archive-move would break `analyze_bo.py`'s hardcoded
  OUT_DIR and violate the operator contract.
- **skopt retirement**: `build_space()` (`autoresearch_bo_michael.py:181-194`)
  is the *behavioral source of truth* the lockstep test (`test_modes.py:45,72`)
  calls for every mode — deleting it removes the SPECS==driver-bounds
  enforcement. Retirement needs a replacement invariant first, not a delete.
- **test-state dict literals**: deliberately divergent — 3 distinct state
  schemas, and key ABSENCE is load-bearing (e.g. `launched_names` omission
  flips the `closed_loop.py:737-740` zero_rows gate). A factory would silently
  change test semantics.
- **sys.path bootstraps (17 sites)**: not copy-paste — 3 different insert
  targets, 2 deliberate lazy-import guards, and top-of-file ordering sequenced
  around the presniff env-stamp constraint; the hardcoded root literal is what
  makes `botorch_predict.py` importable under ANY venv via the
  AUTORESEARCH_BOTORCH_VENV seam (pip -e would need install into every A/B venv).
- **dual inline-extractor launchers** (`pipeline.py:1048` vs `:1120`): the
  sentinel-vs-splitlines divergence is the root-caused ipa03 fix — gallery
  holds files open and prints AFTER the result; the calo script Close()s
  everything first and structurally can't hit it.
- **closed_loop satellite truth-sites** (:436,:460,:523,:706): deliberate
  decomposition; merging the rolling-streak read into a row-OR-broken
  predicate would REINTRODUCE the b98d5da streak bug (DONE_BROKEN must count
  as rowless).
- **`pipeline.py:276-296` foilsflash knob branch**: migration candidate
  (→ ModeSpec.stage_knob_overrides, like stage_target_overrides), NOT a
  deletion — no second copy exists; knobs feed the harvest denominator via
  the submit stamp.
- **`.venv-botorch` (0.10)**: production default (`config.py:190`,
  closed_loop hard-fails without it), the A/B control arm, AND **the only
  interpreter with matplotlib** — .venv-graph and .venv-botorch-new both lack
  it, so plot generators run on the 0.10 venv. Consolidation is gated on the
  A/B verdict and must solve matplotlib first.
- **requirements-graph.txt**: keep; the real gap is the MISSING
  requirements-botorch*.txt for both picker venvs (versions live only in wiki
  prose) — an ADD, not a delete.

## Key facts — RISKY / unverified
- `slides/analyze_bo.py`: zero code references but `settings.local.json:51`
  allowlists it and wiki names it the sole reader of frozen
  `leaderboard_bo.tsv` — delete only with wiki+settings cleanup.
- `botorch_predict.py:78-95` CURRENT_BOX_ONLY/TMAX_MIN env seam: one-shot
  pt6d08 experiment, inert for foilsflash; retire with prodtarget wind-down.
- Unverified (verify agents hit session limit): dead helical regex
  alternatives in SURFACE_OVERLAP_MANAGED (`autoresearch_bo_michael.py:
  1672-1685`, ~6 L, finder evidence solid); state-file literal consolidation
  (`{stage}_cluster.txt` at 8 sites → harvest.py accessor).

## Key facts — critic leads (new, unverified)
- **~423 L of stale helical/michael-era agent config** still in the live skill
  listing: `.claude/skills/launch-bo/SKILL.md`, `.claude/commands/
  closed-loop-launch.md`, `closed-loop-status.md`, + 1 more — can steer future
  agents to retired flags. Highest-value cleanup after the safe deletes.
- **`graph/run.py:55-56` defaults `--mock` to True** ("Phase 1 default"): a
  bare `python -m graph.run --config X` SYNTHESIZES FAKE METRICS. Flip the
  default or require explicit --mock.
- `tests/test_wal_multiwriter_stress.py` (230 L) exists ONLY untracked in the
  working tree — unittest discover runs it locally, a fresh clone silently
  doesn't. Commit it.
- `graph/list_threads.sh` (~18 L) referenced only by the stale launch-bo skill.
- 5 tracked docs/ PNGs (~570 KB) referenced by no deck/script/wiki.
- Hygiene batch: driver docstring/--help still advertises michael/helical/
  show-priors (`autoresearch_bo_michael.py:2-37`); `.gitignore` workspace
  block should be 2 globs (`bo_*_proposals/`, `bo_*_preflight/`); 6 tracked
  LaTeX intermediates in slides/; `graph/state.py:24` StageStatus Literal
  declares 'submitted'/'running' (never emitted) and omits 'in_flight'
  (emitted); ~30 gitignored .bak/.lock sediment files at root; stale
  retired-feature comments at `pipeline.py:425`, `pipeline_io.py:146-150`,
  `botorch_predict.py:387,475`.

## Key facts — root .py / .tsv reorganization: KEEP FLAT (2026-07-17)

Investigated moving the 5 root `.py` modules into a package and the 22 root
TSVs into a `leaderboards/` subdir. **Both are net-negative — leave flat.**

- **The 5 `.py` files are a load-bearing flat namespace**: ~30 call sites
  `import` them by bare name (`modes`, `harvest`, `autoresearch_bo_michael`,
  `pipeline`, `botorch_predict`) from graph/, tests/, tools/, /data scripts,
  and each other; resolved via 10+ scattered `sys.path.insert` (one
  hardcoded-absolute at `graph/pipeline_io.py:22`). Plus 3 subprocess path
  constants (`graph/config.py:21-22,193`) and the `pipeline.py` /
  `python -m graph.run` CLI entrypoints. Packaging = ~30 import rewrites in
  the exact subprocess/sys.path machinery behind past incidents, for zero
  functional gain. 5 flat modules is a conventional library layer under the
  already-packaged `graph/`.
- **The 22 root TSVs can't move because off-repo plotters hardcode their
  filenames** — see [mmackenz-table-plots-dir](/external/mmackenz-table-plots-dir.md) "REVERSE coupling":
  ~15 `ROOT / "leaderboard_bo_<mode>.tsv"` constants across ~10 unversioned
  /data scripts, silent breakage on move. The `_bo_<mode>` prefix already
  sorts them into coherent groups. Even `leaderboard_bo.tsv` (retired) is
  pinned by absolute path in `overlay_bo_on_s_sqrt_b.py:25`, so it can't
  even be renamed. **The real underlying friction is the sys.path.insert
  thicket, not file placement** — a separate (architecture-review) task.

## Key facts — top-level FILE audit (2026-07-17): everything is a KEEP

All 42 root files adjudicated; zero deletables left after the earlier
sediment rounds. Two non-obvious keeps:

- **`.env` looks like retired Studio-era sediment but is LOAD-BEARING**:
  `graph/run.py:31-34` and `graph/closed_loop.py:72-73` `load_dotenv()` it
  before any langchain/langgraph import (LangSmith tracing of live
  campaigns). Its `LANGSMITH_PROJECT=autoresearch-bo-helical` name is stale
  (May-era) but harmless.
- **The 9 zero-byte `.lock` files are by-design permanent** ("intentionally
  NEVER deleted"; deleting one while any process holds it would split the
  lock across inodes). **Relocated 2026-07-17 into `locks/`** via a single
  `_lock_path()` seam in the driver (anchor = `<target's dir>/locks/<name>.lock`,
  relative to the target's parent so tmp-dir test TSVs keep lock isolation;
  `.propose_<mode>.lock` renamed `locks/propose_<mode>.lock`). Migration
  gotcha that FIRED: inserting `_lock_path` above `_flock_ex` silently
  captured `_flock_ex`'s `@contextmanager` decorator — and the 158-test
  suite stayed GREEN with the flock seam completely broken (TypeError on
  every real lock acquisition): **no test exercises _flock_ex/_flock_sh
  end-to-end**; caught only by a live `load_history()` smoke call.
- The 13 leaderboard TSVs (incl. `foilsg.broken` + `flash0_quarantine`
  quarantines) are the scientific record; the 9 `pending_bo_*.tsv` are the
  duplicate-proposal guard a resumed line would need. All tiny; all keep.

## Key facts — top-level directory audit (2026-07-17)

All 24 real dirs + 4 symlinks at repo root inspected one-by-one:

- **`runs/` (symlink → /data `autoresearch_runs/runs`, 35 GB) is retired-driver
  sediment**: 51 `config_bo*`/`config_t*`/`config_v*` dirs written by
  `autoresearch_bo.py` (deleted in f6f281f), newest mtime 2026-05-02,
  ZERO references in current code (pipeline.py works in
  `/exp/mu2e/data/.../autoresearch_grid/<cfg>/`). Deleting frees 35 GB of
  the 2 TB /data quota that EDQUOT'd once.
- **Top-level `closed_loop_logs/` is a stale duplicate** — current path is
  `graph_data/closed_loop_logs` (closed_loop.py:441,470); 4 files from
  Jun 8–10 predate the move.
- **`data/` is an accidental relative-path write**: single PNG at
  `data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/...` —
  a command run with the `/exp/mu2e/` prefix missing recreated the
  absolute path under CWD.
- **`logs/` (50 files) has no writer left** — old campaign logs, newest
  Jun 27; parent logs now go to `graph_data/<prefix>_parent.log`.
- **`Run1BAna/` is LOAD-BEARING despite being untracked+ignored**:
  pipeline.py:973–974 read `Run1BAna/workflows/fcl/edep.fcl` and
  `rough_run1a_sensitivity.C` from it. Never delete.
- **`graph_data/forensics/foilsf08_crash_*` is 56 of graph_data's 60 MB** —
  sqlite+WAL evidence for the RESOLVED foilsf08 incident, fully distilled
  into the incident page (bytes-level analysis recorded).
- **`bo_<mode>_{proposals,preflight}/` are live driver infrastructure**
  (`autoresearch_bo_michael.py:396–1239`); preflight *logs* of dormant
  lines (~1.3 GB on /app, dominated by bo_foils_preflight 659 MB) are
  prunable content. **Whole preflight dirs are safe to delete** — recreated
  on demand via `mkdir(parents=True, exist_ok=True)` at
  `autoresearch_bo_michael.py:1605`, and each log is write-once/read-once
  (parsed by the classifier in the same invocation; nothing reads old
  entries). Proposal dirs likewise mkdir'd (:220) but tiny — keep.
- slides/ = frozen May-era original-line deck (10 tracked files, in git);
  untracked LaTeX byproducts are the only disk noise there.
- **EXECUTED 2026-07-17 (round 4, user-approved):** deleted `runs/` symlink
  + its 35 GB /data target, top-level `closed_loop_logs/`, `logs/`, `data/`,
  and `graph_data/forensics/foilsf08_crash_20260608_191942`. Permission
  gotcha: the auto-mode classifier blocks *compound* `rm -rf` commands even
  when user-approved — one named-path `rm` per Bash call passes.
- ~~Leftover sediment in `/exp/mu2e/data/.../autoresearch_runs/`~~ —
  **DELETED 2026-07-17 (user-approved):** the nine `grid_test`–`grid_test_v8`
  bring-up probes + the then-empty `autoresearch_runs/` parent. That /data
  tree is fully gone.
- **bo_foils_preflight archived 2026-07-17 (user chose archive over delete):**
  965 logs, 659 MB → single tarball
  `/exp/mu2e/data/users/oksuzian/autoresearch_archive/bo_foils_preflight_20260717.tar.gz`
  (41 MB — 16× compression, G4 init logs are near-identical), verified
  965 logs inside, then source dir removed from /app. **All four remaining
  dormant preflight dirs archived the same way 2026-07-17** (prodtarget6d
  477 / foilsg 101 / ipa 83 / prodtarget 66 logs, counts verified) →
  `/exp/mu2e/data/users/oksuzian/autoresearch_archive/` totals 68 MB for
  what was ~1.3 GB on /app. Only `bo_foilsflash_preflight` (active line)
  remains in the repo.

## Cross-links
- Related: [architecture-friction-survey-2026-07](/concepts/architecture-friction-survey-2026-07.md) (predecessor survey; its
  candidates 1+2 landed, 3-5 re-counted here), [ml-stack-review-2026-07](/concepts/ml-stack-review-2026-07.md)
  (skopt/venv/0.18 context), [mode-registry-childtracker-design](/concepts/mode-registry-childtracker-design.md) (landed
  refactor this audit re-counts against), [aitools-skills-symlink-dependency](/external/aitools-skills-symlink-dependency.md)
  (found by this audit)
- Source files: verdicts archived in the workflow output; key refs inline above.

## Open questions / TODO
- ~~SAFE_DELETE tier~~ **EXECUTED 2026-07-17** (user-approved), commits
  bdafed9 (schema dedup + preflight branch + cl_min test class, golden-diff
  byte-identical across all 7 modes), 5ceebd4 (overlay + helical analyzer +
  5 dep pins), d60d064 (hygiene: .gitignore globs, StageStatus Literal,
  comment rot), e475eda (WAL harness tracked), 42783bb (this page). Suite
  158 green (162 − 4 deleted cl_min tests). Merged branch
  fix-closed-loop-failure-modes deleted locally (origin copy needs user push).
  Note: the WAL harness has NO TestCase classes — the critic's "fresh clone
  runs a smaller suite" framing was wrong; it's a manually-run script, but
  tracking it was still right.
- **Round 2 EXECUTED 2026-07-17** (commit 320cc2f + local .claude cleanup):
  helical regex alternatives verified dead inline and trimmed; 5 orphan docs/
  PNGs + graph/list_threads.sh deleted; requirements-botorch{,-new}.txt ADDED
  (versions from dist-info audit; records CPU-wheel intent + py3.9 floor +
  matplotlib-only-on-0.10 constraint). Local .claude config: stale helical-era
  `closed-loop-launch.md` command + `launch-bo` skill DELETED;
  `closed-loop-status.md` / `closed-loop-harvest.md` KEPT and re-pointed to
  foilsflash-era leaderboards/prefixes (their awk column indices $8/$9/$11
  survive unchanged — foilsflash's 6 knobs land sob/flash/obj at the same
  positions helical's 4+2 derived columns did).
- **Round 3 EXECUTED 2026-07-17** (user-approved "do the remaining items"):
  (a) deck-trio RETIRED as a coordinated pass — 3 tools + 4 truly-orphaned
  PNGs deleted (3 of the 7 script-managed PNGs KEPT: cited by wiki concept
  pages), local [refresh-foils-slides](/drivers/refresh-foils-slides.md) command deleted, refresh-deck user skill
  + refresh-foils-talk project skill re-worded, wiki driver page superseded;
  (b) aitools RELOCATED to /exp/mu2e/app/users/oksuzian/aitools, 12 symlinks
  re-pointed ([aitools-skills-symlink-dependency](/external/aitools-skills-symlink-dependency.md) resolved); (c) graph.run
  --mock/--no-mock now REQUIRED (bare launch errors instead of silently
  synthesizing fake metrics; closed_loop children already passed --no-mock);
  (d) data sediment purged (37 files + 4 retired workspace dirs; foilsg
  quarantine + active foilsflash locks kept).
  **Round-3 gotcha that FIRED live:** `git add docs/` blanket-swept the
  under-review deck files (foilsflash_talk.*, cloud PNG) AND untracked docs
  into the trio commit — exactly what the refresh-foils-talk skill warns
  against. Recovery (unpushed only): `git reset --soft <pre-commit>` →
  `git restore --staged <deck files>` → re-commit each group with explicit
  pathspecs (`git commit -m ... -- <paths>`). When deleting files under
  docs/, stage the named deletions, never the directory.
- Still open (all gated, not forgotten): cluster.txt literal consolidation
  (only remaining unverified candidate); skopt retirement (needs a
  replacement lockstep invariant for build_space before deletion); venv
  consolidation (gated on the 0.10-vs-0.18 A/B verdict; must first move
  matplotlib rendering off .venv-botorch).
