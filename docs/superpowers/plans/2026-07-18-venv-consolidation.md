# Venv Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three venvs (`.venv-graph`, `.venv-botorch`, `.venv-botorch-new`) with one fresh `.venv` (Python 3.11, langgraph + botorch 0.18 + matplotlib/sklearn), validated through 7 ordered gates before anything is deleted.

**Architecture:** Build the new venv on /data and symlink it at the repo root exactly like the current three. Validate it against the untouched repo first (the `AUTORESEARCH_BOTORCH_VENV` env seam lets the picker run under `.venv` with zero code changes), then flip the two seam defaults, sweep references, and only then delete. The `botorch_ask()` subprocess seam and the env override survive by design.

**Tech Stack:** uv 0.11.8, Python 3.11, langgraph 1.2, botorch 0.18.1 / gpytorch 1.15.2 / torch 2.13.0+cpu, numpy 2.4.6, scipy 1.17.1, matplotlib, scikit-learn, uproot/awkward.

**Spec:** `docs/superpowers/specs/2026-07-18-venv-consolidation-design.md`

## Global Constraints

- **NEVER `git push`** — Bash subshells cannot reach the user's ssh-agent (wiki incident `claude-bash-no-ssh-agent`). The user pushes from their interactive shell.
- Every commit message ends with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- **Never blanket `git add docs/`** — deck files under `docs/` (`foilsflash_talk.*`, `foilsflash_beamer.*`, `*_cloud.png`, `gp_holdout_verdict.png`) stay uncommitted for operator review. Stage named paths only (`git add -- <path>`).
- **One named-path `rm` per Bash call** — the auto-mode classifier blocks compound rm commands. Never wildcard `rm -rf *`.
- **Precondition for every task:** no campaign running. Check `pgrep -f "closed_loop"` and `pgrep -f "graph.run"` return nothing before starting; abort if not.
- Venvs live at `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/`, symlinked from the repo root. The repo root is `/exp/mu2e/app/users/oksuzian/autoresearch` (all relative paths below are from there).
- Wiki edits follow the OKF contract: bump `timestamp:` on every edited page, keep `description:` in sync with its `index.md` one-liner, add `log.md` bullets under a `## 2026-07-18` heading at the TOP (newest-first).
- **Nothing is deleted (files or venvs) until all validation gates in Tasks 2–7 have passed.**

---

### Task 1: Merged `requirements.txt` + `.gitignore` glob

**Files:**
- Create: `requirements.txt`
- Modify: `.gitignore:5`
- (The three old requirements files are NOT deleted here — that happens in Task 9, after validation.)

**Interfaces:**
- Produces: `requirements.txt` — the single rebuild recipe Task 2's build consumes verbatim.

- [ ] **Step 1: Write `requirements.txt`**

Exact content (pins: numeric stack exactly matches the current `.venv-graph`/`.venv-botorch-new` twins so nothing shifts under the tests; torch is installed separately from the CPU wheel index, same convention as the old `requirements-botorch-new.txt`; scikit-learn is REQUIRED — 8 off-repo plotters import `sklearn.gaussian_process`, it was silently present in `.venv-botorch` but never recorded in its requirements file):

```
# Rebuild recipe for .venv — the SINGLE project venv (orchestrator + botorch
# picker + plot renderers), consolidated 2026-07-18 from .venv-graph +
# .venv-botorch (botorch 0.10, retired) + .venv-botorch-new (botorch 0.18).
# See docs/superpowers/specs/2026-07-18-venv-consolidation-design.md.
#
# Python 3.11, uv-built. CPU torch wheel (+cpu local version) FIRST, then
# the rest:
#   uv venv --python 3.11 /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv
#   uv pip install --python /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv/bin/python \
#     --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
#   uv pip install --python /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv/bin/python \
#     -r requirements.txt
#   ln -s /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv .venv
#
# The AUTORESEARCH_BOTORCH_VENV env seam still selects an alternate picker
# venv for A/Bs (e.g. a future train_Yvar or botorch-0.19 arm).
langgraph>=0.2.50
langgraph-checkpoint-sqlite>=1.0.0
botorch==0.18.1
gpytorch==1.15.2
numpy==2.4.6
scipy==1.17.1
# Renderers (were only on the retired .venv-botorch): matplotlib pulls pillow.
matplotlib>=3.9
# 8 off-repo plotters use sklearn.gaussian_process (was unrecorded in
# requirements-botorch.txt — present in the old venv but never pinned).
scikit-learn>=1.6
# ROOT file reader for bo-prodtarget harvest-pot-only (pot_vd.root TTrees + genCountLogger TH1D).
uproot>=5
awkward>=2
```

