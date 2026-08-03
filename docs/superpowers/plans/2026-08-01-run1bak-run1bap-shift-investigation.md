# Run1Bak → Run1Bap +4.9% sob Shift Investigation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute the +4.9% sob shift between Run1Bak and Run1Bap evaluations at the identical champion x to a named layer (accounting / our migration / geometry-config / FCL / toolchain / Offline code), producing `docs/run1bak_run1bap_shift_evidence.md` and wiki updates.

**Architecture:** Metric-led funnel over EXISTING artifacts (no grid in Tasks 1–7): inventory → normalization audit → provenance audit → box-scan decomposition → ntuple spectra + flash accounting → environment diff → candidate ledger + wiki. Task 8 (paired Run1Bak control arm) is CONDITIONAL and operator-gated.

**Tech Stack:** python3 (stdlib) for log parsing; PyROOT under `muse setup` for `nts.ce.root`; git archaeology; cvmfs Musing environments in subagent shells.

## Global Constraints

- **Read-only investigation.** No production code changes. Analysis scripts live ONLY in `$SCRATCH` (defined below), never the repo. Results go in the evidence doc.
- `SCRATCH=/tmp/claude-11549/-exp-mu2e-app-users-oksuzian-autoresearch/b42dfdec-9da3-4c8b-a6a0-19e7f546bafa/scratchpad/shift` — create with `mkdir -p`, reuse across tasks.
- `GRID=/exp/mu2e/data/users/oksuzian/autoresearch_grid` (state dirs). Repo root: `/exp/mu2e/app/users/oksuzian/autoresearch`.
- **The 8 configs under study** (state dir = `$GRID/<name>`):
  - Historical champion (Run1Bak): `foilsflashSOBX01` (sob 3.90), `foilsflashBASIN01_00` (3.91), `foilsflashC400_champ` (3.90)
  - Run1Bap arms (same champion x): `ipafixAB01` (4.10), `ipa625AB01` (4.11), `ipaovrAB01` (4.11)
  - Baseline pair: `foilsflashHOLEDhi` (Run1Bak deployed, 3.11) vs `nominalAB01` (Run1Bap deployed, 3.26)
- Champion x (exact strings): `112.4760 109.9162 0.063100 0.144736 0.1778 0.0000`.
- Noise references for every flat/shifted claim: σ_sob **0.4%**, σ_flash **2.52% @ N=100** elebeam jobs; declared GP `obs_noise` sob 0.006.
- Commit ONLY the evidence doc (and, in Task 8 if triggered, the arm spec + test edit) with **explicit `git add` paths — never `-A`/`-u`/`.`**. Wiki edits in Task 7 stay **UNCOMMITTED** for operator review. **Never `git push`.**
- Commit trailer (verbatim, both lines):
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01R5HnfdYMwXXrJGAkYVE48c`
- Any cvmfs/muse step: `export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER` FIRST; **never pipe `muse setup`** (redirect to a file, grep the file); ROOT files are read with **PyROOT under muse**, never uproot (`NotImplementedError` on Mu2e classes).
- **No grid submission anywhere in Tasks 1–7.** Task 8 requires an explicit fresh operator approval before ANY launch.
- Evidence doc sections are appended in task order and each ends with a bold one-line **Verdict**. Write findings as they land, not at the end.

---

### Task 1: Artifact inventory + evidence doc skeleton + summary table

**Files:**
- Create: `docs/run1bak_run1bap_shift_evidence.md`
- Create: `$SCRATCH/inventory.py`, `$SCRATCH/summary_table.tsv`

**Interfaces:**
- Produces: `$SCRATCH/summary_table.tsv` (TSV: one row per config, columns exactly `config s_over_sqrt_b ce_abs_eff ce_seen ce_simulated_events muminus_stops mubeam_sim_total stopping_factor flash_edep_per_pot flash_edep_events flash_n_input flash_n_files`) — consumed by Tasks 2, 4, 5.
- Produces: the evidence doc with sections `## 1. Inventory` (later tasks append `## 2` … `## 7`).

- [ ] **Step 1: Write `$SCRATCH/inventory.py`**

