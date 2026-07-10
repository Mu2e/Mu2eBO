# Retire the cl_min picker; the closed loop depends only on in-repo pickers

The `--picker cl_min` path imported per-mode `gp_predict_*.py` scripts from the
off-repo, unversioned `mmackenz_table_plots` directory via an if/elif chain
(`graph/closed_loop.py:_import_gp`) that silently lacked prodtarget support.
Decided 2026-07-06: delete `_import_gp` and the cl_min path entirely —
`qnehvi`/`qlnei`/`pareto_sob` (all driven by in-repo `botorch_predict.py`) have
been the only pickers used since 2026-06. The external scripts remain for
plotting only; the closed loop must never again import code that isn't
versioned in this repo. If a skopt-style picker is needed later, port it into
the repo rather than re-adding the path injection.