- [ ] **Step 2: Fix the `.gitignore` glob**

`.gitignore:5` is `.venv-*`, which does not match the new name `.venv`. Edit:

```
old: .venv-*
new: .venv*
```

- [ ] **Step 3: Verify the glob**

Run: `git check-ignore -v .venv .venv-graph .venv-botorch-new`
Expected: three lines, each matched by `.gitignore:5:.venv*`.

- [ ] **Step 4: Commit**

```bash
git add -- requirements.txt .gitignore
git commit -m "feat: merged requirements.txt for the single .venv

One rebuild recipe replaces the graph/botorch/botorch-new trio (files
deleted after validation). Adds scikit-learn, which .venv-botorch carried
silently (8 plotters import it) but requirements-botorch.txt never
recorded. .gitignore .venv-* -> .venv* to cover the new name.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c" -- requirements.txt .gitignore
```

---

### Task 2: Build `.venv` (GATE 1 — resolution + imports)

**Files:** none in-repo (operation). Creates `/exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv` and the root symlink `.venv`.

**Interfaces:**
- Consumes: `requirements.txt` from Task 1.
- Produces: `.venv/bin/python` — the interpreter every later task uses.

- [ ] **Step 1: Create the venv and install torch from the CPU index**

```bash
uv venv --python 3.11 /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv
uv pip install --python /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv/bin/python \
  --index-url https://download.pytorch.org/whl/cpu torch==2.13.0+cpu
```

Expected: torch 2.13.0+cpu installs (~183 MB CPU wheel, NOT a ~2.5 GB CUDA wheel).

- [ ] **Step 2: Install the rest**

```bash
uv pip install --python /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv/bin/python \
  -r requirements.txt
```

Expected: clean resolution. **If uv cannot resolve** (langgraph-vs-torch conflict — judged unlikely, disjoint trees): STOP the whole plan and report; the spec's fallback is the two-venv shape with nothing else touched.

- [ ] **Step 3: Symlink at the repo root**

```bash
ln -s /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv .venv
```

- [ ] **Step 4: Import smoke (gate 1 passes here)**

Run:
```bash
.venv/bin/python -c "import langgraph, botorch, gpytorch, torch, matplotlib, sklearn, uproot, awkward; print('OK', torch.__version__, botorch.__version__)"
```
Expected: `OK 2.13.0+cpu 0.18.1`.

---

### Task 3: GATE 2 — main suite green under `.venv`

No code changes — the new venv must satisfy everything `.venv-graph` did, unmodified.