```python
#!/usr/bin/env python3
import json, glob, os
GRID = "/exp/mu2e/data/users/oksuzian/autoresearch_grid"
CONFIGS = ["foilsflashSOBX01", "foilsflashBASIN01_00", "foilsflashC400_champ",
           "ipafixAB01", "ipa625AB01", "ipaovrAB01",
           "foilsflashHOLEDhi", "nominalAB01"]
COLS = ["s_over_sqrt_b", "ce_abs_eff", "ce_seen", "ce_simulated_events",
        "muminus_stops", "mubeam_sim_total", "stopping_factor",
        "flash_edep_per_pot", "flash_edep_events", "flash_n_input"]
ARTIFACTS = {  # relative path pattern -> label
    "harvest/summary.json": "summary", "harvest/edep.log": "edep",
    "harvest/rough_run1a_sensitivity.log": "boxscan",
    "harvest/nts.ce.root": "nts", "harvest/ce_files.txt": "cefiles",
    "state/mustops_ce_template_materialized.fcl": "fcl_ce",
    "state/mubeam_template_materialized.fcl": "fcl_mubeam",
}
rows, missing = [], []
for c in CONFIGS:
    d = os.path.join(GRID, c)
    s = json.load(open(os.path.join(d, "harvest/summary.json")))
    n_files = (s.get("flash_perfile_stats") or {}).get("n_files", "")
    n_countsim = len(glob.glob(os.path.join(d, "harvest/count_sim.*.log")))
    tarballs = [os.path.basename(p) for p in glob.glob(os.path.join(d, "Code.*.tar.bz2"))]
    rows.append([c] + [str(s.get(k)) for k in COLS] + [str(n_files)])
    for rel, label in ARTIFACTS.items():
        if not os.path.exists(os.path.join(d, rel)):
            missing.append(f"{c}: MISSING {rel}")
    print(f"{c}: count_sim_logs={n_countsim} preserved_tarball={tarballs}")
out = "/tmp/claude-11549/-exp-mu2e-app-users-oksuzian-autoresearch/b42dfdec-9da3-4c8b-a6a0-19e7f546bafa/scratchpad/shift/summary_table.tsv"
with open(out, "w") as f:
    f.write("\t".join(["config"] + COLS + ["flash_n_files"]) + "\n")
    for r in rows: f.write("\t".join(r) + "\n")
print("MISSING:", missing or "none")
```

- [ ] **Step 2: Run it and verify**

Run: `mkdir -p $SCRATCH && python3 $SCRATCH/inventory.py`
Expected: 8 config lines; `summary_table.tsv` has 9 lines; spot-check `foilsflashBASIN01_00` sob=3.91, `ipafixAB01` sob=4.1, `nominalAB01` sob=3.26. Record any MISSING artifacts (a missing artifact is a *finding to record*, not a stop — fall back to the surviving replicas per the spec's error handling).

- [ ] **Step 3: Create the evidence doc**

`docs/run1bak_run1bap_shift_evidence.md` — header stating the question (+4.9% sob at identical champion x, elimination result to be confirmed/mechanized), the 8-config table (markdown rendering of `summary_table.tsv`), the artifact-availability notes, and this observation carried from the design: stops flat (−0.1%), `ce_abs_eff` +4.75%, sob +4.9%. Section heading `## 1. Inventory`, ending with **Verdict: inventory complete; N configs fully-artifacted**.

- [ ] **Step 4: Commit**

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): shift investigation — artifact inventory + summary table"
```
(with the Global Constraints trailer lines in the message body.)

---

### Task 2: Normalization audit — recompute sob/ce_abs_eff from raw logs

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 2. Normalization audit`)
- Create: `$SCRATCH/recompute.py`
- Read: `core/pipeline.py:1275-1420`, `core/harvest.py:20-140`

**Interfaces:**
- Consumes: `$SCRATCH/summary_table.tsv` (Task 1).
- Produces: evidence section stating the exact formulas and the **loss-corrected shift value** — Tasks 4 and 7 quote it.

- [ ] **Step 1: Document the formulas from code**

Read `core/pipeline.py:1275-1420` and `core/harvest.py:20-140`. Write into the evidence doc, verbatim from code (line-cited):
- `stopping_factor = muminus_stops / mubeam_sim_total`
- `ce_scale = RUN1A_MUBEAM_INPUT_CORRECTION * stopping_factor / ce_simulated_events` with `RUN1A_MUBEAM_INPUT_CORRECTION = 0.01278168` (`core/harvest.py:30`)
- `ce_abs_eff = ce_seen * ce_scale`
- `s_over_sqrt_b = run_sensitivity_macro(harvest_dir, nts_path, ce_abs_eff, ...)` (`core/pipeline.py:1346`, macro driver `core/harvest.py:98`) — record which macro file it runs and which stdout line it parses for the returned sob.
- **The key semantics question:** for each of `mubeam_sim_total`, `ce_simulated_events`, `ce_seen` — is the value derived from LANDED files or SUBMITTED jobs? Cite the exact lines that build each (e.g. where `ce_simulated_events` is computed from `ce_files.txt` length × events-per-job, or from stamped submit counts). This decides whether job loss can bias `ce_abs_eff`.

- [ ] **Step 2: Write `$SCRATCH/recompute.py`**

