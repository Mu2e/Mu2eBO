# Run1Bak vs Run1Bap Shift Investigation

## Question
Identical geometry configurations evaluated under two software releases (Run1Bak vs Run1Bap) exhibit a **+4.9% shift in `s_over_sqrt_b`** (sob). This investigation mechanizes the elimination of possible root causes.

## 1. Inventory

### Configuration Summary

| config | s_over_sqrt_b | ce_abs_eff | ce_seen | ce_simulated_events | muminus_stops | mubeam_sim_total | stopping_factor | flash_edep_per_pot | flash_edep_events | flash_n_input | flash_n_files |
|--------|---------------|-----------|---------|-------------------|--------------|-----------------|-----------------|-------------------|-----------------|---------------|---------------|
| foilsflashSOBX01 | 3.9 | 0.0006434968099166264 | 512862 | 975000 | 248849 | 2600000 | 0.09571115384615385 | 1.080642573322103e-06 | 78985 | 19250000 |  |
| foilsflashBASIN01_00 | 3.91 | 0.0006448971175792507 | 474026 | 900000 | 229908 | 2400000 | 0.095795 | 1.0803183062259505e-06 | 45302 | 11000000 | 100 |
| foilsflashC400_champ | 3.9 | 0.000644176254979119 | 552746 | 1050000 | 268064 | 2800000 | 0.09573714285714285 | 1.0639969270327796e-06 | 179588 | 44000000 | 400 |
| ipafixAB01 | 4.1 | 0.0006755457577694941 | 580262 | 1050000 | 229532 | 2400000 | 0.09563833333333334 | 1.0358153515168671e-06 | 44625 | 10890000 | 99 |
| ipa625AB01 | 4.11 | 0.0006764205780049471 | 539022 | 975000 | 268031 | 2800000 | 0.09572535714285714 | 1.0326683685261107e-06 | 45056 | 11000000 | 100 |
| ipaovrAB01 | 4.11 | 0.0006758439092087209 | 497236 | 900000 | 229694 | 2400000 | 0.09570583333333334 | 1.0585555617218336e-06 | 44733 | 10890000 | 99 |
| foilsflashHOLEDhi | 3.11 | 0.00040782891755500897 | 530651 | 975000 | 152426 | 2600000 | 0.058625384615384614 | (no flash data) | 101403 | (no flash data) |  |
| nominalAB01 | 3.26 | 0.0004244694268978349 | 595233 | 1050000 | 152312 | 2600000 | 0.05858153846153846 | 6.854431002611723e-07 | 28206 | 11000000 | 100 |

### Artifact Availability
All 8 configurations are fully artifacted:
- `harvest/summary.json`: present for all configs (primary metric source)
- `harvest/edep.log`: present for all configs
- `harvest/rough_run1a_sensitivity.log`: present for all configs
- `harvest/nts.ce.root`: present for all configs
- `harvest/ce_files.txt`: present for all configs
- `state/mustops_ce_template_materialized.fcl`: present for all configs
- `state/mubeam_template_materialized.fcl`: present for all configs

Note: `foilsflashHOLEDhi` lacks `flash_edep_*` metrics in summary.json, consistent with its early campaign stage (count_sim_logs=1 preserved). All other configs have complete flash metrics.

### Carried Observation from Design
Comparison of run1bak vs run1bap baseline metrics across the 8-config set:
- **Stops**: −0.1% (essentially flat)
- **ce_abs_eff**: +4.75% (material accumulation or interaction bias)
- **s_over_sqrt_b**: +4.9% (the focal shift)

This pattern suggests the sob improvement is **not** driven by stop yield but by ce efficiency gains, which are proportional to the solver's photon transport or interaction modeling.

**Verdict: Inventory complete; all 8 configs fully artifacted. Ready for mechanized elimination.**