- [ ] **Step 1: Run the suite**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: `OK` with 156 tests (same count the suite reports under `.venv-graph`). Any failure = a missing/incompatible dependency in `requirements.txt`; fix the requirements file (amend Task 1's commit is NOT needed — a follow-up `fix:` commit is fine), reinstall, re-run.

---

### Task 4: GATE 3 — real picker smoke under `.venv`

Uses the `AUTORESEARCH_BOTORCH_VENV` env seam, so the repo stays untouched: the picker subprocess runs under `.venv` while the defaults still say `.venv-botorch`.

- [ ] **Step 1: Run a real qNEHVI ask on the live foilsflash leaderboard**

Run (GP fit on ~274 rows takes minutes — use a 600000 ms timeout or run in background):
```bash
AUTORESEARCH_BOTORCH_VENV=.venv .venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import bo_driver as bo
picks = bo.botorch_ask('foilsflash', q=2)
print('PICKS', picks)
assert len(picks) == 2 and all(len(p) == 6 for p in picks), picks
"
```
Expected: `PICKS [[...6 floats...], [...6 floats...]]`, exit 0. This exercises botorch 0.18 fitting the real 6D archive end-to-end — the configuration foilsflash will use in production after the flip.

---

### Task 5: GATE 4 — full mock chain under `.venv`

Exercises langgraph + SqliteSaver + the pipeline_io subprocess wiring end-to-end with zero grid contact. The mock chain appends a real row to the live leaderboard, so this task ends by removing it.

- [ ] **Step 1: Compute a mid-bounds x-point (avoids a second GP ask; gate 3 covered that)**

```bash
XPT=$(.venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import modes
s = modes.SPECS['foilsflash']
print(','.join(str((lo + hi) / 2) for lo, hi in zip(s.bounds_lo, s.bounds_hi)))")
echo "XPT=$XPT"
```

- [ ] **Step 2: Run the mock chain**

```bash
mkdir -p /tmp/oksuzian/venvsmoke
AUTORESEARCH_MODE=foilsflash AUTORESEARCH_CHECKPOINT_DIR=/tmp/oksuzian/venvsmoke \
  .venv/bin/python -m graph.run --mode foilsflash --thread-id venvsmoke1 \
  --config-name venvsmoke1 --x-point "$XPT" --mock 2>&1 | tail -20
```
Expected: node sequence reaches `END`, evaluate reports an appended row for `venvsmoke1` with mock metrics, exit 0.

- [ ] **Step 3: Verify then remove the smoke row + artifacts**

```bash
grep -c "^venvsmoke1	" leaderboards/leaderboard_bo_foilsflash.tsv   # expect 1
grep -v "^venvsmoke1	" leaderboards/leaderboard_bo_foilsflash.tsv > /tmp/oksuzian/venvsmoke/lb.tmp
cp /tmp/oksuzian/venvsmoke/lb.tmp leaderboards/leaderboard_bo_foilsflash.tsv   # cp, not mv: preserves the flock inode
grep -c "venvsmoke1" leaderboards/pending_bo_foilsflash.tsv || echo "pending clean"   # expect 0 / clean
```
Then remove the scratch state (one named path per call):
```bash
rm -rf state/venvsmoke1
```
```bash
rm -f bo_work/proposals/foilsflash/venvsmoke1_geom.txt
```
```bash
rm -rf /tmp/oksuzian/venvsmoke
```
Verify: `git diff --stat leaderboards/` shows no change vs HEAD for the leaderboard (row added then removed → byte-identical).

---

### Task 6: GATE 5 — plotter regeneration under `.venv`

- [ ] **Step 1: Regenerate the active-deck cloud figure**

```bash
cd /exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots
/exp/mu2e/app/users/oksuzian/autoresearch/.venv/bin/python gp_predict_foilsflash_perpot_cloud.py
```
Expected: exits 0, writes its PNG. If it raises on a botorch 0.10→0.18 API difference, fix the script in place (they are unversioned /data scripts by convention) and note the fix for the Task 9 log entry.

- [ ] **Step 2: Eyeball the output**

Read the generated PNG (Read tool renders it inline). Expected: a recognizable perpot cloud — small shifts vs the committed `docs/foilsflash_perpot_cloud.png` are ACCEPTED (0.18 GP defaults; spec records this; the next deck refresh regenerates deck figures).

---

### Task 7: Flip the seam defaults + in-repo sweep (GATE 6)

**Files:**
- Modify: `graph/config.py:188-198`, `core/bo_driver.py:1182-1196`
- Modify (comment/docstring sweep): `core/botorch_predict.py:5-12,39`, `core/modes.py:7-8`, `graph/closed_loop.py:101,288-289,311,831`, `graph/run.py:8`, `tests/test_audit_fixes.py:12`, `tests/test_nodes.py:4`, `tests/test_wal_multiwriter_stress.py:22`

**Interfaces:**
- Produces: `BOTORCH_VENV_PY` default = `PROJECT_ROOT / ".venv" / "bin" / "python"`; same rule in `bo_driver.botorch_ask`. `AUTORESEARCH_BOTORCH_VENV` override unchanged.

- [ ] **Step 1: `graph/config.py` — comment block + default**

Replace lines 188–198:
```python
# Disjoint-venv plumbing: closed_loop.py runs under .venv-graph (langgraph,
# sklearn, skopt) but the botorch_predict.py qNEHVI picker needs .venv-botorch
# (gpytorch + botorch). When --picker qnehvi is requested, node_predict_picks
# subprocess-shells into this interpreter, dumps picks to a tmp JSON, and
# loads them back into the langgraph state.
# AUTORESEARCH_BOTORCH_VENV overrides the venv DIRECTORY for a picker A/B
# (e.g. .venv-botorch-new = botorch 0.18 defaults; see wiki
# ml-stack-review-2026-07 — accuracy question unresolved at n=10 holdout).
BOTORCH_VENV_PY = (PROJECT_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv-botorch")
                   / "bin" / "python")
```
with:
```python
# Picker subprocess plumbing: node_predict_picks shells botorch_predict.py
# into a child interpreter, dumps picks to a tmp JSON, and loads them back
# into the langgraph state. Since the 2026-07-18 venv consolidation there is
# ONE project venv (.venv) — the subprocess keeps torch out of the
# long-lived orchestrator process, not out of a different dependency set.
# AUTORESEARCH_BOTORCH_VENV overrides the venv DIRECTORY for a picker A/B
# (e.g. a future train_Yvar or botorch-0.19 arm; see wiki
# ml-stack-review-2026-07).
BOTORCH_VENV_PY = (PROJECT_ROOT
                   / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
                   / "bin" / "python")
```

- [ ] **Step 2: `core/bo_driver.py` — default + error message**

Two edits:
```python
old:                    / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv-botorch")
new:                    / os.environ.get("AUTORESEARCH_BOTORCH_VENV", ".venv")
```
```python
old:             f"(install .venv-botorch or set AUTORESEARCH_BOTORCH_VENV)")
new:             f"(install .venv or set AUTORESEARCH_BOTORCH_VENV)")
```

- [ ] **Step 3: Comment/docstring sweep**

In each remaining file, update the venv names in comments/docstrings (no logic changes). Exact replacements:

- `core/botorch_predict.py:5-6`: `round (disjoint venvs — this runs under .venv-botorch, the graph under\n.venv-graph; picks round-trip via --emit-picks-json).` → `round (subprocess seam — runs under the project .venv; picks round-trip\nvia --emit-picks-json).`
- `core/botorch_predict.py:12`: `.venv-botorch/bin/python botorch_predict.py \\` → `.venv/bin/python botorch_predict.py \\`
- `core/botorch_predict.py:39`: `— stdlib-only, so .venv-botorch (no skopt) can` → `— stdlib-only, so any venv can`
- `core/modes.py:7-8`: `error, never a default), stdlib-only so every venv (.venv-graph,\n.venv-botorch) and pipeline.py can import it.` → `error, never a default), stdlib-only so the project .venv (and any\nA/B picker venv) and pipeline.py can import it.`
- `graph/closed_loop.py:101`: `# in-repo botorch_predict.py in .venv-botorch.` → `# in-repo botorch_predict.py in the project .venv.`
- `graph/closed_loop.py:288-289`: `Disjoint-venv: closed_loop.py runs under .venv-graph (no botorch); the\nbotorch pickers need .venv-botorch (no langgraph). bo.botorch_ask owns` → `Picker subprocess: bo.botorch_ask shells into BOTORCH_VENV_PY (the\nproject .venv by default; AUTORESEARCH_BOTORCH_VENV overrides). It owns`
- `graph/closed_loop.py:311`: `All pickers subprocess into .venv-botorch (disjoint venv) to run` → `All pickers subprocess into BOTORCH_VENV_PY (.venv by default) to run`
- `graph/closed_loop.py:831`: `help="batch picker (all subprocess into .venv-botorch; "` → `help="batch picker (all subprocess into the picker venv; "`
- `graph/run.py:8`: `source .venv-graph/bin/activate` → `source .venv/bin/activate`
- `tests/test_audit_fixes.py:12`, `tests/test_nodes.py:4`, `tests/test_wal_multiwriter_stress.py:22`: `.venv-graph/bin/python` → `.venv/bin/python`

(Read each location before editing — line numbers may drift a line or two; match on the quoted text.)

- [ ] **Step 4: GATE 6a — suite green after the flip**

Run: `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -3`
Expected: `OK` (156).

- [ ] **Step 5: GATE 6b — picker smoke WITHOUT the env override (proves the new default)**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'core')
import bo_driver as bo
picks = bo.botorch_ask('foilsflash', q=1)
print('PICKS', picks)
assert len(picks) == 1 and len(picks[0]) == 6
"
```
Expected: 1 pick of 6 floats, exit 0 — resolved via the new `.venv` default.

- [ ] **Step 6: Verify no live-path stragglers**

Run: `grep -rn "\.venv-graph\|\.venv-botorch" core/ graph/ tests/ 2>/dev/null`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add -- core/bo_driver.py core/botorch_predict.py core/modes.py graph/config.py graph/closed_loop.py graph/run.py tests/test_audit_fixes.py tests/test_nodes.py tests/test_wal_multiwriter_stress.py
git commit -m "refactor: seam defaults + comments .venv-botorch/.venv-graph -> .venv

Single-venv consolidation flip: BOTORCH_VENV_PY and botorch_ask default
to .venv; AUTORESEARCH_BOTORCH_VENV A/B override unchanged. Suite green
and a no-override picker smoke passed under the new default before this
commit.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

---

### Task 8: Ops sweep — off-repo plotters + operator skills (no commit)

**Files (off-repo /data, unversioned by convention):**
- Modify: every `*.py` in `/exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots/` containing `venv-botorch` (docstring "Run with" lines; ~13 files)

**Files (user skills):**
- Modify: `~/.claude/skills/launch-bo-chain/SKILL.md:14,31`, `~/.claude/skills/more-jobs/SKILL.md:35`

- [ ] **Step 1: Plotter docstring sweep**

```bash
cd /exp/mu2e/data/users/oksuzian/autoresearch_grid/mmackenz_table_plots
for f in $(grep -l "venv-botorch" *.py); do sed -i 's/\.venv-botorch/.venv/g' "$f"; done
grep -rn "venv-botorch" *.py | wc -l   # expect 0
```

- [ ] **Step 2: Skill sweep**

In `~/.claude/skills/launch-bo-chain/SKILL.md`: `source .venv-graph/bin/activate` → `source .venv/bin/activate`; ``The venv is `.venv-graph` (uv-built, Python 3.11).`` → ``The venv is `.venv` (uv-built, Python 3.11; single project venv since 2026-07-18).`` In `~/.claude/skills/more-jobs/SKILL.md`: ``from `.venv-graph`,`` → ``from `.venv`,``.

- [ ] **Step 3: Verify**

Run: `grep -rn "\.venv-graph\|\.venv-botorch" ~/.claude/skills/ 2>/dev/null`
Expected: no output.

---

### Task 9: Delete old requirements files + wiki sweep + spec amendment

**Files:**
- Delete: `requirements-graph.txt`, `requirements-botorch.txt`, `requirements-botorch-new.txt` (git history is the 0.10 rebuild archive)
- Modify: `wiki/concepts/ml-stack-review-2026-07.md`, `wiki/concepts/simplification-audit-2026-07.md`, `wiki/incidents/venv-relocated-to-data-volume.md`, `wiki/drivers/tests.md`, `wiki/index.md`, `wiki/log.md`
- Modify: `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`

Policy for the other wiki pages that mention old venv names (incidents, project pages, `bo-driver.md`, `closed-loop-runner.md`, `graph-runner.md`, `qlnei-sob-only-picker.md`, `gp-cloud-rendering.md`, `batch-bo.md`, `refresh-foils-slides.md`, ADR-0002): **historical narrative stays as-is** (it describes what was true then); update only lines that are LIVE guidance a future session would follow (run commands, "install X", "use venv Y"). Grep each: `grep -n "venv-graph\|venv-botorch" wiki/<page>` and judge per line.

- [ ] **Step 1: git rm the three requirements files**

```bash
git rm requirements-graph.txt requirements-botorch.txt requirements-botorch-new.txt
```

- [ ] **Step 2: Wiki — ml-stack-review verdict revision**

Add under Key facts (and bump `timestamp:` to `2026-07-18`):

```markdown
- **VERDICT REVISED 2026-07-18 (user decision, venv consolidation):**
  botorch 0.10 RETIRED with the single-venv consolidation (see
  docs/superpowers/specs/2026-07-18-venv-consolidation-design.md) —
  recommendation #1 ("keep the 0.10 stack for the next campaign") was
  revisited eyes-open: foilsflash continues on **0.18-base**, accepting the
  measured 6D corner regression (corner NLL −1.35 vs −2.14) in exchange for
  one venv, 0 fit failures, ~15% faster fits, and access to train_Yvar.
  Recommendation #2 stands: per-row train_Yvar is the next env-flagged A/B
  (AUTORESEARCH_BOTORCH_VENV seam kept for exactly this).