For each of the 8 configs, from raw artifacts only (not summary.json):
- `ce_seen`: parse `harvest/edep.log` line `EdepAna summary: Saw N events` → regex `Saw ([\d.e+]+) events` with `int(float(...))` (scientific-notation guard per wiki incident `edepana-saw-events-scientific-notation-parse`).
- `muminus_stops`: sum the per-job counts from `harvest/count_sim.*.log`. First `tail -20` ONE such log to identify the count line format, and cross-check the parse against `_count_events_art` in `core/pipeline.py` (~line 1329 call site) — reuse its regex verbatim.
- Landed-file counts: `wc -l` on `harvest/ce_files.txt`, `state/mustops_ce_outputs.txt`, `state/mubeam_outputs.txt`, `state/elebeam_flash_outputs.txt`; events-per-job from `state/<stage>_events_per_job.txt`.
- Recompute `stopping_factor`, `ce_abs_eff` with the code's formula; print side-by-side with summary.json values and the ratio.

- [ ] **Step 3: Run and verify the recompute closes**

Run: `python3 $SCRATCH/recompute.py`
Expected: recomputed `ce_abs_eff` matches summary.json to <0.1% for every config (proves formula understanding). If it does not close, find why before proceeding — a non-closing recompute is itself a candidate finding.

- [ ] **Step 4: Compute the loss-consistent shift**

Using the Step-1 semantics: if any denominator is submitted-based while its numerator is landed-based, recompute `ce_abs_eff` for all configs on a fully landed-consistent basis, then restate the historical→arm ratio (mean of 3 historical vs mean of 3 arms). Also restate the baseline pair (HOLEDhi → nominalAB01). State each ratio ± the σ implied by counting statistics (`1/√N` on `ce_seen` and `muminus_stops`).

- [ ] **Step 5: Constants/macro drift check**

```bash
git log --oneline --since=2026-06-25 -- core/harvest.py core/pipeline.py
```
Inspect any commit in the window touching `RUN1A_MUBEAM_INPUT_CORRECTION`, `run_edepana`, `run_sensitivity_macro`, or `sourced_env`: did the numeric constants or the macro file change between the historical harvest dates (SOBX01 2026-07-08 … BASIN01 ~2026-07-2x) and the A/B harvests (2026-07-28/29)? Also record the sensitivity-macro file's identity (path + `git log -1` date, or mtime if off-repo).

- [ ] **Step 6: Append evidence + commit**

Section `## 2. Normalization audit` with the formulas, the closure table, the loss-consistent shift, the constants check, ending **Verdict: shift survives audit at +X.X% ± Y%** (or **Verdict: accounting artifact — root cause found**, in which case later tasks contract to writing it up).

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): normalization audit — <one-line verdict>"
```

---

### Task 3: Provenance audit — rendered-geom diffs, tarball gates, harvest env pinning

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 3. Provenance audit`)
- Create: `$SCRATCH/geomdiff.sh`

**Interfaces:**
- Consumes: config list (Global Constraints).
- Produces: evidence section = the "rule out our own bug" verdict; Task 7's ledger cites it.

- [ ] **Step 1: Pairwise rendered-geom diffs**

The rendered geometry is `$GRID/<config>/geom/*.txt` (glob it; one file per config). Diff with comments stripped:

```bash
strip() { sed -e 's://.*$::' -e 's/^#.*$//' -e '/^\s*$/d' "$1"; }
diff <(strip $GRID/foilsflashBASIN01_00/geom/*.txt) <(strip $GRID/ipafixAB01/geom/*.txt)
```

Four pairs, each with an EXPECTED delta class — any hunk outside it is a finding:
1. `foilsflashBASIN01_00` vs `ipafixAB01`: override pair (`tracker.inDS2Vacuum`, `ds2.halfLength`) removed; `protonabsorber.distFromTargetEnd` 625 → 491.666672; `zEMCSourceInMu2e` handling; nothing else.
2. `ipafixAB01` vs `ipaovrAB01`: EXACTLY the override pair restored.
3. `ipafixAB01` vs `ipa625AB01`: EXACTLY the one `distFromTargetEnd` line.
4. `foilsflashHOLEDhi` vs `nominalAB01`: NOT one-line — the deployed stack is emitted via env-seam (`N_UP=N_DOWN=0`) in HOLEDhi vs explicit `base_*` consts in nominal. Enumerate every hunk and classify equivalent-vs-real; this pair's comparability caveat goes in the evidence verbatim.

- [ ] **Step 2: Tarball provenance + strings gates**

Per config: provenance from `grep -ho "[^ ]*tar.bz2" $GRID/<config>/graph_logs/submit_mubeam_*.log | sort -u`. Expected: historical + HOLEDhi → `Code_helical_holeradii.tar.bz2`; all four arms → `Code_run1bap_holeradii.tar.bz2`. Then extract the GeometryService lib from each DISTINCT tarball (preserved in-dir copy `Code.*.tar.bz2` if present, else the `autoresearch_muse/` original) into `$SCRATCH` and gate:

