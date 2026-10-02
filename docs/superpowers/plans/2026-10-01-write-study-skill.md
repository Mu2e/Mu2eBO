# write-study Skill Implementation Plan

> **Outcome (2026-10-02):** stopped after Task 1. The baselines passed
> without the skill; the operator chose a README section and a loader
> rule instead (see the spec's "Outcome"). Tasks 2-4 were not carried out.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project skill, `.claude/skills/write-study/SKILL.md`, that turns an operator's one-sentence description into a schema-2 study file that passes `python -m graph.check_study`, then installs it where the operator says.

**Architecture:**
- A prose skill. It holds the loop, the rules, and pointers to the sources that list the parts; it contains no parts lists of its own, and there is no new engine code.
- It is built test-first, the way superpowers:writing-skills builds skills:
  - a baseline run of a fresh subagent without the skill;
  - the skill;
  - three scenario runs with it;
  - plus a unit test that keeps the skill's file paths and required rules from going stale.

**Tech Stack:** Markdown skill with YAML frontmatter; unittest; Agent subagents (sonnet) as the test harness.

**Spec:** `docs/superpowers/specs/2026-10-01-write-study-skill-design.md`

## Global Constraints

- **Suite:** `cd /exp/mu2e/app/users/oksuzian/autoresearch-checkstudy && PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest discover -s tests -t .`. The baseline is 820 tests OK (skipped=3).
- **Subagents:** every test subagent is `general-purpose` on `sonnet`. Sonnet is the floor, never haiku. A subagent never dispatches subagents or commits.
- **Sandbox:** `SB=/exp/mu2e/data/users/oksuzian/claude-scratch/writestudy/<run>`, where `<run>` is `baseline`, `s1`, `s2` or `s3`.
  - Each run sets `AUTORESEARCH_DATA_ROOT=$SB/data` and `AUTORESEARCH_STUDY_PATH=$SB/studies`.
  - It works in the worktree `/exp/mu2e/app/users/oksuzian/autoresearch-checkstudy`, after `source ./activate.sh`.
  - Never `/tmp`.
- **Nothing outside the sandbox:**
  - no write to `mode_specs/` in either checkout;
  - no live board touched;
  - no `graph.run` or `graph.closed_loop`;
  - no submit.
- **Kerberos:** scenario 1 and the baseline check with `--executor grid`, which needs a ticket with 4 h left. Run `klist` first; if less than 4 h remain, stop and ask the operator to `kinit`. Never switch the executor.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MyWw6RZmPD7Ap3TtFRCdWM
  ```

## Review Focus

1. **A draft named like an existing study.** check_study checks a draft outside the path as a replacement for its namesake, so the check passes. Installing it into `mode_specs/` would then overwrite a production study.
   - **Expected:** a new name, unless the operator explicitly asks to replace that study, and then with a new board.
   - **Test:** Task 2's unit test asserts the skill carries the "never overwrite an existing study file" rule.
2. **A launch failure from the environment** (Kerberos, a missing `AUTORESEARCH_ANAKIT`).
   - **Expected:** the operator is told what to fix. The executor is never switched and the study is never edited to dodge it.
   - **Test:** the unit test asserts the "never change the executor" rule.
3. **"another check_study of '<name>' is running"** (the lock).
   - **Expected:** wait and re-run; the draft is not edited.
   - **Test:** the unit test asserts the skill names that message.
4. **A load failure naming another study file.**
   - **Expected:** report it to the operator; never edit a study the skill did not write.
   - **Test:** the unit test asserts the rule.
5. **A pre-check that runs long.**
   - **Expected:** wait for the background check to end (about 6 min, more under load); never kill it and declare a result.
   - **Test:** the unit test asserts the skill says to wait for the background run.

---

### Task 1: Baseline without the skill

**Files:** none in git. The findings go to the plan workspace as `baseline.md`.

**Interfaces:**
- Produces: `baseline.md`, a list of where an agent without the skill went wrong. Each item is phrased as a rule Task 2 must carry, or "already covered by rule N of the spec".

- [ ] **Step 1:** `klist` shows at least 4 h left. Create `$SB` for `baseline` with `data/` and `studies/` subdirectories.
- [ ] **Step 2: Dispatch the baseline subagent** (sonnet, general-purpose), without mentioning the skill. Its prompt carries:
  - the sandbox exports and the worktree;
  - the operator's answers: install into `$SB/studies`; the executor is grid;
  - the scenario 1 ask, verbatim: "Make a study like foilspfbpz_ax, but with only the three rOut knobs, bounds 70-110 mm; hold hT_0..2 at 0.08, f_0..2 at 0.475 and zmid at 0. Make sure it would launch.";
  - "Report every command you ran, and the final file's path."
- [ ] **Step 3: Grade the run** against the spec's pass criteria (spec, Testing). Record each miss in `baseline.md`, for example:
  - a reused board name;
  - writing into `mode_specs/`;
  - running `graph.run` to test it;
  - not knowing check_study;
  - a `{:d}` format.

  Also check the side effects yourself:
  - `git -C <both checkouts> status --short mode_specs/` is empty;
  - `find /exp/mu2e/data/users/oksuzian/autoresearch_grid -maxdepth 1 -newer $SB` is empty;
  - nothing new in `/exp/mu2e/data/users/oksuzian/autoresearch_leaderboards`.

### Task 2: The skill and its unit test

**Files:**
- Create: `.claude/skills/write-study/SKILL.md`
- Create: `tests/test_write_study_skill.py`
- Modify: `mode_specs/README.md` ("Starting a new study": one paragraph pointing at the skill)

**Interfaces:**
- Consumes: `baseline.md` from Task 1.
- Produces: `.claude/skills/write-study/SKILL.md`, with frontmatter `name: write-study` and a `description` naming its triggers. It has the sections of the spec's "The skill":
  - the loop, steps 1-7;
  - "What the skill reads", as the table;
  - "Rules the skill carries";
  - plus the five Review Focus rules and every rule `baseline.md` adds.

- [ ] **Step 1: Write the failing test** `tests/test_write_study_skill.py`, class `TestSkill`:
  - `test_frontmatter`: the file starts with `---`, its YAML has `name == "write-study"`, and `description` contains `"check_study"`.
  - `test_every_path_it_names_exists`:
    - **Candidates:** every backticked token that contains `/` and does not start with `$` or `/exp/` is a repo-relative path.
    - **Globs:** a token containing `*` must match at least one file (`ROOT.glob`).
    - **Placeholders and commands:** a token containing `<` or whitespace is skipped.
    - **Everything else** must exist under `ROOT`.
  - `test_it_carries_the_rules`: each of these substrings appears in the text, case-insensitive:
    - `"never overwrite an existing study"`
    - `"never change the executor"`
    - `"another check_study"`
    - `"never edit a study you did not write"`
    - `"wait for the background"`
    - `"exit 3"`
    - `"{:.0f}"`
    - `"leaderboard.file"`
    - `"study_drafts"`
    - `"graph.closed_loop"`
- [ ] **Step 2: Run it to see it fail.** Run: `PYTHONPATH= /cvmfs/mu2e.opensciencegrid.org/env/ana/2.8.0/bin/python -m unittest tests.test_write_study_skill -v`. Expected: 3 errors, `FileNotFoundError` for SKILL.md.
- [ ] **Step 3: Write `SKILL.md`** from the spec's "The skill" section, the Review Focus rules and `baseline.md`, in the second person ("you"), as skills are written. Keep it under ~250 lines: point at the sources, never copy them. Then add the README paragraph.
- [ ] **Step 4: Run** the test file. Expected: 3 OK. Then run the full suite. Expected: 823 OK (skipped=3).
- [ ] **Step 5: Commit**: `git commit -m "write-study: a skill that drafts a study until it passes check_study"`.

### Task 3: Scenario runs with the skill

**Files:** `.claude/skills/write-study/SKILL.md` (tightened only where a run fails). The run reports go to the plan workspace as `s1.md`, `s2.md` and `s3.md`.

**Interfaces:**
- Consumes: `SKILL.md` from Task 2.

- [ ] **Step 1: Run the three scenarios,** one fresh subagent each (sonnet, general-purpose), one after another, never in parallel: s1 and the baseline both use the shared `_code/` unpack.
  - Each prompt says: "Read and follow /exp/mu2e/app/users/oksuzian/autoresearch-checkstudy/.claude/skills/write-study/SKILL.md". Then come the sandbox exports, the operator's answers, the ask, and "Report every command you ran".
  - **s1:** Task 1's ask; grid executor; install into `$SB/studies`.
  - **s2:** "Make a study like ce_chain but with 200 events per job in the ce step."; executor local, `--parallel 1`; install into `$SB/studies`.
  - **s3:** "Make a study that optimizes calorimeter occupancy using a new calo_occupancy analysis."; install into `$SB/studies`.
- [ ] **Step 2: Grade each run** against the spec, and write `sN.md`:
  - **s1:** `check_study <name> --json` re-run by name from `$SB/studies` exits 0; a new board basename; at most 5 check rounds.
  - **s2:** the same, with geometry note `"rendered, not pre-checked"`; `events_per_job` 200 in the `ce` step.
  - **s3:** no file under `$SB/data/study_drafts` or `$SB/studies`, and the reply names "new analysis" and piece 4 (or "out of scope").
  - **All runs:** Task 1's side-effect checks are clean, and `git -C /exp/mu2e/app/users/oksuzian/autoresearch-checkstudy status --short` shows nothing but Task 2's files.
- [ ] **Step 3: Tighten and rerun.** For each failed criterion, tighten `SKILL.md` (an added or sharper rule, still tested by `test_it_carries_the_rules` if it is load-bearing) and rerun that scenario only. At most 2 tightening rounds; a scenario still failing after that is reported to the operator, not papered over.
- [ ] **Step 4: Run** `tests.test_write_study_skill`, then commit any tightening: `git commit -m "write-study: rules from the scenario runs"`.

### Task 4: Records

- [ ] **Step 1:** `wiki/drivers/contract-engine.md`: a "write-study skill (2026-10-01)" section covering:
  - what it does and where it lives;
  - the loop in one line;
  - the baseline's misses;
  - the three scenario results (rounds, exit codes).

  Also bump the frontmatter `description`/`timestamp`, the `log.md` bullet under `## 2026-10-01`, and the `index.md` one-liner.
- [ ] **Step 2:** Memory `project_phase_c1_branches.md`, plus the MEMORY.md line.
- [ ] **Step 3:** The suite is green. Then commit: `git commit -m "wiki: write-study skill"`.