```

Update the page `description:` (and its `wiki/index.md` one-liner, keeping them mirrored) to append `; 0.10 retired 2026-07-18 (single .venv, 0.18-base)`.

- [ ] **Step 3: Wiki — simplification-audit KEEP superseded**

In the `.venv-botorch` KEEP bullet, append (and bump `timestamp:`):

```markdown
  **SUPERSEDED 2026-07-18:** the venv pair was consolidated to a single
  .venv (botorch 0.18) — the A/B verdict landed (ff16+ff17), matplotlib
  moved into the merged venv, and 0.10 was retired by user decision. See
  docs/superpowers/specs/2026-07-18-venv-consolidation-design.md.
```

Also update this page's `description:`/index one-liner: change `KEEP decisions (qlnei, Run1BAna, venv pair)` to `KEEP decisions (qlnei, Run1BAna); venv pair consolidated to one .venv 2026-07-18`.

- [ ] **Step 4: Wiki — venv-relocated incident inventory + tests page**

`wiki/incidents/venv-relocated-to-data-volume.md`: add a dated note that the three venvs were consolidated into one `.venv` (same /data + symlink pattern; old dirs deleted 2026-07-18); keep the relocation story intact. Bump `timestamp:`.

`wiki/drivers/tests.md`: replace the two invocation mentions (`:5` frontmatter description and `:21-22`): `PYTHONPATH= .venv-graph/bin/python -m unittest discover -s tests -v` → `PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v`, and DELETE the line `Do NOT use .venv-botorch — its env lacks langgraph/sqlite for` (plus its continuation) — there is no wrong venv to warn about anymore. Mirror the description change in `wiki/index.md`. Bump `timestamp:`.

- [ ] **Step 5: Amend the tests/schema spec (tests_botorch/ dissolves)**

In `docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md`:
- In "Phase 0", replace the `tests_botorch/` paragraph with:

```markdown
**`tests/test_botorch_predict.py`** — main suite (the 2026-07-18 venv
consolidation put botorch in the same venv as the test runner, so no
separate suite is needed). Covers the pure parts of `botorch_predict.py`:
`_load_history_tensor` against tmp TSV fixtures (row parsing, width guard,
sob-only path), seeding (`--round-idx` → 42^idx), min-spacing filters,
picks-JSON emit; plus one tiny real GP fit + qNEHVI pick on ~10 synthetic
rows (CPU, seconds).
```

- Replace the "Cross-venv smoke" paragraph with:

```markdown
**Seam smoke** — one test: `bo_driver.botorch_ask()` q=2 against a tmp
~10-row leaderboard, exercising the subprocess seam end-to-end. The only
slow test in the suite.
```

- In "Commit sequence", change item 2 from `` `tests_botorch/` suite + cross-venv `botorch_ask` smoke `` to `` `tests/test_botorch_predict.py` + `botorch_ask` seam smoke ``.
- In "Verification", change `` `tests_botorch/` green under `.venv-botorch` (~12 tests) `` to fold into the main-suite line: `Main suite green under `.venv` (156 + ~42 new tests)`.
- In "Risks", delete the "Second test suite discoverability" bullet (moot).
- Add at the top under Status: `Amended 2026-07-18: single-venv consolidation landed first; tests_botorch/ dissolved into the main suite.`

- [ ] **Step 6: log.md + commit**

Add under `## 2026-07-18` at the TOP of `wiki/log.md` (one bullet, mention any plotter API fixes from Task 6):