```bash
tar -xjf <tarball> -C $SCRATCH/tb_<name> --wildcards "*libmu2e_GeometryService*" 
strings $SCRATCH/tb_<name>/**/libmu2e_GeometryService.so | grep -c "holeRadii vector active"
```
Expected: marker present (=1) in BOTH tarballs — both sides ran the holeRadii-patched maker. (If the lib path inside the tarball differs, `tar -tjf | grep GeometryService` first.) Absence on either side is a major finding.

- [ ] **Step 3: Harvest env pinning + naming note**

Read `core/pipeline.py:423-451` (`sourced_env(with_muse=True)`): confirm the harvest muse environment is pinned (Run1Bak/p094-era EdepAna) independent of the mode's simulation musing, and quote the pinning lines in the evidence. From Task 2 Step 5's git log, confirm no commit in the window changed it. Note explicitly that `harvest/count_sim.*.log` filenames embed `Run1Bak_<config>` for ARM configs too — naming template, cosmetic; state where the name string comes from (grep `TargetStops` in `core/pipeline.py`).

- [ ] **Step 4: Append evidence + commit**

Section ends **Verdict: our migration ruled out / NOT ruled out (finding: …)**.

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): provenance audit — <one-line verdict>"
```

---

### Task 4: Box-scan decomposition — fixed-box vs box-migration vs background

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 4. Box-scan decomposition`)
- Create: `$SCRATCH/boxscan.py`, `$SCRATCH/boxscan_<config>.tsv`

**Interfaces:**
- Consumes: Task 2's formula finding (how the macro consumes `ce_abs_eff` and which line yields the final sob).
- Produces: the three-way split of the +4.9% (acceptance @ fixed box / box migration / background) — Task 7's ledger and Phase-3 targeting depend on it.

- [ ] **Step 1: Identify the final-sob line**

From Task 2's reading of `core/harvest.py:98` (`run_sensitivity_macro`), record which stdout line the driver parses for the returned `s_over_sqrt_b` and how the macro turns the raw scan (values ~1e-8 in the log) into the ~3.9 final number (normalization factors, Run-1 POT scaling, and where `ce_abs_eff` enters — signal scaling). Cite macro source lines.

- [ ] **Step 2: Write `$SCRATCH/boxscan.py`**

```python
#!/usr/bin/env python3
import re, sys, os
GRID = "/exp/mu2e/data/users/oksuzian/autoresearch_grid"
PAT = re.compile(r"Test box = \[([\d.]+), ([\d.]+)\] MeV/c, signal = ([\d.e+-]+), "
                 r"dio = ([\d.e+-]+), cosmic = ([\d.e+-]+) --> bkg = ([\d.e+-]+), "
                 r"S/sqrt\(B\) = ([\d.e+-]+)")
def scan(cfg):
    rows = []
    for line in open(os.path.join(GRID, cfg, "harvest/rough_run1a_sensitivity.log")):
        m = PAT.search(line)
        if m: rows.append(tuple(float(g) for g in m.groups()))
    return rows  # (lo, hi, signal, dio, cosmic, bkg, sob)
def best(rows): return max(rows, key=lambda r: r[6])
configs = ["foilsflashSOBX01","foilsflashBASIN01_00","foilsflashC400_champ",
           "ipafixAB01","ipa625AB01","ipaovrAB01","foilsflashHOLEDhi","nominalAB01"]
data = {c: scan(c) for c in configs}
ref_box = best(data["foilsflashBASIN01_00"])[:2]
for c in configs:
    b = best(data[c])
    fixed = next(r for r in data[c] if r[:2] == ref_box)
    print(f"{c}: argmax_box=[{b[0]},{b[1]}] sob_at_own={b[6]:.4g} "
          f"sob_at_ref={fixed[6]:.4g} signal_at_ref={fixed[2]:.4g} "
          f"dio_at_ref={fixed[3]:.4g} cosmic_at_ref={fixed[4]:.4g}")
```
Also dump each config's full scan to `$SCRATCH/boxscan_<config>.tsv`. If the exact-tuple box match (`r[:2] == ref_box`) fails because the scan grids differ across configs, match with `abs(r[0]-ref_box[0]) < 1e-6 and abs(r[1]-ref_box[1]) < 1e-6` — and if the grids genuinely differ, that itself is a finding (the macro's scan range changed).

- [ ] **Step 3: Run and decompose**

Run: `python3 $SCRATCH/boxscan.py`
Compute and tabulate (mean over 3 historical vs mean over 3 arms, at the FIXED reference box): signal ratio, dio ratio, cosmic ratio, sob ratio; and separately the argmax-box locations. Answer three questions numerically:
1. Did the optimal box move between Run1Bak and Run1Bap? (If yes, by how much and what does sob-at-fixed-box alone shift?)
2. At fixed box, what fraction of the +4.9% is signal-side vs background-side?
3. Is the signal-side ratio consistent with the Task-2 `ce_abs_eff` ratio (i.e. pure normalization input), or is there a residual spectrum/shape effect? (`sob_ratio / expected-from-ce_abs_eff` — state the residual %.)
Repeat the same three answers for the baseline pair (HOLEDhi vs nominalAB01).

- [ ] **Step 4: Append evidence + commit**

Section ends **Verdict: +4.9% = A% acceptance-at-fixed-box + B% box-migration + C% background, with residual-beyond-ce_abs_eff = D%**.

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): box-scan decomposition — <one-line verdict>"
```

---

### Task 5: CE spectra (PyROOT) + flash-side accounting

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 5. Spectra + flash`)
- Create: `$SCRATCH/spectra.py`, optional PNGs in `$SCRATCH/`

**Interfaces:**
- Consumes: Task 4's residual (does a spectrum effect need explaining at all?).
- Produces: spectrum verdict + flash-shift ledger rows for Task 7.

- [ ] **Step 1: Write `$SCRATCH/spectra.py` (PyROOT)**

```python
#!/usr/bin/env python3
import ROOT, sys
ROOT.gROOT.SetBatch(True)
GRID = "/exp/mu2e/data/users/oksuzian/autoresearch_grid"
def load(cfg):
    f = ROOT.TFile.Open(f"{GRID}/{cfg}/harvest/nts.ce.root")
    t = f.Get("t1")
    if not t:
        f.ls(); sys.exit(f"{cfg}: no t1 — inspect the file listing above")
    return f, t
pairs = [("foilsflashBASIN01_00", "ipafixAB01"), ("foilsflashHOLEDhi", "nominalAB01")]
for a, b in pairs:
    fa, ta = load(a); fb, tb = load(b)
    ha = ROOT.TH1D("ha", a, 120, 90, 110); hb = ROOT.TH1D("hb", b, 120, 90, 110)
    ta.Draw("e>>ha", "w", "goff"); tb.Draw("e>>hb", "w", "goff")
    print(f"{a}: entries={ta.GetEntries()} wmean={ha.GetMean():.4f} rms={ha.GetRMS():.4f}")
    print(f"{b}: entries={tb.GetEntries()} wmean={hb.GetMean():.4f} rms={hb.GetRMS():.4f}")
    if ha.Integral() and hb.Integral():
        ha.Scale(1/ha.Integral()); hb.Scale(1/hb.Integral())
        print(f"KS prob = {ha.KolmogorovTest(hb):.4g}")
    c = ROOT.TCanvas(); ha.SetLineColor(2); ha.Draw("hist"); hb.Draw("hist same")
    c.SaveAs(f"/tmp/claude-11549/-exp-mu2e-app-users-oksuzian-autoresearch/b42dfdec-9da3-4c8b-a6a0-19e7f546bafa/scratchpad/shift/spec_{a}_vs_{b}.png")
```
Before trusting branch names, run once with `t.Print()` added if `Draw("e>>ha","w")` errors — the branches seen in macro output are `t1.e` and `t1.w`; adjust the axis range to the branch's actual unit (CE momentum endpoint ~104.97 MeV/c) if the first histogram lands empty.

- [ ] **Step 2: Run under muse (subagent shell)**

```bash
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
muse setup > /tmp/muse_setup.log 2>&1
python3 $SCRATCH/spectra.py
```
Expected: per-config entries/mean/RMS + KS prob for both pairs. Note: the nts files are on /exp (CephFS), not /pnfs — no NFS-hang risk. Read the saved PNGs with the Read tool to eyeball shape differences.

- [ ] **Step 3: Flash-side accounting (no ROOT needed)**

Build the flash table from `summary_table.tsv` + these known numbers: champion historical flash 1.08064 / 1.08032 / 1.06400e-6 (n=3); arms 1.0358 (A) / 1.0327 (B) / **1.05856 (C, override restored)**; baseline 6.445e-7 (HOLEDhi) → 6.854e-7 (nominal, +6.3%). Quantify: (a) override-pair contribution = C vs mean(A,B) = +2.2%; (b) residual version shift = historical mean vs C; (c) the baseline pair's OPPOSITE sign, with its two confounds stated: HOLEDhi ran at 400 elebeam jobs (σ_flash ~1.3%) vs nominal at 100 (σ 2.52%), and the two emit the deployed stack by different mechanisms (Task 3 Step 1 pair 4). State every number ± σ, using the near-paired-seed argument (`baseSeed = index+1`, deterministic) where job counts match.

- [ ] **Step 4: Append evidence + commit**