```markdown
- Venv consolidation EXECUTED: one `.venv` (py3.11, botorch 0.18.1 +
  langgraph + matplotlib/sklearn) replaces .venv-graph/.venv-botorch/
  .venv-botorch-new; 0.10 retired (ml-stack verdict revised, foilsflash
  → 0.18-base, train_Yvar = next A/B); ~13 /data plotters + 2 operator
  skills re-pointed; old venvs deleted after 7 validation gates.
```

```bash
git add -- wiki/concepts/ml-stack-review-2026-07.md wiki/concepts/simplification-audit-2026-07.md wiki/incidents/venv-relocated-to-data-volume.md wiki/drivers/tests.md wiki/index.md wiki/log.md docs/superpowers/specs/2026-07-18-tests-schema-protocol-design.md
git commit -m "docs(wiki): venv consolidation — verdicts revised, old requirements retired

ml-stack verdict revision (0.10 retired, 0.18-base for foilsflash,
train_Yvar next A/B), audit venv-pair KEEP superseded, tests page ->
.venv, tests/schema spec amended (tests_botorch/ dissolves).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c"
```

(The `git rm` of the requirements files rides in this commit automatically — they are already staged.)

---

### Task 10: GATE 7 — delete the old venvs + final verification

Only runs when Tasks 2–7 gates have ALL passed and Task 9 is committed.