Section ends **Verdict: CE spectrum shifted/unshifted (KS=…); flash shift = override (+2.2%) + version (X% ± σ), baseline-pair sign discussed**.

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): CE spectra + flash accounting — <one-line verdict>"
```

---

### Task 6: Targeted environment diff — geometry config, job config, toolchain

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 6. Environment diff`)
- Create: `$SCRATCH/resolve_geom.py`, `$SCRATCH/cfg_bak.txt`, `$SCRATCH/cfg_bap.txt`

**Interfaces:**
- Consumes: Tasks 4–5's implicated quantity (to classify which diffs can matter).
- Produces: the candidate list Task 7 ranks.

- [ ] **Step 1: Locate both base geometry trees**

```bash
find -L /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bak -maxdepth 7 -name geom_run1_a.txt 2>/dev/null
find -L /cvmfs/mu2e.opensciencegrid.org/Musings/SimJob/Run1Bap -maxdepth 7 -name geom_run1_a.txt 2>/dev/null
```
Record both absolute paths and their containing Offline release roots (the directory holding `Mu2eG4/geom/`). If `find` returns nothing, source each musing in a subagent shell and locate via `echo $MU2E_SEARCH_PATH`.

- [ ] **Step 2: Write `$SCRATCH/resolve_geom.py`** — SimpleConfig include-chain resolver

```python
#!/usr/bin/env python3
import re, sys, os
INC = re.compile(r'^\s*#include\s+"([^"]+)"')
KV  = re.compile(r'^\s*(?:double|int|bool|string|vector<[^>]+>)\s+([\w.]+)\s*=\s*(.+?);')
def resolve(path, root, kv, seen):
    buf = ""
    for raw in open(path):
        line = raw.split("//")[0]
        m = INC.match(line)
        if m:
            inc = os.path.join(root, m.group(1))
            if not os.path.exists(inc):
                inc = os.path.join(root, "Offline", m.group(1))  # both root layouts occur
            if inc not in seen:
                seen.add(inc); resolve(inc, root, kv, seen)
            continue
        buf += " " + line.strip()
        if ";" not in buf:      # vector<...> values span lines; accumulate to ';'
            continue
        m = KV.match(buf.strip())
        if m: kv[m.group(1)] = m.group(2).strip()   # last-wins, SimpleConfig semantics
        buf = ""
    return kv
def full(base, root): return resolve(base, root, {}, set())
a = full(sys.argv[1], sys.argv[2]); b = full(sys.argv[3], sys.argv[4])
keys = sorted(set(a) | set(b))
for k in keys:
    va, vb = a.get(k, "<ABSENT>"), b.get(k, "<ABSENT>")
    if va != vb: print(f"{k}: {va}  ->  {vb}")
print(f"# total keys: bak={len(a)} bap={len(b)} differing={sum(1 for k in keys if a.get(k)!=b.get(k))}")
```

- [ ] **Step 3: Self-test then diff**

Run first with the SAME tree on both sides — Expected: `differing=0` (validates the resolver). Then Run1Bak-tree vs Run1Bap-tree. Classify every differing key into: (relevant to CE chain: tracker/DS/stopping-target/absorber/materials/physics) vs (irrelevant: unrelated subsystems). The relevant list is the geometry-config candidate set. Note the caveat: include paths may be relative to the release root as `Offline/...` or bare `Mu2eG4/...` — handle both by trying `root/inc` then `root/Offline/inc`.

- [ ] **Step 4: Job-config diff (`mu2e --debug-config`, subagent shells)**

First diff the two materialized FCLs directly (ours): `diff $GRID/foilsflashBASIN01_00/state/mustops_ce_template_materialized.fcl $GRID/ipafixAB01/state/mustops_ce_template_materialized.fcl` — expected near-identical modulo config-name paths; any semantic delta is a finding. Then, in TWO separate subagent shells (muse setup is one-shot per shell):

```bash
# shell 1 (Run1Bak):
export SPACK_USER_CACHE_PATH=/tmp/spack_cache_$USER
source /cvmfs/mu2e.opensciencegrid.org/setupmu2e-art.sh
muse setup ops > /tmp/m1.log 2>&1 && muse setup SimJob Run1Bak >> /tmp/m1.log 2>&1
mu2e --debug-config $SCRATCH/cfg_bak.txt -c $GRID/foilsflashBASIN01_00/state/mustops_ce_template_materialized.fcl
# shell 2 (Run1Bap): same with Run1Bap and the ipafixAB01 FCL -> cfg_bap.txt
```
Then `diff $SCRATCH/cfg_bak.txt $SCRATCH/cfg_bap.txt` filtering obvious noise (absolute paths containing the config names, seeds). Every surviving delta = Production/Offline FCL-prolog candidate. (`--debug-config` only resolves configuration; it does not open input files.)

- [ ] **Step 5: Toolchain versions**

In the same two shells: `ups active | grep -iE "^geant4|^art |^root |^g4|^xerces|^cry |^artg4" ; muse status`. Record Geant4/art/ROOT versions + ENVSET (expect p094-era vs p101) side by side. A Geant4 version change is a first-class candidate; art/ROOT are bookkeeping.

- [ ] **Step 6: Append evidence + commit**

Section ends **Verdict: candidate deltas = [list], toolchain = G4 X→Y, art …**.

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): environment diff — <one-line verdict>"
```

---

### Task 7: Scoped Offline sweep, candidate ledger, recommendation, wiki

**Files:**
- Modify: `docs/run1bak_run1bap_shift_evidence.md` (append `## 7. Candidate ledger + recommendation`)
- Modify (UNCOMMITTED): `wiki/projects/bo-foilsflash.md`, `wiki/log.md`, `wiki/index.md`
- Create (UNCOMMITTED): `wiki/concepts/run1bak-run1bap-sob-shift.md`

**Interfaces:**
- Consumes: verdicts of Tasks 2–6.
- Produces: final ledger + the leaderboard-decision input; the Task-8 trigger decision.

- [ ] **Step 1: Scoped Offline release sweep**

Scope = the subsystem(s) implicated by Tasks 4–6 (e.g. `Mu2eG4/`, `TrackerMC/`, EM physics config — NOT a blind 20-version sweep). The sparse clone at `/exp/mu2e/app/users/oksuzian/Offline_ipa_pr` has full history:

```bash
git -C /exp/mu2e/app/users/oksuzian/Offline_ipa_pr fetch --tags origin 2>/dev/null
git -C /exp/mu2e/app/users/oksuzian/Offline_ipa_pr log --oneline v13_12_10..v13_32_10 -- <implicated paths>
```
If the tags are absent, fall back to `gh api repos/Mu2e/Offline/releases --paginate -q '.[].tag_name'` to find the range and read release notes via `gh release view <tag> -R Mu2e/Offline`. Also record the Geant4 delta's own release notes if Task 6 found a G4 bump. List commits/notes plausibly explaining the Task-4/5 quantity.

- [ ] **Step 2: Candidate ledger**

Markdown table in the evidence doc — every candidate ever raised, one row each: candidate | status (`excluded` / `confirmed` / `open`) | evidence (task/measurement) | strength (direct-paired / elimination / inspection). Must include at minimum: IPA position, override pair, `zEMCSourceInMu2e`, analysis binary, job-loss accounting, our tarball/geom migration, base-geometry config deltas, Production FCL deltas, Geant4 version, Offline code (scoped commits).

- [ ] **Step 3: Recommendation input + Task-8 trigger decision**

Write the leaderboard-decision *input* (not the decision): e.g. whether the shift is multiplicative and geometry-independent within measurement (champion +4.9% vs baseline +4.8% is the existing evidence; state what Tasks 2–6 added). Then state the Phase-4 trigger verdict per the spec: **≥2 live candidates or one needing direct proof → recommend Task 8 arm(s); else → investigation closes without grid.**

- [ ] **Step 4: Wiki updates (edit, do NOT commit)**

- `wiki/concepts/run1bak-run1bap-sob-shift.md` (new, `type: concept`, full OKF frontmatter): the shift, the decomposition, the ledger summary, cross-links to `bo-foilsflash`, `bo-noise-budget`, the evidence doc path.
- `wiki/projects/bo-foilsflash.md`: update the migration Key-facts block with the mechanism findings; bump timestamp.
- `wiki/log.md`: bullet(s) under `## 2026-08-01` (or current date) at TOP.
- `wiki/index.md`: one-line entry for the new concept page.

- [ ] **Step 5: Commit evidence doc only**

```bash
git add docs/run1bak_run1bap_shift_evidence.md
git commit -m "docs(evidence): candidate ledger + recommendation — <one-line verdict>"
git status --short wiki/   # confirm wiki edits present and UNCOMMITTED
```

---

### Task 8 (CONDITIONAL — runs ONLY if Task 7 triggers it AND the operator freshly approves): Run1Bak control arm

**Files:**
- Create: `mode_specs/bakctl.json`
- Modify: `tests/test_modes.py` (`SHIPPED_SPECS` — temporary extension, same discipline as the 2026-07-28 A/B arms)
- Create (by the run): `leaderboards/leaderboard_ab_bakctl.tsv`