- [ ] **Step 1: Remove the three root symlinks (one rm per call)**

```bash
rm .venv-graph
```
```bash
rm .venv-botorch
```
```bash
rm .venv-botorch-new
```

- [ ] **Step 2: Remove the three /data venv dirs (one rm per call; frees ~8+ GB incl. the accidental 5.8 GB CUDA wheels in .venv-botorch)**

```bash
rm -rf /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv-graph
```
```bash
rm -rf /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv-botorch
```
```bash
rm -rf /exp/mu2e/data/users/oksuzian/autoresearch_venvs/.venv-botorch-new
```

- [ ] **Step 3: Final verification sweep**

```bash
ls -la .venv* ; PYTHONPATH= .venv/bin/python -m unittest discover -s tests -v 2>&1 | tail -3
```
Expected: exactly one symlink `.venv`; suite `OK` (156).

```bash
grep -rn "\.venv-graph\|\.venv-botorch" --include="*.py" --include="*.txt" core/ graph/ tests/ requirements.txt 2>/dev/null
```
Expected: no output (wiki/docs historical mentions are the only survivors repo-wide, by policy).

- [ ] **Step 4: Report**

Summarize to the user: gates passed, commits made (3), disk freed, the one-line rollback recipe (rebuild 0.10 from git-history `requirements-botorch.txt`, uv can fetch py3.9), and the reminder that all commits are local awaiting their `git push`.