**Interfaces:**
- Consumes: Task 7's trigger verdict; the historical spec = `git show 42ced1d~1:mode_specs/foilsflash.json` (pre-Run1Bap-migration foilsflash: musing `/exp/mu2e/app/users/oksuzian/Offline_helical/setup_local.sh`, tarball `/exp/mu2e/app/users/oksuzian/autoresearch_muse/Code_helical_holeradii.tar.bz2`, override pair present, `distFromTargetEnd` 625).
- Produces: one leaderboard row; expected sob **3.90 ± 0.02** (σ_sob 0.4%) confirms the version bump; ~4.10 refutes it and reopens the audit.

- [ ] **Step 1: Build the spec from the pre-migration snapshot**

```bash
git show 42ced1d~1:mode_specs/foilsflash.json > mode_specs/bakctl.json
```
Edit `mode_specs/bakctl.json`: `"name": "bakctl"`; `"note"`: "Run1Bak control arm for the +4.9% shift — historical foilsflash environment + geometry, evaluated by today's harness at the champion x. Throwaway; DELETE after the measurement."; `"leaderboard.file"`: `"leaderboards/leaderboard_ab_bakctl.tsv"`. If the current loader requires fields the old snapshot lacks (e.g. `require_zero_overlaps` — REQUIRED since 2026-07-28), add them with the historical-compatible value (`"require_zero_overlaps": false` — the classic 1 `EMC_0_Front` overlap is EXPECTED here). Do not change musing/tarball/geometry lines.

- [ ] **Step 2: Extend `SHIPPED_SPECS` + load-verify**

Add `"bakctl"` to `SHIPPED_SPECS` in `tests/test_modes.py` (same temporary pattern the A/B arms used). Run: `PYTHONPATH= .venv/bin/python -m unittest tests.test_modes -v` — Expected: PASS (spec loads, guard satisfied).

- [ ] **Step 3: Render + verify the geometry replicates history**

Render the proposal at the forced champion x, then run the production preflight (both in a muse-capable subagent shell — the driver sources its own env internally):

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch
.venv/bin/python -c "
import core.proposals_io as pio
x = [112.4760, 109.9162, 0.063100, 0.144736, 0.1778, 0.0000]
print(pio.propose_one('bakctl', 'bakctlPRE01', x_override=x))"
PYTHONPATH= .venv/bin/python core/bo_driver.py --mode bakctl preflight bakctlPRE01
```
(`propose_one(mode, name, x_override=...)` is the same forced-x seam `graph/nodes.py:node_propose:76` uses; it leaves a pending row in `leaderboards/pending_bo_bakctl.tsv` — throwaway, removed at cleanup.) Expected: PASS with exactly **1 overlap (`VirtualDetector_EMC_0_Front`)** — the 461-eval historical constant. Then diff the rendered geom (comments stripped, Task-3 `strip` recipe) against `$GRID/foilsflashBASIN01_00/geom/*.txt` — Expected: identical except config-name strings. Any other hunk = STOP, fix the spec.

- [ ] **Step 4: STOP — operator approval gate**

Report readiness + the exact launch command to the operator and WAIT for explicit approval. Do not launch without it.

- [ ] **Step 5: Launch (after approval) + monitor**

```bash
cd /exp/mu2e/app/users/oksuzian/autoresearch && source .venv/bin/activate
nohup python -m graph.run --thread-id bakctlAB01 --config-name bakctlAB01 \
  --mode bakctl --x-point 112.4760,109.9162,0.063100,0.144736,0.1778,0.0000 \
  --no-mock > /exp/mu2e/data/users/oksuzian/autoresearch_graph_data/bakctlAB01.log 2>&1 &
echo "PID=$!"
```
Kerberos must be fresh (mid-run expiry kills the chain — wiki incident). Monitor per the launch-bo-chain skill pattern (~4–5 h). On landing: read `leaderboards/leaderboard_ab_bakctl.tsv` + `$GRID/bakctlAB01/harvest/summary.json`.

- [ ] **Step 6: Evidence + commit + cleanup marker**

Append the result to evidence `## 8. Run1Bak control arm` with the ladder updated (3.90/3.91/3.90 | bakctl | 4.10/4.11/4.11) and the confirmed/refuted verdict; update the Task-7 ledger row.

```bash
git add docs/run1bak_run1bap_shift_evidence.md mode_specs/bakctl.json tests/test_modes.py
git commit -m "feat(bakctl): Run1Bak control arm — <confirmed/refuted> the version-bump attribution"
```
Note in the evidence doc: `bakctl.json` + its `SHIPPED_SPECS` line join the four A/B specs in the pending operator-approved deletion.

**Config-level arm variants** (if Task 7 named a config-level candidate instead): clone `mode_specs/ipafix.json` → `mode_specs/<candidate>.json`, revert ONLY the candidate line(s) to their Run1Bak-resolved values (from Task 6's diff), own leaderboard `leaderboard_ab_<candidate>.tsv`, same Steps 2–6 discipline. One arm at a time, each individually operator-approved.
